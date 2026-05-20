"""P&L Attribution + Unexplained PnL Drift Detection (VR-16).

Decomposes daily portfolio PnL into three buckets:

    **explained** — mark-to-market change on opening positions
    **trades**    — realized PnL from intraday trades
    **unexplained** — residual (fees, funding, execution slippage, data lag)

An unexplained PnL exceeding 10 bps of total capital triggers a drift
alert — indicates model risk, data pipeline issues, or unmodelled costs.

Prometheus:
    ``bot_pnl_explained_pct``
    ``bot_pnl_unexplained_pct``
    ``bot_pnl_attribution_health``  (1 = healthy, 0 = drift)

Alerts:
    ``BotPnLDriftHigh`` — |unexplained_pct| > 10 bps for 15m.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Sequence, runtime_checkable

log = logging.getLogger("super_otonom.risk.pnl_attribution")

# Sentinel for var_topology detection
pnl_attribution_active = True

PNL_DRIFT_THRESHOLD_BPS = 10
"""Unexplained PnL threshold in basis points (10 bps = 0.001)."""

PNL_DRIFT_THRESHOLD = PNL_DRIFT_THRESHOLD_BPS / 10_000
"""Fractional threshold: 0.001."""

_REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "pnl_reports"


# ── Trade protocol ──────────────────────────────────────────────────────────

@runtime_checkable
class TradeLike(Protocol):
    """Minimal interface for a trade object used in attribution."""

    @property
    def pnl(self) -> float: ...


@dataclass(frozen=True)
class SimpleTrade:
    """Lightweight trade representation for attribution.

    Can be used when the calling code doesn't have a full trade object.
    """

    pnl: float = 0.0
    symbol: str = ""


# ── Result dataclass ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PnLAttribution:
    """P&L attribution decomposition result.

    Attributes
    ----------
    explained : float
        Mark-to-market PnL from holding opening positions.
    trades : float
        Realized PnL from intraday trade executions.
    unexplained : float
        Residual: actual_pnl - explained - trades.
        Sources: fees, funding, execution slippage, data lag.
    actual_pnl : float
        Total portfolio PnL observed (end NAV - start NAV).
    unexplained_pct : float
        unexplained / total_capital (fractional, e.g. 0.001 = 10 bps).
    unexplained_bps : float
        Unexplained in basis points (abs value).
    drift_detected : bool
        True when |unexplained_pct| > PNL_DRIFT_THRESHOLD.
    total_capital : float
        Capital base used for percentage calculation.
    n_positions : int
        Number of positions in the attribution.
    n_trades : int
        Number of trades in the attribution.
    """

    explained: float = 0.0
    trades: float = 0.0
    unexplained: float = 0.0
    actual_pnl: float = 0.0
    unexplained_pct: float = 0.0
    unexplained_bps: float = 0.0
    drift_detected: bool = False
    total_capital: float = 0.0
    n_positions: int = 0
    n_trades: int = 0


@dataclass(frozen=True)
class PnLAttributionSeries:
    """Time-series of daily attribution results.

    Attributes
    ----------
    daily : list[PnLAttribution]
        Per-day attribution results.
    total_explained : float
    total_trades : float
    total_unexplained : float
    max_abs_unexplained_bps : float
        Worst-day |unexplained| in bps.
    drift_days : int
        Number of days with drift detected.
    """

    daily: List[PnLAttribution] = field(default_factory=list)
    total_explained: float = 0.0
    total_trades: float = 0.0
    total_unexplained: float = 0.0
    max_abs_unexplained_bps: float = 0.0
    drift_days: int = 0


# ── Core attribution ────────────────────────────────────────────────────────

def attribute_pnl(
    positions_start: Dict[str, float],
    positions_end: Dict[str, float],
    prices_start: Dict[str, float],
    prices_end: Dict[str, float],
    trades: Sequence[TradeLike],
    total_capital: float,
) -> PnLAttribution:
    """Decompose daily PnL into explained, trades, and unexplained.

    Parameters
    ----------
    positions_start:
        Opening positions: ``{symbol: quantity}``.
    positions_end:
        Closing positions: ``{symbol: quantity}``.
    prices_start:
        Opening prices: ``{symbol: price}``.
    prices_end:
        Closing prices: ``{symbol: price}``.
    trades:
        Intraday trades (each must have a ``.pnl`` attribute).
    total_capital:
        Total portfolio capital for percentage calculation.

    Returns
    -------
    PnLAttribution
    """
    if total_capital <= 0:
        raise ValueError(
            f"total_capital must be positive, got {total_capital}"
        )

    # 1. Explained: mark-to-market on opening positions
    explained = 0.0
    for symbol, qty in positions_start.items():
        p_start = prices_start.get(symbol, 0.0)
        p_end = prices_end.get(symbol, 0.0)
        explained += (p_end - p_start) * qty

    # 2. Realized: sum of trade PnLs
    realized = sum(t.pnl for t in trades)

    # 3. Actual PnL: end NAV - start NAV
    nav_end = sum(
        positions_end.get(s, 0.0) * prices_end.get(s, 0.0)
        for s in set(positions_end) | set(prices_end)
        if s in positions_end
    )
    nav_start = sum(
        positions_start.get(s, 0.0) * prices_start.get(s, 0.0)
        for s in set(positions_start) | set(prices_start)
        if s in positions_start
    )
    actual_pnl = nav_end - nav_start

    # 4. Unexplained residual
    unexplained = actual_pnl - explained - realized

    unexplained_pct = unexplained / total_capital
    unexplained_bps = abs(unexplained_pct) * 10_000
    drift_detected = abs(unexplained_pct) > PNL_DRIFT_THRESHOLD

    if drift_detected:
        log.warning(
            "PnL drift detected: unexplained=%.4f (%.1f bps), "
            "threshold=%d bps",
            unexplained,
            unexplained_bps,
            PNL_DRIFT_THRESHOLD_BPS,
        )

    return PnLAttribution(
        explained=explained,
        trades=realized,
        unexplained=unexplained,
        actual_pnl=actual_pnl,
        unexplained_pct=unexplained_pct,
        unexplained_bps=unexplained_bps,
        drift_detected=drift_detected,
        total_capital=total_capital,
        n_positions=len(positions_start),
        n_trades=len(trades),
    )


# ── Multi-day attribution ──────────────────────────────────────────────────

def attribute_pnl_series(
    daily_snapshots: Sequence[dict],
    total_capital: float,
) -> PnLAttributionSeries:
    """Run attribution across a time-series of daily snapshots.

    Parameters
    ----------
    daily_snapshots:
        List of dicts, each containing:
        ``positions_start``, ``positions_end``, ``prices_start``,
        ``prices_end``, ``trades`` (list of TradeLike or dicts with 'pnl').
    total_capital:
        Capital base (assumed constant across days for simplicity).

    Returns
    -------
    PnLAttributionSeries
    """
    results: List[PnLAttribution] = []

    for snap in daily_snapshots:
        trades_raw = snap.get("trades", [])
        trades_obj: List[TradeLike] = []
        for t in trades_raw:
            if isinstance(t, dict):
                trades_obj.append(SimpleTrade(pnl=t.get("pnl", 0.0)))
            else:
                trades_obj.append(t)

        r = attribute_pnl(
            positions_start=snap.get("positions_start", {}),
            positions_end=snap.get("positions_end", {}),
            prices_start=snap.get("prices_start", {}),
            prices_end=snap.get("prices_end", {}),
            trades=trades_obj,
            total_capital=total_capital,
        )
        results.append(r)

    total_explained = sum(r.explained for r in results)
    total_trades = sum(r.trades for r in results)
    total_unexplained = sum(r.unexplained for r in results)
    max_abs_bps = max((r.unexplained_bps for r in results), default=0.0)
    drift_days = sum(1 for r in results if r.drift_detected)

    return PnLAttributionSeries(
        daily=results,
        total_explained=total_explained,
        total_trades=total_trades,
        total_unexplained=total_unexplained,
        max_abs_unexplained_bps=max_abs_bps,
        drift_days=drift_days,
    )


# ── Report generation ───────────────────────────────────────────────────────

def generate_attribution_report(
    result: PnLAttribution | PnLAttributionSeries,
    report_dir: Optional[Path] = None,
) -> Path:
    """Write a markdown P&L attribution report to disk.

    Output: ``docs/pnl_reports/pnl_attribution_YYYY-MM-DD.md``
    """
    out_dir = report_dir or _REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    out_path = out_dir / f"pnl_attribution_{today}.md"

    lines: List[str] = [
        f"# P&L Attribution Report — {today}",
        "",
    ]

    if isinstance(result, PnLAttributionSeries):
        lines.extend([
            "## Summary",
            "",
            f"- **Days analysed:** {len(result.daily)}",
            f"- **Total explained:** {result.total_explained:.4f}",
            f"- **Total trades PnL:** {result.total_trades:.4f}",
            f"- **Total unexplained:** {result.total_unexplained:.4f}",
            f"- **Max |unexplained| day:** {result.max_abs_unexplained_bps:.1f} bps",
            f"- **Drift days:** {result.drift_days}",
            "",
            "## Daily Detail",
            "",
            "| Day | Explained | Trades | Unexplained | Bps | Drift |",
            "|-----|-----------|--------|-------------|-----|-------|",
        ])
        for i, d in enumerate(result.daily, 1):
            drift_str = "DRIFT" if d.drift_detected else "OK"
            lines.append(
                f"| {i} | {d.explained:.4f} | {d.trades:.4f} "
                f"| {d.unexplained:.4f} | {d.unexplained_bps:.1f} | {drift_str} |"
            )
    else:
        r = result
        drift_str = "DRIFT DETECTED" if r.drift_detected else "HEALTHY"
        lines.extend([
            "## Attribution",
            "",
            "| Component | Value |",
            "|-----------|-------|",
            f"| Explained (mark-to-market) | {r.explained:.6f} |",
            f"| Trades (realized) | {r.trades:.6f} |",
            f"| Unexplained (residual) | {r.unexplained:.6f} |",
            f"| Actual PnL | {r.actual_pnl:.6f} |",
            "",
            "## Drift Analysis",
            "",
            f"- **Unexplained %:** {r.unexplained_pct:.6f} ({r.unexplained_bps:.1f} bps)",
            f"- **Threshold:** {PNL_DRIFT_THRESHOLD_BPS} bps",
            f"- **Status:** {drift_str}",
            f"- **Positions:** {r.n_positions}",
            f"- **Trades:** {r.n_trades}",
        ])

    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("PnL attribution report written: %s", out_path)
    return out_path


# ── JSON serialization helper ───────────────────────────────────────────────

def attribution_to_dict(result: PnLAttribution) -> dict:
    """Convert to JSON-serializable dictionary."""
    return {
        "explained": result.explained,
        "trades": result.trades,
        "unexplained": result.unexplained,
        "actual_pnl": result.actual_pnl,
        "unexplained_pct": result.unexplained_pct,
        "unexplained_bps": result.unexplained_bps,
        "drift_detected": result.drift_detected,
        "total_capital": result.total_capital,
        "n_positions": result.n_positions,
        "n_trades": result.n_trades,
    }
