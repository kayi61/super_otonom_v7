from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

log = logging.getLogger("super_otonom.wfa")

_TRAIN_RATIO = 0.70   # %70 eğitim / %30 test


class WFAFold:
    """Tek bir WFA penceresi: eğitim + test dilimi + metadata."""

    def __init__(
        self,
        fold_id: int,
        train: pd.DataFrame,
        test: pd.DataFrame,
        train_range: Tuple[int, int],
        test_range: Tuple[int, int],
    ):
        self.fold_id    = fold_id
        self.train      = train
        self.test       = test
        self.train_range = train_range   # (start_idx, end_idx)
        self.test_range  = test_range
        self.best_params: Dict[str, Any] = {}
        self.train_score: Optional[float] = None
        self.test_score:  Optional[float] = None

    def __repr__(self) -> str:
        return (
            f"WFAFold(id={self.fold_id} "
            f"train={self.train_range} n={len(self.train)} "
            f"test={self.test_range} n={len(self.test)})"
        )


class WFAManager:
    """
    Walk-Forward Analysis yöneticisi — v4 entegrasyonu.

    Kullanım:
    ─────────
    manager = WFAManager(df, window_size=1000, step_size=200)
    for fold in manager.get_folds():
        params = optimize(fold.train)          # kullanıcı tarafı
        score  = backtest(fold.test, params)   # görülmemiş veri
        manager.record_result(fold, params, train_score, score)

    summary = manager.summary()
    best    = manager.best_params()
    """

    def __init__(
        self,
        data: pd.DataFrame,
        window_size: int,
        step_size: int,
        train_ratio: float = _TRAIN_RATIO,
        min_test_rows: int = 10,
    ):
        if data is None or data.empty:
            raise ValueError("WFAManager: data bos olamaz.")
        if window_size <= 0 or step_size <= 0:
            raise ValueError("window_size ve step_size pozitif olmali.")
        if not (0.0 < train_ratio < 1.0):
            raise ValueError("train_ratio 0-1 arasinda olmali.")

        self.data         = data
        self.window_size  = window_size
        self.step_size    = step_size
        self.train_ratio  = train_ratio
        self.min_test_rows = min_test_rows
        self._results: List[Dict[str, Any]] = []

    # ── Fold üreteci ──────────────────────────────────────────────────────────

    def get_folds(self) -> List[WFAFold]:
        """
        Veriyi kayan pencere ile eğitim/test dilimlerine böler.

        Her pencere:
          [start : train_end]  → eğitim (%70)
          [train_end : window_end] → test  (%30)
        """
        folds  = []
        n      = len(self.data)
        fold_id = 0

        for start in range(0, n - self.window_size, self.step_size):
            train_end  = start + int(self.window_size * self.train_ratio)
            window_end = start + self.window_size

            train_df = self.data.iloc[start:train_end].copy()
            test_df  = self.data.iloc[train_end:window_end].copy()

            if len(test_df) < self.min_test_rows:
                log.debug("WFA fold %d: test seti cok kucuk (%d < %d), atlandi.",
                          fold_id, len(test_df), self.min_test_rows)
                continue

            fold = WFAFold(
                fold_id     = fold_id,
                train       = train_df,
                test        = test_df,
                train_range = (start, train_end),
                test_range  = (train_end, window_end),
            )
            folds.append(fold)
            fold_id += 1

        log.info("WFAManager: %d fold olusturuldu (window=%d step=%d)",
                 len(folds), self.window_size, self.step_size)
        return folds

    # ── Sonuç kaydı ───────────────────────────────────────────────────────────

    def record_result(
        self,
        fold: WFAFold,
        params: Dict[str, Any],
        train_score: float,
        test_score: float,
    ) -> None:
        """Optimizasyon ve doğrulama sonuçlarını fold'a ve iç listeye yazar."""
        fold.best_params  = params
        fold.train_score  = train_score
        fold.test_score   = test_score
        self._results.append({
            "fold_id":     fold.fold_id,
            "train_range": fold.train_range,
            "test_range":  fold.test_range,
            "params":      params,
            "train_score": train_score,
            "test_score":  test_score,
        })
        log.info(
            "WFA fold %d kaydedildi | train_score=%.4f test_score=%.4f params=%s",
            fold.fold_id, train_score, test_score, params,
        )

    # ── Analiz araçları ───────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Tüm foldların özet istatistiklerini döner."""
        if not self._results:
            return {"status": "no_results"}

        test_scores  = [r["test_score"]  for r in self._results if r["test_score"]  is not None]
        train_scores = [r["train_score"] for r in self._results if r["train_score"] is not None]

        def _stats(vals: List[float]) -> Dict[str, float]:
            if not vals:
                return {}
            return {
                "mean":  round(sum(vals) / len(vals), 4),
                "min":   round(min(vals), 4),
                "max":   round(max(vals), 4),
                "count": len(vals),
            }

        # Overfitting oranı: train/test korelasyonu basit proxy
        overfit_ratio: Optional[float] = None
        if len(test_scores) > 1 and len(train_scores) > 1:
            avg_train = sum(train_scores) / len(train_scores)
            avg_test  = sum(test_scores)  / len(test_scores)
            if avg_train != 0:
                overfit_ratio = round((avg_train - avg_test) / abs(avg_train), 4)

        return {
            "folds":         len(self._results),
            "test_scores":   _stats(test_scores),
            "train_scores":  _stats(train_scores),
            "overfit_ratio": overfit_ratio,  # pozitif → eğitim > test (overfit riski)
        }

    def best_params(self, metric: str = "test_score") -> Dict[str, Any]:
        """En yüksek test_score'a sahip fold'un parametrelerini döner."""
        if not self._results:
            return {}
        best = max(self._results, key=lambda r: r.get(metric) or float("-inf"))
        log.info(
            "WFA best_params: fold=%d %s=%.4f params=%s",
            best["fold_id"], metric, best.get(metric, 0), best["params"],
        )
        return best["params"]

    def results_dataframe(self) -> pd.DataFrame:
        """Tüm sonuçları DataFrame olarak döner — analiz/görselleştirme için."""
        if not self._results:
            return pd.DataFrame()
        rows = []
        for r in self._results:
            row = {
                "fold_id":     r["fold_id"],
                "train_start": r["train_range"][0],
                "train_end":   r["train_range"][1],
                "test_start":  r["test_range"][0],
                "test_end":    r["test_range"][1],
                "train_score": r["train_score"],
                "test_score":  r["test_score"],
            }
            row.update({f"param_{k}": v for k, v in (r.get("params") or {}).items()})
            rows.append(row)
        return pd.DataFrame(rows)
