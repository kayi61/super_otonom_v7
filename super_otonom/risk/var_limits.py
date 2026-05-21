"""VR-20: VaR Limit Hierarchy — Strategy / Portfolio / Firm.

Three-level limit system with override chain: env > YAML > dataclass defaults.

Invariants (enforced by ``validate()``):
  - strategy VaR < portfolio VaR
  - strategy CVaR < portfolio CVaR
  - portfolio VaR < stressed VaR
  - marginal VaR per trade < strategy VaR
  - all limits in (0, 1]
  - component VaR concentration in (0, 1]
  - LVaR/NAV in (0, 1]
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

# VR-20 sentinel — var_topology tarafından tespit edilir
var_limit_hierarchy_active = True

_DEFAULT_YAML = Path(__file__).resolve().parents[2] / "config" / "var_limits.yaml"

# Field name → env var mapping (upper-case with prefix)
_ENV_PREFIX = ""  # Direct mapping: field MAX_VAR_PER_STRATEGY_PCT → env MAX_VAR_PER_STRATEGY_PCT


@dataclass(frozen=True)
class VaRLimits:
    """Three-level VaR limit hierarchy.

    Levels:
      1. Strategy — per-strategy 1d 99% VaR/CVaR cap
      2. Portfolio — aggregate VaR/CVaR/Stressed VaR cap
      3. Trade — single-trade marginal VaR cap
      + Concentration — max component VaR per position
      + Liquidity — LVaR / NAV cap
    """

    # ── Strategy level ───────────────────────────────────────────────────────
    max_var_per_strategy_pct: float = 0.02
    max_cvar_per_strategy_pct: float = 0.03

    # ── Portfolio level ──────────────────────────────────────────────────────
    max_var_total_pct: float = 0.06
    max_cvar_total_pct: float = 0.10
    max_stressed_var_total_pct: float = 0.15

    # ── Single-trade marginal ────────────────────────────────────────────────
    max_marginal_var_per_trade_pct: float = 0.005

    # ── Concentration ────────────────────────────────────────────────────────
    max_component_var_per_position_pct: float = 0.40

    # ── Liquidity ────────────────────────────────────────────────────────────
    max_lvar_to_nav: float = 0.08

    def validate(self) -> List[str]:
        """Return list of invariant violations (empty = valid)."""
        issues: List[str] = []

        # All limits must be in (0, 1]
        for f in fields(self):
            val = getattr(self, f.name)
            if not (0.0 < val <= 1.0):
                issues.append(f"{f.name}={val} outside (0, 1]")

        # Hierarchy: strategy < portfolio
        if self.max_var_per_strategy_pct >= self.max_var_total_pct:
            issues.append(
                f"max_var_per_strategy_pct ({self.max_var_per_strategy_pct}) "
                f"must be < max_var_total_pct ({self.max_var_total_pct})"
            )
        if self.max_cvar_per_strategy_pct >= self.max_cvar_total_pct:
            issues.append(
                f"max_cvar_per_strategy_pct ({self.max_cvar_per_strategy_pct}) "
                f"must be < max_cvar_total_pct ({self.max_cvar_total_pct})"
            )

        # Hierarchy: portfolio VaR < stressed VaR
        if self.max_var_total_pct >= self.max_stressed_var_total_pct:
            issues.append(
                f"max_var_total_pct ({self.max_var_total_pct}) "
                f"must be < max_stressed_var_total_pct ({self.max_stressed_var_total_pct})"
            )

        # Hierarchy: marginal < strategy
        if self.max_marginal_var_per_trade_pct >= self.max_var_per_strategy_pct:
            issues.append(
                f"max_marginal_var_per_trade_pct ({self.max_marginal_var_per_trade_pct}) "
                f"must be < max_var_per_strategy_pct ({self.max_var_per_strategy_pct})"
            )

        return issues

    @property
    def is_valid(self) -> bool:
        """True if all invariants hold."""
        return len(self.validate()) == 0

    def to_dict(self) -> Dict[str, float]:
        """JSON-serializable dict."""
        return asdict(self)


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file as dict. Returns empty dict if missing or invalid."""
    if not path.is_file():
        return {}
    try:
        import yaml
    except ImportError:
        # Fallback: simple key: value parser for flat YAML
        result: Dict[str, Any] = {}
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip()
                if val.startswith("#"):
                    continue
                # Remove inline comments
                if "#" in val:
                    val = val[: val.index("#")].strip()
                try:
                    result[key] = float(val)
                except ValueError:
                    pass
        return result
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _env_overrides() -> Dict[str, float]:
    """Read env vars matching VaRLimits field names (upper-case)."""
    overrides: Dict[str, float] = {}
    for f in fields(VaRLimits):
        env_key = f.name.upper()
        val = os.getenv(env_key)
        if val is not None:
            try:
                overrides[f.name] = float(val)
            except ValueError:
                pass
    return overrides


