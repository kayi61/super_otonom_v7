"""
Backtest evreni — survivorship bias ve tek-sembol sınırları (audit madde 4).

Tek mum zinciri veya bugün listeli çiftler: delist / point-in-time evren yoksa
kurumsal evren backtest iddiası yapılmaz. Çok sembol: bağımsız paper koşum + açık özet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from super_otonom.backtester import BacktestReport, run_backtest_async
from super_otonom.clock_skew import check_candle_timestamps_monotonic

_log = logging.getLogger("super_otonom.backtest_universe")


@dataclass(frozen=True)
class SymbolScheduleEntry:
    """Point-in-time evren: sembolün hangi mum aralığında 'listede' sayıldığı."""

    symbol: str
    active_from_ms: Optional[float] = None
    active_until_ms: Optional[float] = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SymbolScheduleEntry":
        sym = str(raw.get("symbol", "")).strip()
        if not sym:
            raise ValueError("schedule entry requires symbol")
        af = raw.get("active_from_ms")
        au = raw.get("active_until_ms")
        return cls(
            symbol=sym,
            active_from_ms=float(af) if af is not None else None,
            active_until_ms=float(au) if au is not None else None,
        )


def parse_symbol_list(raw: str) -> List[str]:
    parts = [p.strip() for p in str(raw or "").split(",")]
    out = [p for p in parts if p]
    if not out:
        raise ValueError("at least one symbol required")
    return out


def load_schedule_file(path: str | Path) -> List[SymbolScheduleEntry]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("schedule file must be a JSON array")
    return [SymbolScheduleEntry.from_mapping(x) for x in data]


def schedule_for_symbol(
    schedule: Optional[Sequence[SymbolScheduleEntry]], symbol: str
) -> Optional[SymbolScheduleEntry]:
    if not schedule:
        return None
    for entry in schedule:
        if entry.symbol == symbol:
            return entry
    return None


def schedule_symbols_missing(
    symbols: Sequence[str],
    schedule: Optional[Sequence[SymbolScheduleEntry]],
) -> List[str]:
    """Takvim dosyasında kaydı olmayan semboller (kurumsal iddia öncesi zorunlu kontrol)."""
    if not schedule:
        return []
    known = {e.symbol for e in schedule}
    return [s for s in symbols if s not in known]


def symbol_active_at(entry: SymbolScheduleEntry, ts_ms: float) -> bool:
    """Sembol ``ts_ms`` anında borsada işlem görebilir mi (point-in-time üyelik)."""
    if entry.active_from_ms is not None and ts_ms < entry.active_from_ms:
        return False
    if entry.active_until_ms is not None and ts_ms > entry.active_until_ms:
        return False
    return True


def symbols_active_at(
    symbols: Sequence[str],
    schedule: Sequence[SymbolScheduleEntry],
    as_of_ms: float,
) -> List[str]:
    """``as_of_ms`` anında listede olan sembol alt kümesi."""
    by_sym = {e.symbol: e for e in schedule}
    return [s for s in symbols if s in by_sym and symbol_active_at(by_sym[s], as_of_ms)]


def filter_candles_by_schedule(
    candles: List[Dict[str, Any]],
    entry: Optional[SymbolScheduleEntry],
) -> List[Dict[str, Any]]:
    if entry is None:
        return candles
    out: List[Dict[str, Any]] = []
    for c in candles:
        try:
            ts = float(c.get("timestamp", 0))
        except (TypeError, ValueError):
            continue
        if entry.active_from_ms is not None and ts < entry.active_from_ms:
            continue
        if entry.active_until_ms is not None and ts > entry.active_until_ms:
            continue
        out.append(c)
    return out


def survivorship_disclosure(
    *,
    symbols: Sequence[str],
    has_point_in_time_schedule: bool,
    data_source: str,
    schedule_symbols_missing: Sequence[str] = (),
) -> Dict[str, Any]:
    """JSON/rapor için açık sınırlar — varsayılan: kurumsal evren iddiası yok."""
    n = len(symbols)
    missing = list(schedule_symbols_missing)
    schedule_complete = bool(has_point_in_time_schedule and not missing)
    controlled = bool(schedule_complete and n >= 1)
    institutional = bool(controlled and n >= 2)
    limitations: List[str] = []
    if n < 2:
        limitations.append("single_symbol_chain")
    if not has_point_in_time_schedule:
        limitations.append("no_point_in_time_universe_schedule")
        limitations.append("delisted_assets_not_excluded")
    if missing:
        limitations.append("schedule_missing_symbols")
    if data_source == "synthetic":
        limitations.append("synthetic_prices_not_exchange_history")
    if data_source == "ccxt":
        limitations.append("ccxt_latest_listing_survivorship_risk")

    return {
        "survivorship_bias_controlled": controlled,
        "institutional_universe_claim_allowed": institutional,
        "schedule_complete": schedule_complete,
        "schedule_symbols_missing": missing,
        "symbol_count": n,
        "symbols": list(symbols),
        "data_source": data_source,
        "limitations": limitations,
        "disclaimer_tr": (
            "Bu geri test delist edilen varlıkları ve geçmişte listelenmemiş çiftleri "
            "otomatik dahil etmez. Kurumsal 'evren' iddiası yalnızca point-in-time sembol "
            "takvimi (--universe-schedule) ile mümkündür; aksi halde sonuçlar mekanik doğrulama "
            "içindir, seçim yanlılığı (survivorship) içerebilir."
        ),
    }


@dataclass
class PerSymbolBacktest:
    symbol: str
    report: BacktestReport
    bars_used: int
    schedule_applied: bool


@dataclass
class UniverseBacktestResult:
    per_symbol: List[PerSymbolBacktest] = field(default_factory=list)
    mean_return_pct: float = 0.0
    median_return_pct: float = 0.0
    mean_sharpe: float = 0.0
    disclosure: Dict[str, Any] = field(default_factory=dict)


async def run_universe_backtest_async(
    candle_by_symbol: Dict[str, List[Dict[str, Any]]],
    *,
    schedule: Optional[Sequence[SymbolScheduleEntry]] = None,
    data_source: str = "unknown",
    capital_per_symbol: float = 10_000.0,
    **bt_kw: Any,
) -> UniverseBacktestResult:
    """Her sembol için bağımsız paper backtest (paylaşılan portföy yok — yanlış birleşim yok)."""
    rows: List[PerSymbolBacktest] = []
    kw_base = {k: v for k, v in bt_kw.items() if k not in ("symbol", "initial_capital")}
    cap = float(bt_kw.get("initial_capital", capital_per_symbol))
    for symbol, candles in candle_by_symbol.items():
        entry = schedule_for_symbol(schedule, symbol)
        filtered = filter_candles_by_schedule(candles, entry)
        order_issues = check_candle_timestamps_monotonic(filtered)
        if order_issues:
            _log.warning(
                "clock_skew | %s non-monotonic candles: %s",
                symbol,
                order_issues[0],
            )
        rep = await run_backtest_async(
            filtered,
            symbol=symbol,
            initial_capital=cap,
            **kw_base,
        )
        rows.append(
            PerSymbolBacktest(
                symbol=symbol,
                report=rep,
                bars_used=len(filtered),
                schedule_applied=schedule is not None and entry is not None,
            )
        )

    rets = [r.report.total_return_pct for r in rows]
    sharpes = [r.report.sharpe_ratio for r in rows]

    mean_ret = float(statistics.mean(rets)) if rets else 0.0
    med_ret = float(statistics.median(rets)) if rets else 0.0
    mean_sh = float(statistics.mean(sharpes)) if sharpes else 0.0

    syms = [r.symbol for r in rows]
    disc = survivorship_disclosure(
        symbols=syms,
        has_point_in_time_schedule=bool(schedule),
        data_source=data_source,
        schedule_symbols_missing=schedule_symbols_missing(syms, schedule),
    )
    return UniverseBacktestResult(
        per_symbol=rows,
        mean_return_pct=round(mean_ret, 2),
        median_return_pct=round(med_ret, 2),
        mean_sharpe=round(mean_sh, 4),
        disclosure=disc,
    )


def run_universe_backtest(
    candle_by_symbol: Dict[str, List[Dict[str, Any]]],
    **kwargs: Any,
) -> UniverseBacktestResult:
    return asyncio.run(run_universe_backtest_async(candle_by_symbol, **kwargs))


def universe_result_to_dict(result: UniverseBacktestResult) -> Dict[str, Any]:
    return {
        "mean_return_pct": result.mean_return_pct,
        "median_return_pct": result.median_return_pct,
        "mean_sharpe": result.mean_sharpe,
        "per_symbol": [
            {
                "symbol": r.symbol,
                "bars_used": r.bars_used,
                "schedule_applied": r.schedule_applied,
                "total_return_pct": r.report.total_return_pct,
                "sharpe_ratio": r.report.sharpe_ratio,
                "max_drawdown_pct": r.report.max_drawdown_pct,
                "n_trades": r.report.n_trades,
                "bars_simulated": r.report.bars_simulated,
            }
            for r in result.per_symbol
        ],
        "survivorship_disclosure": result.disclosure,
    }
