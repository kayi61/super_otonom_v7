"""Risk engine configuration (VR-01 / VR-05)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    var_confidences: tuple[float, ...] = (0.95, 0.975, 0.99)
    var_horizons_days: tuple[int, ...] = (1, 10)
    var_history_min_obs: int = 100
    var_history_min_obs_institutional: int = 250
    cvar_primary_conf: float = 0.975
    cvar_secondary_conf: float = 0.99
    cvar_legacy_conf: float = 0.95
    monte_carlo_draws: int = 600
    monte_carlo_seed: int = 42
    limit_aggregator: str = "max"
    parametric_z_95: float = 1.645
    parametric_z_975: float = 1.96
    parametric_z_99: float = 2.326
