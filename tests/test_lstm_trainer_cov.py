"""lstm_trainer gercek kapsama testleri.

CI'da torch YOK (.[dev] torch icermez) -> torch-bagimsiz kisimlar (_compute_features,
_generate_labels, modul sabitleri) her yerde kosar. Torch-bagimli kisimlar (LSTMTrainer,
_prepare_data, train, save/load) yalnizca torch varken kosar (skipif) — CI'da skip, kirilmaz.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from super_otonom import lstm_trainer as lt

_NEED_TORCH = pytest.mark.skipif(not lt._TORCH_AVAILABLE, reason="torch yok (CI dev profili)")


def _ohlcv(n: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = np.abs(np.cumsum(rng.normal(0, 1.0, n))) + 100.0
    open_ = close + rng.normal(0, 0.4, n)
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.4, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.4, n))
    volume = np.abs(rng.normal(1000, 120, n)) + 1.0
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


# ── Torch-bagimsiz: her yerde kosar (CI dahil) ─────────────────────────────


def test_module_constants():
    assert lt.SEQ_LEN == 30
    assert lt.N_FEATURES == 8
    assert lt.N_CLASSES == 3
    assert 0 < lt.TRAIN_SPLIT < 1
    assert lt.LABEL_THRESHOLD > 0


def test_compute_features_shape_and_bounds():
    df = _ohlcv(120)
    feats = lt._compute_features(df)
    assert feats.shape == (120, lt.N_FEATURES)
    # Ilk satirlarda rolling/std isinma NaN'i var (tasarim: _prepare_data NaN mask uygular).
    # Isinmis bolgede (>=25) NaN olmamali ve sinirlar tutmali.
    warm = feats[25:]
    assert not np.isnan(warm).any()
    assert np.all(warm[:, 5] >= 0) and np.all(warm[:, 5] <= 1.0001)  # RSI
    assert np.all(warm[:, 7] >= -0.0001) and np.all(warm[:, 7] <= 1.0001)  # Bollinger %B
    assert np.all(warm[:, 4] >= 0) and np.all(warm[:, 4] <= 1.0001)  # volume ratio


def test_compute_features_no_nan_in_close_change():
    df = _ohlcv(60)
    feats = lt._compute_features(df)
    assert not np.isnan(feats[1:, 3]).any()  # close pct change


def test_generate_labels_buy_on_rising():
    close = np.linspace(100.0, 130.0, 40)  # surekli yukseliyor
    labels = lt._generate_labels(close, threshold=0.015)
    assert (labels[:30] == 0).any()  # en az bir BUY


def test_generate_labels_sell_on_falling():
    close = np.linspace(130.0, 100.0, 40)  # surekli dusuyor
    labels = lt._generate_labels(close, threshold=0.015)
    assert (labels[:30] == 1).any()  # en az bir SELL


def test_generate_labels_flat_all_hold():
    close = np.full(40, 100.0)
    labels = lt._generate_labels(close)
    assert (labels == 2).all()


def test_generate_labels_tail_is_hold():
    close = np.linspace(100.0, 130.0, 40)
    labels = lt._generate_labels(close)
    assert (labels[-5:] == 2).all()  # son horizon=5 bar daima HOLD


# ── Torch-bagimli: yalnizca torch varken (CI'da skip) ──────────────────────


@_NEED_TORCH
def test_trainer_init_and_prepare(tmp_path):
    trainer = lt.LSTMTrainer()
    csv = tmp_path / "klines.csv"
    _ohlcv(220).to_csv(csv, index=False)
    n = trainer.load_data_from_csv(str(csv))
    assert n > 0
    assert trainer._data_loaded is True
    assert trainer.X_train is not None and trainer.X_test is not None


@_NEED_TORCH
def test_trainer_prepare_missing_columns_raises():
    trainer = lt.LSTMTrainer()
    bad = pd.DataFrame({"close": [1, 2, 3]})  # eksik kolon
    with pytest.raises(ValueError):
        trainer._prepare_data(bad)


@_NEED_TORCH
def test_trainer_train_eval_save_load(tmp_path):
    trainer = lt.LSTMTrainer()
    csv = tmp_path / "k.csv"
    _ohlcv(260).to_csv(csv, index=False)
    trainer.load_data_from_csv(str(csv))
    hist = trainer.train(epochs=1)
    assert isinstance(hist, list) and len(hist) == 1
    metrics = trainer.evaluate()
    assert "accuracy" in metrics or isinstance(metrics, dict)
    model_path = tmp_path / "m.pt"
    assert trainer.save(str(model_path)) is True
    trainer2 = lt.LSTMTrainer()
    assert trainer2.load(str(model_path)) is True


@_NEED_TORCH
def test_load_data_from_db_unavailable(monkeypatch):
    import super_otonom.infra.timescale_bridge as tb

    class _FakeDB:
        _available = False

    monkeypatch.setattr(tb, "TimescaleBridge", lambda *a, **k: _FakeDB())
    trainer = lt.LSTMTrainer()
    assert trainer.load_data_from_db("BTCUSDT", "1h", days=1) == 0
