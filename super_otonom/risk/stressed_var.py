"""Stressed VaR — Basel 2.5 stress-period rescaling (VR-11).

For each candidate stress period the engine computes
``historical_var(stress_returns, 0.99)`` and rescales by
``σ_current / σ_stress`` so the result reflects the *current* volatility
regime projected onto the worst historical episode.

Limit rule:  ``stressed_var > 2 × var_99  →  emergency_stop('stressed_var_breach')``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from super_otonom.risk.var_models import historical_var

# ── Canonical crypto stress periods ─────────────────────────────────────────
STRESS_PERIODS: List[Tuple[str, str]] = [
    ("2020_covid", "COVID-19 March 2020"),
    ("2021_china_ban", "China Mining Ban May-Jun 2021"),
    ("2022_luna", "LUNA/UST Collapse May 2022"),
    ("2022_ftx", "FTX Collapse Nov 2022"),
    ("2024_yen_carry", "Yen Carry Trade Unwind Aug 2024"),
]

SVAR_MIN_OBS = 20
"""Minimum observations per stress period to include in computation."""

_FIXTURES = Path(__file__).resolve().parent / ".." / ".." / "tests" / "risk" / "fixtures"

# Sentinel for var_topology detection
stressed_var_engine = True


@dataclass(frozen=True)
class StressedVarResult:
    """Stressed VaR computation output."""

    stressed_var: float = 0.0
    worst_period: str = ""
    per_period_var: Dict[str, float] = field(default_factory=dict)
    rescale_factor: float = 1.0
    breach: bool = False
    breach_multiplier: float = 2.0


class StressedVaR:
    """Basel 2.5 Stressed VaR engine.

    For each stress period *p*:

        sVaR_p = historical_var(stress_p, conf) × (σ_current / σ_stress_p)

    Final:  ``stressed_var = max(sVaR_p)``
    """

    def __init__(
        self,
        stress_returns: Dict[str, Sequence[float]],
    ) -> None:
        self._stress_returns: Dict[str, List[float]] = {
            k: [float(x) for x in v] for k, v in stress_returns.items()
        }

    @classmethod
    def from_fixture(cls, path: Optional[Path] = None) -> "StressedVaR":
        """Load stress-period returns from the JSON fixture."""
        if path is None:
            path = _FIXTURES / "historical_stress_returns.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls({k: v["returns"] for k, v in data.items()})

    # ── Primary interface ───────────────────────────────────────────────────

    def compute(
        self,
        current_returns: Sequence[float],
        conf: float = 0.99,
        *,
        breach_multiplier: float = 2.0,
        var_99_for_limit: Optional[float] = None,
    ) -> StressedVarResult:
        """Compute rescaled stressed VaR across all loaded stress periods.

        Parameters
        ----------
        current_returns:
            Recent portfolio returns (typically last 60 days).
        conf:
            Confidence level (default 0.99 per Basel 2.5).
        breach_multiplier:
            Trigger ratio vs ``var_99_for_limit``.
        var_99_for_limit:
            Current VaR(99%) for breach check.  If *None* breach is always False.
        """
        cur = np.asarray(current_returns, dtype=float).ravel()
        if len(cur) < 2:
            return StressedVarResult()

        sigma_current = float(np.std(cur, ddof=1))

        per_period: Dict[str, float] = {}
        worst_key = ""
        worst_val = 0.0
        worst_rescale = 1.0

        for key, rets in self._stress_returns.items():
            if len(rets) < SVAR_MIN_OBS:
                continue

            raw_var = historical_var(rets, conf, horizon_days=1)
            sigma_stress = float(np.std(rets, ddof=1))

            if sigma_stress < 1e-12:
                per_period[key] = raw_var
                if raw_var > worst_val:
                    worst_val = raw_var
                    worst_key = key
                    worst_rescale = 1.0
                continue

            rescale = sigma_current / sigma_stress
            scaled = raw_var * rescale
            per_period[key] = scaled

            if scaled > worst_val:
                worst_val = scaled
                worst_key = key
                worst_rescale = rescale

        # ── Breach check ────────────────────────────────────────────────────
        ref = var_99_for_limit if var_99_for_limit is not None else 0.0
        breach = (worst_val > breach_multiplier * ref) if ref > 0 else False

        return StressedVarResult(
            stressed_var=worst_val,
            worst_period=worst_key,
            per_period_var=per_period,
            rescale_factor=worst_rescale,
            breach=breach,
            breach_multiplier=breach_multiplier,
        )

    # ── Convenience ─────────────────────────────────────────────────────────

    @staticmethod
    def check_limit(
        stressed_var: float,
        var_99: float,
        multiplier: float = 2.0,
    ) -> bool:
        """Return *True* when stressed VaR exceeds the limit multiple."""
        if var_99 <= 0:
            return False
        return stressed_var > multiplier * var_99

    @property
    def period_keys(self) -> List[str]:
        return sorted(self._stress_returns.keys())


def compute_stressed_var(
    current_returns: Sequence[float],
    stress_returns: Dict[str, Sequence[float]],
    conf: float = 0.99,
) -> Tuple[float, str, Dict[str, float]]:
    """Convenience: ``(stressed_var, worst_period, per_period_var)``."""
    engine = StressedVaR(stress_returns)
    r = engine.compute(current_returns, conf)
    return r.stressed_var, r.worst_period, r.per_period_var
