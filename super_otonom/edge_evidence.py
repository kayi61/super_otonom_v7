"""
Faz 9.1 — Edge kanıtı: komisyon (bps/taraf) + ExecutionSimulator slip ile
tam örnek geri test ve isteğe bağlı WFA test dilimleri.

final_signal histogramı ile çoğu HOLD durumunun (düşük frekans / sıkı filtre)
ölçülebilir bir özeti üretilir; kârlılık varsayılmaz.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from typing import Any, Dict, List, Optional

import pandas as pd

from super_otonom.backtester import run_backtest
from super_otonom.data_freshness import (
    LEGACY_PERIODS_PER_YEAR_STOCK_5M,
    periods_per_year_from_timeframe,
    sharpe_annualize_factor_vs_legacy,
)
from super_otonom.exchange_async import ohlcv_to_candles
from super_otonom.wfa_manager import WFAManager

log = logging.getLogger("super_otonom.edge_evidence")


def _synthetic_ohlcv_rows(symbol: str, limit: int, seed: int) -> List[List[float]]:
    rng = random.Random(seed)
    price = {"BTC/USDT": 65000.0, "ETH/USDT": 3500.0}.get(symbol, 100.0)
    ts_base = int(time.time() * 1000) - limit * 300_000
    out: List[List[float]] = []
    ts = ts_base
    for _ in range(limit):
        o = price * (1 + rng.uniform(-0.002, 0.002))
        h = o * (1 + rng.uniform(0, 0.005))
        lo = o * (1 - rng.uniform(0, 0.005))
        c = rng.uniform(lo, h)
        v = rng.uniform(1.0, 50.0)
        out.append([ts, o, h, lo, c, v])
        price = c
        ts += 300_000
    return out


def fetch_ccxt_candles(symbol: str, timeframe: str, limit: int) -> List[Dict[str, Any]]:
    import ccxt

    ex = ccxt.binance({"enableRateLimit": True})
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    return ohlcv_to_candles(raw)


def _fold_test_candles(test_df: pd.DataFrame) -> List[Dict[str, Any]]:
    return test_df.to_dict("records")


def interpret(
    hold_frac: float,
    action_count: int,
    n_trades: int,
    total_return_pct: float,
) -> str:
    parts = []
    if action_count <= 0:
        parts.append("Yeterli tick üretilmedi.")
        return " ".join(parts)
    if hold_frac >= 0.9:
        parts.append(
            "Sinyallerin çoğu HOLD — bu ya düşük frekanslı strateji ya da sıkı ön "
            "filtreler nedeniyle beklenen davranış olabilir; tek başına kârlılık kanıtı değildir."
        )
    elif hold_frac <= 0.5:
        parts.append(
            "HOLD oranı düşük — yüksek işlem frekansı; komisyon ve slip ile edge eriyebilir."
        )
    if n_trades < 3:
        parts.append(
            "Kapalı işlem sayısı çok az — istatistiksel edge iddiası için veri yetersiz olabilir."
        )
    parts.append(
        f"Net simülasyon getirisi ~{total_return_pct:.2f}% (komisyon + slip dahil varsayımlarla); "
        "'bot çalışıyor = para kazanıyor' çıkarımı yapılmamalı."
    )
    return " ".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    if argv is None:
        argv = sys.argv[1:]
    p = argparse.ArgumentParser(
        description="Faz 9.1 edge kanıtı: geri test + WFA test dilimleri (komisyon + slip)."
    )
    p.add_argument("--source", choices=("synthetic", "ccxt"), default="synthetic")
    p.add_argument("--symbol", default="BTC/USDT")
    p.add_argument("--timeframe", default="5m")
    p.add_argument("--limit", type=int, default=600)
    p.add_argument("--initial-capital", type=float, default=10_000.0)
    p.add_argument(
        "--fee-bps",
        type=float,
        default=10.0,
        metavar="BPS",
        help="Taraf başına komisyon (basis point); örn. 10 ≈ %%0.10",
    )
    p.add_argument("--slip-min", type=float, default=0.0002)
    p.add_argument("--slip-max", type=float, default=0.0012)
    p.add_argument("--exec-seed", type=int, default=42)
    p.add_argument("--window-size", type=int, default=280)
    p.add_argument("--step-size", type=int, default=120)
    p.add_argument("--no-wfa", action="store_true", help="Yalnızca tek tam örnek geri test.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    slip_rng = (float(args.slip_min), float(args.slip_max))
    if slip_rng[0] > slip_rng[1]:
        print("slip-min slip-max'tan büyük olamaz.", file=sys.stderr)
        return 2

    if args.source == "synthetic":
        raw = _synthetic_ohlcv_rows(args.symbol, args.limit, args.exec_seed)
        candles = ohlcv_to_candles(raw)
    else:
        candles = fetch_ccxt_candles(args.symbol, args.timeframe, args.limit)

    if len(candles) < 80:
        print("Yetersiz mum.", file=sys.stderr)
        return 1

    tf = str(args.timeframe).strip().lower()
    ppy = periods_per_year_from_timeframe(tf)
    bt_kw: Dict[str, Any] = dict(
        symbol=args.symbol,
        initial_capital=args.initial_capital,
        paper_fee_bps_per_side=float(args.fee_bps),
        exec_slippage_range=slip_rng,
        exec_seed=args.exec_seed,
        min_bars=35,
        max_window=150,
        timeframe=tf,
    )

    out: Dict[str, Any] = {
        "symbol": args.symbol,
        "source": args.source,
        "timeframe": tf,
        "periods_per_year": round(ppy, 2),
        "legacy_periods_per_year_wrong": LEGACY_PERIODS_PER_YEAR_STOCK_5M,
        "sharpe_factor_vs_legacy_default": round(
            sharpe_annualize_factor_vs_legacy(tf), 4
        ),
        "fee_bps_per_side": args.fee_bps,
        "slippage_range": list(slip_rng),
        "exec_seed": args.exec_seed,
        "folds": [],
        "full_sample": None,
    }

    hist_full: Dict[str, int] = {}
    rep_full = run_backtest(candles, final_signal_histo=hist_full, **bt_kw)
    total_actions = sum(hist_full.values())
    hold_frac_full = (hist_full.get("HOLD", 0) / total_actions) if total_actions else 0.0
    out["full_sample"] = {
        "bars_simulated": rep_full.bars_simulated,
        "total_return_pct": rep_full.total_return_pct,
        "n_trades": rep_full.n_trades,
        "sharpe_ratio": rep_full.sharpe_ratio,
        "max_drawdown_pct": rep_full.max_drawdown_pct,
        "final_signal_hist": dict(hist_full),
        "hold_fraction": round(hold_frac_full, 4),
        "interpretation": interpret(
            hold_frac_full, total_actions, rep_full.n_trades, rep_full.total_return_pct
        ),
    }

    if not args.no_wfa:
        df = pd.DataFrame(candles)
        n = len(df)
        margin = 55
        max_ws = max(n - margin, 0)
        if max_ws < 90:
            out["folds_note"] = "WFA atlandı: seri çok kısa (pencere için yeterli bar yok)."
        else:
            ws = min(max(args.window_size, 80), max_ws)
            step = max(40, min(args.step_size, max(ws // 2, 40)))
            mgr = WFAManager(df, window_size=ws, step_size=step)
            folds = mgr.get_folds()
            if not folds:
                out["folds_note"] = "WFA fold üretilemedi (pencere/adım veya min test boyutu)."
            for fold in folds:
                test_candles = _fold_test_candles(fold.test)
                hist: Dict[str, int] = {}
                rep = run_backtest(test_candles, final_signal_histo=hist, **bt_kw)
                ta = sum(hist.values())
                hf = (hist.get("HOLD", 0) / ta) if ta else 0.0
                out["folds"].append(
                    {
                        "fold_id": fold.fold_id,
                        "test_bars": len(test_candles),
                        "train_range": fold.train_range,
                        "test_range": fold.test_range,
                        "total_return_pct": rep.total_return_pct,
                        "n_trades": rep.n_trades,
                        "bars_simulated": rep.bars_simulated,
                        "hold_fraction": round(hf, 4),
                        "final_signal_hist": dict(hist),
                    }
                )

    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print("=== Faz 9.1 Edge özeti ===")
        print(
            f"Kaynak: {args.source} | {args.symbol} | TF: {tf} | "
            f"ppy={ppy:.0f} (legacy yanlış={LEGACY_PERIODS_PER_YEAR_STOCK_5M:.0f}) | mum: {len(candles)}"
        )
        print(f"Komisyon: {args.fee_bps} bps/taraf | slip: {slip_rng} | seed: {args.exec_seed}")
        fs = out["full_sample"]
        assert fs is not None
        print(
            f"\n[Tam örnek] getiri %: {fs['total_return_pct']} | işlem: {fs['n_trades']} | "
            f"Sharpe: {fs['sharpe_ratio']} | MDD %: {fs['max_drawdown_pct']}"
        )
        print(f"  HOLD oranı: {fs['hold_fraction']} | hist: {fs['final_signal_hist']}")
        print(f"  → {fs['interpretation']}")
        if out.get("folds"):
            print("\n[WFA test dilimleri]")
            for f in out["folds"]:
                print(
                    f"  fold {f['fold_id']}: getiri %={f['total_return_pct']} "
                    f"trades={f['n_trades']} HOLD%={f['hold_fraction']:.2f} bars={f['test_bars']}"
                )
        elif out.get("folds_note"):
            print(f"\n{out['folds_note']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