def load_var_limits(
    *,
    yaml_path: Optional[Path] = None,
    skip_env: bool = False,
) -> VaRLimits:
    """Load VaRLimits with override chain: env > YAML > defaults.

    Parameters
    ----------
    yaml_path : Path, optional
        Custom YAML path. Defaults to ``config/var_limits.yaml``.
    skip_env : bool
        If True, skip env var overrides (useful for testing).
    """
    # Start with defaults
    merged: Dict[str, float] = {}

    # Layer 1: YAML overrides
    yp = yaml_path if yaml_path is not None else _DEFAULT_YAML
    yaml_data = _load_yaml(yp)
    valid_fields = {f.name for f in fields(VaRLimits)}
    for k, v in yaml_data.items():
        if k in valid_fields and isinstance(v, (int, float)):
            merged[k] = float(v)

    # Layer 2: env overrides (highest priority)
    if not skip_env:
        env_data = _env_overrides()
        merged.update(env_data)

    return VaRLimits(**merged)


def check_limits(limits: VaRLimits, metrics: Any) -> List[str]:
    """Check RiskMetrics against VaRLimits. Returns list of breaches.

    Parameters
    ----------
    limits : VaRLimits
        Active limit set.
    metrics : RiskMetrics
        Current risk metrics from RiskEngine.compute().

    Returns
    -------
    list[str]
        Breach descriptions (empty = all within limits).
    """
    breaches: List[str] = []

    # Portfolio-level checks
    var_99 = getattr(metrics, "var_99_1d", 0.0)
    if var_99 > limits.max_var_total_pct:
        breaches.append(
            f"portfolio_var_99={var_99:.4f} > limit={limits.max_var_total_pct:.4f}"
        )

    cvar_975 = getattr(metrics, "cvar_975_1d", 0.0)
    if cvar_975 > limits.max_cvar_total_pct:
        breaches.append(
            f"portfolio_cvar_975={cvar_975:.4f} > limit={limits.max_cvar_total_pct:.4f}"
        )

    stressed = getattr(metrics, "stressed_var", 0.0)
    if stressed > limits.max_stressed_var_total_pct:
        breaches.append(
            f"stressed_var={stressed:.4f} > limit={limits.max_stressed_var_total_pct:.4f}"
        )

    # LVaR check
    lvar = getattr(metrics, "lvar", 0.0)
    if lvar > limits.max_lvar_to_nav:
        breaches.append(
            f"lvar={lvar:.4f} > limit={limits.max_lvar_to_nav:.4f}"
        )

    # Component VaR concentration check
    comp_var = getattr(metrics, "component_var_per_position", {})
    var_total = getattr(metrics, "var_for_limits_95", 0.0) or 1.0
    for symbol, cv in comp_var.items():
        ratio = abs(cv) / abs(var_total) if abs(var_total) > 1e-12 else 0.0
        if ratio > limits.max_component_var_per_position_pct:
            breaches.append(
                f"component_var[{symbol}]={ratio:.4f} > limit={limits.max_component_var_per_position_pct:.4f}"
            )

    return breaches
