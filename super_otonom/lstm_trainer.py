from __future__ import annotations

"""
LSTMTrainer v1.0
─────────────────────────────────────────────────────────────────────────────
LSTM model eğitim pipeline'ı.

AILayer'ın inference için beklediği modeli (.pt) üretir:
    Input:  (batch, seq_len=30, features=8)
    Output: (batch, 3) → [BUY_prob, SELL_prob, HOLD_prob]

Veri kaynağı:
    1. TimescaleDB (klines tablosu) — tercih edilen
    2. CSV dosyası (data/klines_*.csv) — offline fallback

Kullanım:
    trainer = LSTMTrainer()
    trainer.load_data("BTCUSDT", "1h", days=180)
    trainer.train(epochs=50)
    trainer.save("data/lstm_model.pt")
    trainer.evaluate()

CLI:
    python -m super_otonom.lstm_trainer --symbol BTCUSDT --timeframe 1h --epochs 50
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger("super_otonom.lstm_trainer")

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    log.warning("PyTorch kurulu değil — pip install torch")

try:
    import pandas as pd

    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False

# ── Config ──────────────────────────────────────────────────────────────

SEQ_LEN = 30       # ai_layer.py ile senkron
N_FEATURES = 8     # ai_layer.py ile senkron
N_HIDDEN = 64      # ai_layer.py ile senkron
N_CLASSES = 3       # BUY, SELL, HOLD
BATCH_SIZE = 64
LEARNING_RATE = 1e-3
DEFAULT_EPOCHS = 50
TRAIN_SPLIT = 0.8
LABEL_THRESHOLD = 0.015  # %1.5 hareket → BUY/SELL sinyal


# ── LSTM Model ──────────────────────────────────────────────────────────

if _TORCH_AVAILABLE:

    class TradingLSTM(nn.Module):
        """AILayer ile uyumlu LSTM modeli."""

        def __init__(
            self,
            input_size: int = N_FEATURES,
            hidden_size: int = N_HIDDEN,
            num_classes: int = N_CLASSES,
            num_layers: int = 2,
            dropout: float = 0.3,
        ):
            super().__init__()
            self.hidden_size = hidden_size
            self.num_layers = num_layers

            self.lstm = nn.LSTM(
                input_size=input_size,
                hidden_size=hidden_size,
                num_layers=num_layers,
                batch_first=True,
                dropout=dropout if num_layers > 1 else 0,
            )
            self.bn = nn.BatchNorm1d(hidden_size)
            self.dropout = nn.Dropout(dropout)
            self.fc = nn.Linear(hidden_size, num_classes)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            # x: (batch, seq_len, features)
            lstm_out, _ = self.lstm(x)
            last = lstm_out[:, -1, :]  # Son timestep
            out = self.bn(last)
            out = self.dropout(out)
            out = self.fc(out)
            return out


# ── Feature Engineering ─────────────────────────────────────────────────

def _compute_features(df: "pd.DataFrame") -> np.ndarray:
    """
    OHLCV → 8 feature (ai_layer._extract_features ile uyumlu).

    Features:
        0: (open - close) / close
        1: (high - close) / close
        2: (low - close) / close
        3: close pct change
        4: volume ratio (vol / rolling_mean_vol) / 10, capped at 1
        5: RSI / 100
        6: EMA diff (clipped)
        7: Bollinger %B
    """
    close = df["close"].values.astype(np.float64)
    open_ = df["open"].values.astype(np.float64)
    high = df["high"].values.astype(np.float64)
    low = df["low"].values.astype(np.float64)
    volume = df["volume"].values.astype(np.float64)

    # Temel fiyat features
    f0 = (open_ - close) / (close + 1e-9)
    f1 = (high - close) / (close + 1e-9)
    f2 = (low - close) / (close + 1e-9)
    f3 = np.zeros_like(close)
    f3[1:] = (close[1:] - close[:-1]) / (close[:-1] + 1e-9)

    # Volume ratio
    vol_ma = pd.Series(volume).rolling(20, min_periods=1).mean().values
    f4 = np.clip(volume / (vol_ma + 1e-9) / 10.0, 0, 1)

    # RSI (14 period)
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(14, min_periods=1).mean().values
    avg_loss = pd.Series(loss).rolling(14, min_periods=1).mean().values
    rs = avg_gain / (avg_loss + 1e-9)
    f5 = (100 - 100 / (1 + rs)) / 100.0

    # EMA diff (12 vs 26)
    ema12 = pd.Series(close).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(close).ewm(span=26, adjust=False).mean().values
    ema_diff = (ema12 - ema26) / (close + 1e-9)
    f6 = np.clip(ema_diff, -0.1, 0.1) * 10.0

    # Bollinger %B
    sma20 = pd.Series(close).rolling(20, min_periods=1).mean().values
    std20 = pd.Series(close).rolling(20, min_periods=1).std().values
    upper = sma20 + 2 * std20
    lower = sma20 - 2 * std20
    f7 = (close - lower) / (upper - lower + 1e-9)
    f7 = np.clip(f7, 0, 1)

    features = np.column_stack([f0, f1, f2, f3, f4, f5, f6, f7])
    return features


def _generate_labels(close: np.ndarray, threshold: float = LABEL_THRESHOLD) -> np.ndarray:
    """
    Forward-looking label: sonraki N bar'da %threshold hareket varsa BUY/SELL.

    Labels: 0=BUY, 1=SELL, 2=HOLD
    """
    n = len(close)
    labels = np.full(n, 2, dtype=np.int64)  # Default: HOLD
    horizon = 5  # 5 bar ileriye bak

    for i in range(n - horizon):
        future_max = np.max(close[i + 1: i + horizon + 1])
        future_min = np.min(close[i + 1: i + horizon + 1])
        up_pct = (future_max - close[i]) / (close[i] + 1e-9)
        down_pct = (close[i] - future_min) / (close[i] + 1e-9)

        if up_pct > threshold and up_pct > down_pct:
            labels[i] = 0  # BUY
        elif down_pct > threshold and down_pct > up_pct:
            labels[i] = 1  # SELL

    return labels


# ── Trainer ─────────────────────────────────────────────────────────────

class LSTMTrainer:
    """LSTM model eğitim ve değerlendirme sınıfı."""

    def __init__(self):
        if not _TORCH_AVAILABLE:
            raise ImportError("PyTorch gerekli — pip install torch")
        if not _PANDAS_AVAILABLE:
            raise ImportError("pandas gerekli — pip install pandas")

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model: Optional[TradingLSTM] = None
        self.X_train: Optional[torch.Tensor] = None
        self.y_train: Optional[torch.Tensor] = None
        self.X_test: Optional[torch.Tensor] = None
        self.y_test: Optional[torch.Tensor] = None
        self.history: List[Dict[str, float]] = []
        self._data_loaded = False

        log.info("LSTMTrainer hazır (device=%s)", self.device)

    def load_data_from_csv(self, csv_path: str) -> int:
        """
        CSV'den veri yükle.
        Beklenen kolonlar: ts/timestamp, open, high, low, close, volume
        Dönüş: toplam sample sayısı.
        """
        df = pd.read_csv(csv_path)
        return self._prepare_data(df)

    def load_data_from_db(
        self,
        symbol: str = "BTCUSDT",
        timeframe: str = "1h",
        days: int = 180,
    ) -> int:
        """
        TimescaleDB'den veri yükle.
        Dönüş: toplam sample sayısı.
        """
        try:
            from super_otonom.infra.timescale_bridge import TimescaleBridge

            db = TimescaleBridge()
            if not db._available:
                log.warning("TimescaleDB erişilemez")
                return 0

            from datetime import datetime, timedelta, timezone

            since = datetime.now(timezone.utc) - timedelta(days=days)
            rows = db.query_klines(symbol, timeframe, limit=days * 24, since=since)

            if not rows:
                log.warning("TimescaleDB'de veri bulunamadı: %s %s", symbol, timeframe)
                return 0

            df = pd.DataFrame(rows)
            df = df.sort_values("ts").reset_index(drop=True)
            return self._prepare_data(df)
        except Exception as exc:
            log.error("DB veri yükleme hatası: %s", exc)
            return 0

    def _prepare_data(self, df: "pd.DataFrame") -> int:
        """DataFrame → train/test tensörleri."""
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(set(df.columns)):
            raise ValueError(f"Eksik kolonlar: {required - set(df.columns)}")

        # Feature extraction
        features = _compute_features(df)
        close = df["close"].values.astype(np.float64)
        labels = _generate_labels(close)

        # Sequence oluştur
        X, y = [], []
        for i in range(SEQ_LEN, len(features)):
            X.append(features[i - SEQ_LEN: i])
            y.append(labels[i])

        X = np.array(X, dtype=np.float32)
        y = np.array(y, dtype=np.int64)

        # NaN temizliği
        mask = ~np.isnan(X).any(axis=(1, 2))
        X, y = X[mask], y[mask]

        # Train/test split
        split_idx = int(len(X) * TRAIN_SPLIT)
        self.X_train = torch.from_numpy(X[:split_idx]).to(self.device)
        self.y_train = torch.from_numpy(y[:split_idx]).to(self.device)
        self.X_test = torch.from_numpy(X[split_idx:]).to(self.device)
        self.y_test = torch.from_numpy(y[split_idx:]).to(self.device)
        self._data_loaded = True

        # Label dağılımı
        unique, counts = np.unique(y, return_counts=True)
        label_names = {0: "BUY", 1: "SELL", 2: "HOLD"}
        dist = {label_names.get(u, str(u)): int(c) for u, c in zip(unique, counts)}
        log.info(
            "Veri hazır: train=%d, test=%d, dağılım=%s",
            len(self.X_train), len(self.X_test), dist,
        )
        return len(X)

    def train(self, epochs: int = DEFAULT_EPOCHS) -> List[Dict[str, float]]:
        """
        Model eğitimi.
        Dönüş: epoch bazlı loss/accuracy geçmişi.
        """
        if not self._data_loaded:
            raise RuntimeError("Önce load_data_* ile veri yükleyin")

        self.model = TradingLSTM().to(self.device)

        # Class weight hesapla (dengesiz veri için)
        labels_np = self.y_train.cpu().numpy()
        unique, counts = np.unique(labels_np, return_counts=True)
        total = len(labels_np)
        weights = torch.zeros(N_CLASSES, device=self.device)
        for u, c in zip(unique, counts):
            weights[u] = total / (N_CLASSES * c)

        criterion = nn.CrossEntropyLoss(weight=weights)
        optimizer = torch.optim.AdamW(
            self.model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4
        )
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", patience=5, factor=0.5
        )

        dataset = TensorDataset(self.X_train, self.y_train)
        loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

        self.history = []
        best_loss = float("inf")
        patience_counter = 0
        max_patience = 10

        log.info("Eğitim başlıyor: %d epoch, %d sample", epochs, len(self.X_train))
        t0 = time.time()

        for epoch in range(1, epochs + 1):
            self.model.train()
            total_loss = 0.0
            correct = 0
            total = 0

            for X_batch, y_batch in loader:
                optimizer.zero_grad()
                output = self.model(X_batch)
                loss = criterion(output, y_batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()

                total_loss += loss.item() * len(y_batch)
                preds = output.argmax(dim=1)
                correct += (preds == y_batch).sum().item()
                total += len(y_batch)

            avg_loss = total_loss / total
            accuracy = correct / total
            scheduler.step(avg_loss)

            # Validation
            val_loss, val_acc = self._evaluate_internal()

            record = {
                "epoch": epoch,
                "train_loss": avg_loss,
                "train_acc": accuracy,
                "val_loss": val_loss,
                "val_acc": val_acc,
            }
            self.history.append(record)

            if epoch % 10 == 0 or epoch == 1:
                log.info(
                    "Epoch %3d/%d — loss: %.4f, acc: %.2f%% | val_loss: %.4f, val_acc: %.2f%%",
                    epoch, epochs, avg_loss, accuracy * 100, val_loss, val_acc * 100,
                )

            # Early stopping
            if val_loss < best_loss:
                best_loss = val_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= max_patience:
                    log.info("Early stopping: %d epoch'ta iyileşme yok", max_patience)
                    break

        elapsed = time.time() - t0
        log.info("Eğitim tamamlandı: %.1f sn, best val_loss: %.4f", elapsed, best_loss)
        return self.history

    def _evaluate_internal(self) -> Tuple[float, float]:
        """İç değerlendirme (validation set)."""
        if self.model is None or self.X_test is None:
            return 0.0, 0.0

        self.model.eval()
        with torch.no_grad():
            output = self.model(self.X_test)
            loss = nn.CrossEntropyLoss()(output, self.y_test).item()
            preds = output.argmax(dim=1)
            acc = (preds == self.y_test).float().mean().item()
        return loss, acc

    def evaluate(self) -> Dict[str, Any]:
        """
        Detaylı model değerlendirmesi.
        Dönüş: accuracy, precision, recall, confusion matrix.
        """
        if self.model is None or self.X_test is None:
            return {"error": "Model veya test verisi yok"}

        self.model.eval()
        with torch.no_grad():
            output = self.model(self.X_test)
            preds = output.argmax(dim=1).cpu().numpy()
            actual = self.y_test.cpu().numpy()

        label_names = ["BUY", "SELL", "HOLD"]
        overall_acc = (preds == actual).mean()

        # Per-class accuracy
        per_class = {}
        for i, name in enumerate(label_names):
            mask = actual == i
            if mask.sum() > 0:
                per_class[name] = {
                    "count": int(mask.sum()),
                    "accuracy": float((preds[mask] == i).mean()),
                }

        result = {
            "accuracy": float(overall_acc),
            "test_size": len(actual),
            "per_class": per_class,
        }
        log.info("Değerlendirme: accuracy=%.2f%%, test_size=%d", overall_acc * 100, len(actual))
        return result

    def save(self, path: str = "data/lstm_model.pt") -> bool:
        """Modeli kaydet (AILayer uyumlu format)."""
        if self.model is None:
            log.error("Kaydedilecek model yok")
            return False
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            torch.save(self.model.state_dict(), path)
            log.info("Model kaydedildi: %s", path)
            return True
        except Exception as exc:
            log.error("Model kaydetme hatası: %s", exc)
            return False

    def load(self, path: str = "data/lstm_model.pt") -> bool:
        """Mevcut modeli yükle (fine-tuning için)."""
        if not os.path.isfile(path):
            log.error("Model dosyası bulunamadı: %s", path)
            return False
        try:
            self.model = TradingLSTM().to(self.device)
            self.model.load_state_dict(torch.load(path, map_location=self.device))
            log.info("Model yüklendi: %s", path)
            return True
        except Exception as exc:
            log.error("Model yükleme hatası: %s", exc)
            return False


# ── CLI ─────────────────────────────────────────────────────────────────

def main():
    """Komut satırı arayüzü."""
    import argparse

    parser = argparse.ArgumentParser(description="LSTM Trainer for Super Otonom")
    parser.add_argument("--symbol", default="BTCUSDT", help="Trading pair")
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--csv", default="", help="CSV veri dosyası (opsiyonel)")
    parser.add_argument("--days", type=int, default=180, help="DB'den kaç gün veri")
    parser.add_argument("--output", default="data/lstm_model.pt", help="Model çıktı yolu")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    trainer = LSTMTrainer()

    # Veri yükle
    if args.csv:
        count = trainer.load_data_from_csv(args.csv)
    else:
        count = trainer.load_data_from_db(args.symbol, args.timeframe, args.days)

    if count == 0:
        log.error("Veri yüklenemedi. CSV ile deneyin: --csv data/klines_btcusdt_1h.csv")
        return

    # Eğit
    trainer.train(epochs=args.epochs)

    # Değerlendir
    result = trainer.evaluate()
    log.info("Sonuç: %s", result)

    # Kaydet
    trainer.save(args.output)
    log.info("Tamamlandı! Model: %s", args.output)


if __name__ == "__main__":
    main()
