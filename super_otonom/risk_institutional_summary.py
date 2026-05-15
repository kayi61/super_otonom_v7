"""
INSTITUTIONAL §1 — çözümlenmiş RISK özet satır sırası (tek kaynak).

``scripts/print_resolved_risk.py --summary`` bu listeyi kullanır.
"""

from __future__ import annotations

from typing import Literal, Tuple

Kind = Literal["pct", "bool", "int", "float", "str"]

# (RISK anahtarı, ortam değişkeni | alternatif, biçim)
SECT1_SUMMARY_SPEC: Tuple[Tuple[str, str, Kind], ...] = (
    ("max_daily_loss_pct", "MAX_DAILY_LOSS_PCT", "pct"),
    ("max_weekly_loss_pct", "MAX_WEEKLY_LOSS_PCT", "pct"),
    ("max_total_drawdown", "MAX_TOTAL_DRAWDOWN", "pct"),
    ("max_exposure_pct", "MAX_EXPOSURE_PCT", "pct"),
    ("max_position_pct", "MAX_POSITION_PCT", "pct"),
    ("max_open_positions", "MAX_OPEN_POSITIONS|MAX_POSITION_COUNT", "int"),
    ("max_notional_per_order", "MAX_NOTIONAL_PER_ORDER", "float"),
    ("stop_loss_pct", "STOP_LOSS_PCT", "pct"),
    ("take_profit_pct", "TAKE_PROFIT_PCT", "pct"),
    ("max_leverage", "MAX_LEVERAGE", "float"),
    ("signal_quality_min", "SIGNAL_QUALITY_MIN", "int"),
    ("exposure_breach_emergency", "EXPOSURE_BREACH_EMERGENCY", "bool"),
    ("min_notional", "MIN_NOTIONAL", "float"),
)
