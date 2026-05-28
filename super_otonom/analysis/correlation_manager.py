from __future__ import annotations

"""
CorrelationManager v6.1
─────────────────────────────────────────────────────────────────────────────
v6   → Korelasyon bazlı risk yönetimi
v6.1 → FIX: summary() dönüş tipi Dict[str, int] → Dict[str, Any] düzeltildi
             threshold bir float — önceki tip bildirimi yanlıştı.
"""

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set

import pandas as pd

log = logging.getLogger("super_otonom.correlation")

_MIN_PERIODS = 30
_PRICE_HISTORY = 200


class CorrelationManager:
    def __init__(self, threshold: float = 0.75, min_periods: int = _MIN_PERIODS):
        self.threshold = threshold
        self.min_periods = min_periods
        self._price_history: Dict[str, deque] = {}

    def update_returns(self, symbol: str, close_price: float) -> None:
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=_PRICE_HISTORY)
        self._price_history[symbol].append(float(close_price))

    def get_returns_df(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        syms = symbols or list(self._price_history.keys())
        data: Dict[str, list] = {}
        for s in syms:
            hist = self._price_history.get(s)
            if hist and len(hist) >= 2:
                prices = list(hist)
                returns = [
                    (prices[i] - prices[i - 1]) / (prices[i - 1] + 1e-9)
                    for i in range(1, len(prices))
                ]
                data[s] = returns
        if not data:
            return pd.DataFrame()
        min_len = min(len(v) for v in data.values())
        for k in data:
            data[k] = data[k][-min_len:]
        return pd.DataFrame(data)

    def get_correlated_pairs(self, returns_df: Optional[pd.DataFrame] = None) -> List[Set[str]]:
        df = returns_df if returns_df is not None else self.get_returns_df()
        if df.empty or len(df) < self.min_periods:
            return []

        corr_matrix = df.corr()
        high_corr: List[Set[str]] = []
        cols = list(corr_matrix.columns)

        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                val = corr_matrix.iloc[i, j]
                if pd.notna(val) and abs(float(val)) > self.threshold:
                    high_corr.append({cols[i], cols[j]})
        return high_corr

    def adjust_risk_exposure(
        self,
        symbol: str,
        open_positions: List[str],
        returns_df: Optional[pd.DataFrame] = None,
    ) -> float:
        if not open_positions:
            return 1.0

        df = returns_df if returns_df is not None else self.get_returns_df()

        if df.empty or symbol not in df.columns or len(df) < self.min_periods:
            return 1.0

        multiplier = 1.0
        for pos_sym in open_positions:
            if pos_sym == symbol or pos_sym not in df.columns:
                continue
            try:
                corr = float(df[symbol].corr(df[pos_sym]))
            except Exception:
                continue

            if pd.isna(corr):
                continue

            if corr > self.threshold:
                multiplier *= 0.5
                log.warning(
                    "KORELASYON_UYARISI: %s vs %s | corr=%.3f > threshold=%.2f | "
                    "risk azaltiliyor multiplier=%.2f",
                    symbol,
                    pos_sym,
                    corr,
                    self.threshold,
                    multiplier,
                )

        return max(multiplier, 0.2)

    def correlation_matrix(self) -> Optional[pd.DataFrame]:
        df = self.get_returns_df()
        if df.empty or len(df) < self.min_periods:
            return None
        return df.corr().round(3)

    # FIX: Dönüş tipi Dict[str, Any] — threshold float olduğu için int değil
    def summary(self) -> Dict[str, Any]:
        return {
            "tracked_symbols": len(self._price_history),
            "min_history_len": min((len(v) for v in self._price_history.values()), default=0),
            "threshold": self.threshold,  # float — önceki Dict[str,int] yanlıştı
        }
