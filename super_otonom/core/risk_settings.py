"""
Runtime risk limits — frozen ``RiskSettings`` + deprecated ``RISK`` dict view.

PROMPT-09: ``RISK["key"]`` mutasyonu test geriye uyumluluğu için override sözlüğüne gider;
yeni kod ``get_risk_settings().max_position_pct`` veya ``risk.max_position_pct`` kullanmalı.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator, MutableMapping
from dataclasses import asdict, dataclass
from typing import Any

from super_otonom.core.config_env import env_truthy
from super_otonom.core.config_meta import ensure_meta_advisory_env_logged


@dataclass(frozen=True, slots=True)
class RiskSettings:
    max_position_pct: float
    max_open_positions: int
    min_notional: float
    max_notional_per_order: float
    take_profit_pct: float
    stop_loss_pct: float
    trailing_stop_pct: float
    trailing_stop_pct_strong: float
    trailing_stop_pct_weak: float
    max_daily_loss_pct: float
    max_weekly_loss_pct: float
    max_total_drawdown: float
    max_exposure_pct: float
    exposure_breach_emergency: bool
    max_var_99_pct: float
    max_cvar_975_pct: float
    max_model_dispersion_pct: float
    var_confidence: float
    entry_min_confidence: float
    signal_quality_min: int
    max_leverage: float
    min_entry_cooldown_sec: float
    capital_reserve_pct: float
    swap_rate_daily: float


_RISK_BASE: RiskSettings | None = None
_RISK_OVERRIDES: dict[str, Any] = {}


def _load_risk_settings_from_env() -> RiskSettings:
    return RiskSettings(
        max_position_pct=float(os.getenv("MAX_POSITION_PCT", "0.12")),
        max_open_positions=int(
            os.getenv("MAX_OPEN_POSITIONS", os.getenv("MAX_POSITION_COUNT", "1"))
        ),
        min_notional=float(os.getenv("MIN_NOTIONAL", "10.0")),
        max_notional_per_order=max(
            10.0,
            min(float(os.getenv("MAX_NOTIONAL_PER_ORDER", "50000")), 50_000_000.0),
        ),
        take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", "0.30")),
        stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "0.04")),
        trailing_stop_pct=float(os.getenv("TRAILING_STOP_PCT", "0.035")),
        trailing_stop_pct_strong=float(os.getenv("TRAILING_STOP_PCT_STRONG", "0.055")),
        trailing_stop_pct_weak=float(os.getenv("TRAILING_STOP_PCT_WEAK", "0.025")),
        max_daily_loss_pct=float(os.getenv("MAX_DAILY_LOSS_PCT", "0.05")),
        max_weekly_loss_pct=float(os.getenv("MAX_WEEKLY_LOSS_PCT", "0.10")),
        max_total_drawdown=float(os.getenv("MAX_TOTAL_DRAWDOWN", "0.20")),
        max_exposure_pct=float(os.getenv("MAX_EXPOSURE_PCT", "0.12")),
        exposure_breach_emergency=env_truthy("EXPOSURE_BREACH_EMERGENCY", "false"),
        max_var_99_pct=float(os.getenv("MAX_VAR_99_PCT", "0.06")),
        max_cvar_975_pct=float(os.getenv("MAX_CVAR_975_PCT", "0.10")),
        max_model_dispersion_pct=float(os.getenv("MAX_MODEL_DISPERSION_PCT", "0.50")),
        var_confidence=float(os.getenv("VAR_CONFIDENCE", "0.95")),
        entry_min_confidence=float(os.getenv("ENTRY_MIN_CONFIDENCE", "0.62")),
        signal_quality_min=int(os.getenv("SIGNAL_QUALITY_MIN", "62")),
        max_leverage=max(0.01, min(float(os.getenv("MAX_LEVERAGE", "1.0")), 50.0)),
        min_entry_cooldown_sec=max(
            0.0,
            min(float(os.getenv("MIN_ENTRY_COOLDOWN_SEC", "0.0")), 86_400.0),
        ),
        capital_reserve_pct=float(os.getenv("CAPITAL_RESERVE_PCT", "0.05")),
        swap_rate_daily=float(os.getenv("SWAP_RATE_DAILY", "0.0003")),
    )


def _ensure_risk_base_loaded() -> RiskSettings:
    global _RISK_BASE
    if _RISK_BASE is None:
        _RISK_BASE = _load_risk_settings_from_env()
    return _RISK_BASE


def get_risk_settings() -> RiskSettings:
    """Immutable runtime risk limits (env + test overrides merged)."""
    ensure_meta_advisory_env_logged()
    base = _ensure_risk_base_loaded()
    if not _RISK_OVERRIDES:
        return base
    fields = {k: v for k, v in asdict(base).items() if k in RiskSettings.__dataclass_fields__}
    for k, v in _RISK_OVERRIDES.items():
        if k in RiskSettings.__dataclass_fields__:
            fields[k] = v
    return RiskSettings(**fields)


def reset_risk_settings_for_tests() -> None:
    """Test isolation: base + override sıfırla."""
    global _RISK_BASE, _RISK_OVERRIDES
    _RISK_BASE = None
    _RISK_OVERRIDES.clear()


class _RiskAccessor:
    """``config.risk.max_position_pct`` — attribute erişimi."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(get_risk_settings(), name)


class RiskDictProxy(MutableMapping[str, Any]):
    """Deprecated dict view — ``RISK['key']``; yazma override sözlüğüne gider."""

    _DEPRECATION = (
        "RISK dict mutation is deprecated; use get_risk_settings() or "
        "risk.<field> (PROMPT-09). Overrides apply until process exit."
    )

    def _snapshot(self) -> dict[str, Any]:
        return asdict(get_risk_settings())

    def __getitem__(self, key: str) -> Any:
        return self._snapshot()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        warnings.warn(self._DEPRECATION, DeprecationWarning, stacklevel=2)
        if key not in RiskSettings.__dataclass_fields__:
            raise KeyError(key)
        _RISK_OVERRIDES[key] = value

    def __delitem__(self, key: str) -> None:
        _RISK_OVERRIDES.pop(key, None)

    def __iter__(self) -> Iterator[str]:
        return iter(self._snapshot())

    def __len__(self) -> int:
        return len(self._snapshot())

    def get(self, key: str, default: Any = None) -> Any:
        snap = self._snapshot()
        return snap.get(key, default)


RISK: RiskDictProxy = RiskDictProxy()
risk = _RiskAccessor()
