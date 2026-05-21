#!/usr/bin/env python3
"""VR-22: Günlük Risk Raporu — Otomatik Üretim.

Kullanım:
    python scripts/generate_daily_risk_report.py
    python scripts/generate_daily_risk_report.py --date 2026-05-20
    python scripts/generate_daily_risk_report.py --out /tmp/risk.md
    python scripts/generate_daily_risk_report.py --json  # JSON çıktısı

Çıktı: docs/risk_reports/risk_YYYY-MM-DD.md

Rapor Bölümleri (10):
  1. Özet tablosu (capital, NAV, exposure, leverage)
  2. VaR matrisi (model × conf)
  3. CVaR matrisi
  4. Stressed VaR
  5. Top 10 pozisyon + component VaR
  6. Stres senaryo sonuçları (worst 5)
  7. VaR backtest (Kupiec / Christoffersen / traffic light)
  8. P&L attribution
  9. Limit breach log
 10. Manuel inceleme gerektiren olaylar

Cron (staging/prod):
    55 23 * * * cd /opt/super_otonom && python scripts/generate_daily_risk_report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ── Path setup ──────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# var_topology sentinel
daily_risk_report_active = True


def _reconfigure_stdio_utf8() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, AttributeError):
                pass


# ── Data collection ─────────────────────────────────────────────────────────


def _collect_capital_snapshot() -> Dict[str, Any]:
    """Collect capital and exposure data from latest state."""
    from super_otonom.config import RISK

    capital_file = _ROOT / "data" / "capital_journal.jsonl"
    equity = 10_000.0  # default
    free_capital = 10_000.0
    if capital_file.is_file():
        try:
            lines = capital_file.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                last = json.loads(lines[-1])
                equity = last.get("equity", equity)
                free_capital = last.get("free_capital", equity)
        except (json.JSONDecodeError, OSError):
            pass

    nav = equity
    gross_exposure = equity - free_capital
    leverage = gross_exposure / nav if nav > 0 else 0.0

    return {
        "equity": equity,
        "nav": nav,
        "free_capital": free_capital,
        "gross_exposure": gross_exposure,
        "net_exposure": gross_exposure,  # simplified: gross ≈ net for unidirectional
        "leverage": leverage,
        "max_daily_loss_pct": RISK.get("max_daily_loss_pct", 0.05),
        "max_total_drawdown": RISK.get("max_total_drawdown", 0.20),
    }


def _collect_risk_metrics(
    returns: Sequence[float],
    positions: Optional[Dict[str, float]] = None,
    asset_returns: Optional[Dict[str, Sequence[float]]] = None,
) -> Optional[Any]:
    """Run RiskEngine.compute() and return RiskMetrics."""
    if len(returns) < 20:
        return None
    try:
        from super_otonom.risk.config import RiskConfig
        from super_otonom.risk.risk_engine import RiskEngine

        cfg = RiskConfig()
        engine = RiskEngine()
        kwargs: Dict[str, Any] = {}
        if positions:
            kwargs["positions"] = positions
        if asset_returns:
            kwargs["asset_returns"] = asset_returns

        # Try loading stress fixture
        try:
            from super_otonom.risk.stressed_var import StressedVaR

            sv = StressedVaR.from_fixture()
            kwargs["stress_returns"] = sv._stress_periods
        except Exception:
            pass

        return engine.compute(list(returns), config=cfg, **kwargs)
    except Exception:
        return None


def _load_returns() -> List[float]:
    """Load realized PnL returns from data/realized_pnl.json."""
    path = _ROOT / "data" / "realized_pnl.json"
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "returns" in raw:
            return [float(r) for r in raw["returns"]]
        if isinstance(raw, list):
            return [float(r) for r in raw]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _load_positions() -> Dict[str, float]:
    """Load current positions from data/positions.json."""
    path = _ROOT / "data" / "positions.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {k: float(v) for k, v in raw.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _load_limit_breaches() -> List[Dict[str, Any]]:
    """Load limit breach events from data/breach_log.jsonl."""
    path = _ROOT / "data" / "breach_log.jsonl"
    if not path.is_file():
        return []
    breaches: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").strip().splitlines()[-50:]:
            try:
                breaches.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return breaches


def _load_stress_results() -> List[Dict[str, Any]]:
    """Load stress scenario grid results if available."""
    try:
        from super_otonom.risk.stress_scenarios import (
            load_scenarios,
            run_stress_grid,
        )

        positions = _load_positions()
        if not positions:
            positions = {"BTC/USDT": 0.5, "ETH/USDT": 0.3}  # placeholder

        scenarios = load_scenarios()
        if not scenarios:
            return []

        result = run_stress_grid(positions, scenarios)
        rows = []
        for sr in sorted(result.results, key=lambda r: r.pnl_pct)[:5]:
            rows.append({
                "scenario": sr.scenario_name,
                "pnl_pct": sr.pnl_pct,
                "horizon_h": sr.horizon_h,
            })
        return rows
    except Exception:
        return []


def _load_backtest_results(
    returns: Sequence[float],
) -> Dict[str, Any]:
    """Run Kupiec / Christoffersen / Basel traffic light on available data."""
    result: Dict[str, Any] = {
        "kupiec": None,
        "christoffersen": None,
        "traffic_light": None,
    }
    if len(returns) < 50:
        return result

    try:
        from super_otonom.risk.var_models import historical_var

        var_99_series = [
            historical_var(returns[: i + 1], 0.99) for i in range(49, len(returns))
        ]
        pnl_tail = list(returns[49:])

        from super_otonom.risk.var_backtest import kupiec_pof

        kr = kupiec_pof(pnl_tail, var_99_series, conf=0.99)
        result["kupiec"] = {
            "p_value": kr.p_value,
            "exceedances": kr.exceedances,
            "expected": kr.expected,
            "model_valid": kr.model_valid,
            "n_obs": kr.n_obs,
        }
    except Exception:
        pass

    try:
        from super_otonom.risk.var_backtest import christoffersen_cc

        cc = christoffersen_cc(pnl_tail, var_99_series, conf=0.99)
        result["christoffersen"] = {
            "kupiec_pvalue": cc.kupiec.p_value,
            "ind_pvalue": cc.independence.p_value,
            "cc_pvalue": cc.p_value,
            "model_valid": cc.model_valid,
        }
    except Exception:
        pass

    try:
        from super_otonom.risk.var_backtest import basel_traffic_light_from_pnl

        tl = basel_traffic_light_from_pnl(pnl_tail, var_99_series, conf=0.99)
        result["traffic_light"] = {
            "zone": tl.zone,
            "exceedances": tl.exceedances,
            "capital_addon": tl.capital_addon,
            "window": tl.window,
        }
    except Exception:
        pass

    return result


def _load_pnl_attribution() -> Optional[Dict[str, Any]]:
    """Load latest PnL attribution data."""
    path = _ROOT / "data" / "pnl_attribution_latest.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# ── Report sections ─────────────────────────────────────────────────────────


def _fmt_pct(val: float | None, decimals: int = 4) -> str:
    if val is None:
        return "—"
    return f"{val:.{decimals}f}"


def _fmt_pct_display(val: float | None) -> str:
    if val is None:
        return "—"
    return f"{val * 100:.2f}%"


def _section_1_summary(cap: Dict[str, Any]) -> str:
    """Bölüm 1: Özet tablosu."""
    return f"""## 1. Özet

| Metrik | Değer |
|--------|-------|
| Sermaye (Equity) | {cap['equity']:,.2f} USDT |
| NAV | {cap['nav']:,.2f} USDT |
| Serbest Sermaye | {cap['free_capital']:,.2f} USDT |
| Brüt Exposure | {cap['gross_exposure']:,.2f} USDT |
| Net Exposure | {cap['net_exposure']:,.2f} USDT |
| Kaldıraç | {cap['leverage']:.2f}x |
| Günlük Kayıp Limiti | {_fmt_pct_display(cap['max_daily_loss_pct'])} |
| Max Drawdown Limiti | {_fmt_pct_display(cap['max_total_drawdown'])} |
"""


def _section_2_var_matrix(metrics: Any) -> str:
    """Bölüm 2: VaR matrisi (model × conf)."""
    if metrics is None:
        return "## 2. VaR Matrisi\n\n> Yetersiz veri — VaR hesaplanamadı.\n"

    rows = [
        ("Historical", "var_historical_95", "var_historical_99"),
        ("Parametric (t)", "var_parametric_95", "var_parametric_99"),
        ("Monte Carlo", "var_monte_carlo_95", "var_monte_carlo_99"),
        ("Cornish-Fisher", "var_cornish_fisher_95", "var_cornish_fisher_99"),
        ("FHS (GARCH)", "var_fhs_95", "var_fhs_99"),
        ("EVT (POT)", None, "var_evt_99"),
        ("Regime Cond.", "var_regime_conditional_95", "var_regime_conditional_99"),
        ("**Aggregate**", "var_for_limits_95", "var_for_limits_99"),
    ]

    lines = [
        "## 2. VaR Matrisi\n",
        "| Model | VaR 95% | VaR 99% |",
        "|-------|---------|---------|",
    ]
    for label, attr95, attr99 in rows:
        v95 = _fmt_pct(getattr(metrics, attr95, None)) if attr95 else "—"
        v99 = _fmt_pct(getattr(metrics, attr99, None)) if attr99 else "—"
        lines.append(f"| {label} | {v95} | {v99} |")

    return "\n".join(lines) + "\n"


def _section_3_cvar_matrix(metrics: Any) -> str:
    """Bölüm 3: CVaR matrisi."""
    if metrics is None:
        return "## 3. CVaR Matrisi\n\n> Yetersiz veri.\n"

    rows = [
        ("Historical", "cvar_historical_95", "cvar_historical_99"),
        ("Parametric", "cvar_parametric_95", "cvar_parametric_99"),
        ("Monte Carlo", "cvar_monte_carlo_95", "cvar_monte_carlo_99"),
        ("FHS", "cvar_fhs_95", "cvar_fhs_99"),
        ("EVT", None, "cvar_evt_99"),
        ("**Aggregate**", "cvar_95_1d", "cvar_99_1d"),
    ]

    lines = [
        "## 3. CVaR / Expected Shortfall Matrisi\n",
        "| Model | CVaR 95% | CVaR 99% |",
        "|-------|----------|----------|",
    ]
    for label, attr95, attr99 in rows:
        v95 = _fmt_pct(getattr(metrics, attr95, None)) if attr95 else "—"
        v99 = _fmt_pct(getattr(metrics, attr99, None)) if attr99 else "—"
        lines.append(f"| {label} | {v95} | {v99} |")

    cvar_975 = getattr(metrics, "cvar_975_1d", None)
    lines.append(f"\n**CVaR 97.5% (Basel FRTB ES):** {_fmt_pct(cvar_975)}")

    return "\n".join(lines) + "\n"


def _section_4_stressed_var(metrics: Any) -> str:
    """Bölüm 4: Stressed VaR."""
    if metrics is None:
        return "## 4. Stressed VaR (Basel 2.5)\n\n> Yetersiz veri.\n"

    svar = getattr(metrics, "stressed_var", 0.0)
    worst = getattr(metrics, "stressed_var_worst_period", "—")
    breach = getattr(metrics, "stressed_var_breach", False)
    var_99 = getattr(metrics, "var_99_1d", 0.0)
    ratio = svar / var_99 if var_99 > 1e-12 else 0.0

    return f"""## 4. Stressed VaR (Basel 2.5)

| Metrik | Değer |
|--------|-------|
| Stressed VaR | {_fmt_pct(svar)} |
| En kötü dönem | {worst} |
| sVaR / VaR₉₉ oranı | {ratio:.2f}x |
| Breach (>2x) | {'⚠️ EVET' if breach else '✅ Hayır'} |
| Model dispersion | {_fmt_pct(getattr(metrics, 'model_dispersion_pct', None))} |
"""


def _section_5_positions(
    metrics: Any, positions: Dict[str, float],
) -> str:
    """Bölüm 5: Top 10 pozisyon + component VaR."""
    if not positions and metrics is None:
        return "## 5. Pozisyon ve Component VaR\n\n> Açık pozisyon yok.\n"

    comp_var = getattr(metrics, "component_var_per_position", {}) if metrics else {}
    marg_var = getattr(metrics, "marginal_var_per_position", {}) if metrics else {}
    var_total = getattr(metrics, "var_for_limits_95", 1.0) if metrics else 1.0
    var_total = var_total if var_total and abs(var_total) > 1e-12 else 1.0

    all_symbols = sorted(
        set(list(positions.keys()) + list(comp_var.keys())),
        key=lambda s: abs(comp_var.get(s, 0.0)),
        reverse=True,
    )[:10]

    lines = [
        "## 5. Top 10 Pozisyon ve Component VaR\n",
        "| # | Sembol | Ağırlık | Comp VaR | Comp/Total | Marginal VaR |",
        "|---|--------|---------|----------|------------|--------------|",
    ]
    for i, sym in enumerate(all_symbols, 1):
        w = positions.get(sym, 0.0)
        cv = comp_var.get(sym, 0.0)
        mv = marg_var.get(sym, 0.0)
        ratio = abs(cv) / abs(var_total)
        lines.append(
            f"| {i} | {sym} | {_fmt_pct_display(w)} | {_fmt_pct(cv)} | "
            f"{_fmt_pct_display(ratio)} | {_fmt_pct(mv)} |"
        )

    if not all_symbols:
        lines.append("| — | Pozisyon yok | — | — | — | — |")

    return "\n".join(lines) + "\n"


def _section_6_stress(stress_results: List[Dict[str, Any]]) -> str:
    """Bölüm 6: Stres senaryo sonuçları."""
    if not stress_results:
        return "## 6. Stres Senaryo Sonuçları\n\n> Senaryo verisi yok.\n"

    lines = [
        "## 6. Stres Senaryo Sonuçları (En Kötü 5)\n",
        "| # | Senaryo | PnL (%) | Horizon |",
        "|---|---------|---------|---------|",
    ]
    for i, sr in enumerate(stress_results, 1):
        lines.append(
            f"| {i} | {sr['scenario']} | {sr['pnl_pct'] * 100:.2f}% | "
            f"{sr.get('horizon_h', '—')}h |"
        )

    return "\n".join(lines) + "\n"


def _section_7_backtest(bt: Dict[str, Any]) -> str:
    """Bölüm 7: VaR Backtest (Kupiec / Christoffersen / Traffic Light)."""
    lines = ["## 7. VaR Backtest\n"]

    kup = bt.get("kupiec")
    if kup:
        lines.append("### Kupiec POF Test (99% VaR)\n")
        lines.append("| Metrik | Değer |")
        lines.append("|--------|-------|")
        lines.append(f"| Gözlem sayısı | {kup['n_obs']} |")
        lines.append(f"| Exceedance | {kup['exceedances']} (beklenen: {kup['expected']:.1f}) |")
        lines.append(f"| p-değeri | {kup['p_value']:.4f} |")
        status = "✅ Geçerli" if kup["model_valid"] else "⚠️ Geçersiz"
        lines.append(f"| Model durumu | {status} |")
        lines.append("")
    else:
        lines.append("> Kupiec testi: yetersiz veri (min 50 gözlem).\n")

    cc = bt.get("christoffersen")
    if cc:
        lines.append("### Christoffersen CC Test\n")
        lines.append("| Metrik | Değer |")
        lines.append("|--------|-------|")
        lines.append(f"| Kupiec p-değeri | {cc['kupiec_pvalue']:.4f} |")
        lines.append(f"| Independence p-değeri | {cc['ind_pvalue']:.4f} |")
        lines.append(f"| CC p-değeri | {cc['cc_pvalue']:.4f} |")
        status = "✅ Geçerli" if cc["model_valid"] else "⚠️ Geçersiz"
        lines.append(f"| Model durumu | {status} |")
        lines.append("")

    tl = bt.get("traffic_light")
    if tl:
        zone_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(
            tl["zone"], "⚪"
        )
        lines.append("### Basel Traffic Light\n")
        lines.append("| Metrik | Değer |")
        lines.append("|--------|-------|")
        lines.append(f"| Bölge | {zone_emoji} {tl['zone']} |")
        lines.append(f"| Exceedance | {tl['exceedances']} / {tl['window']} |")
        lines.append(f"| Sermaye ek yüklemesi | +{tl['capital_addon']:.2f} |")
        lines.append("")
    else:
        lines.append("> Basel traffic light: yetersiz veri.\n")

    return "\n".join(lines) + "\n"


def _section_8_pnl_attribution(attr_data: Optional[Dict[str, Any]]) -> str:
    """Bölüm 8: P&L Attribution."""
    if attr_data is None:
        return "## 8. P&L Attribution\n\n> Attribution verisi mevcut değil.\n"

    lines = [
        "## 8. P&L Attribution\n",
        "| Kalem | Değer |",
        "|-------|-------|",
    ]
    for key in (
        "explained",
        "trades",
        "unexplained",
        "actual_pnl",
        "unexplained_pct",
        "unexplained_bps",
        "drift_detected",
    ):
        val = attr_data.get(key, "—")
        if isinstance(val, float):
            val = f"{val:.6f}"
        elif isinstance(val, bool):
            val = "⚠️ Evet" if val else "✅ Hayır"
        lines.append(f"| {key} | {val} |")

    return "\n".join(lines) + "\n"


def _section_9_breach_log(breaches: List[Dict[str, Any]]) -> str:
    """Bölüm 9: Limit breach log."""
    if not breaches:
        return "## 9. Limit Breach Log\n\n> Son 24 saatte limit ihlali yok. ✅\n"

    lines = [
        "## 9. Limit Breach Log\n",
        "| Zaman | Tür | Detay |",
        "|-------|-----|-------|",
    ]
    for b in breaches[-20:]:
        ts = b.get("timestamp", "—")
        btype = b.get("type", "unknown")
        detail = b.get("detail", b.get("message", "—"))
        lines.append(f"| {ts} | {btype} | {detail} |")

    return "\n".join(lines) + "\n"


def _section_10_manual_review(
    metrics: Any,
    bt: Dict[str, Any],
    breaches: List[Dict[str, Any]],
) -> str:
    """Bölüm 10: Manuel inceleme gerektiren olaylar."""
    flags: List[str] = []

    if metrics is not None:
        disp = getattr(metrics, "model_dispersion_pct", 0.0) or 0.0
        if disp > 0.5:
            flags.append(
                f"⚠️ Model dispersion yüksek: {disp:.2%} (>50%) — model kalibrasyonu gözden geçirin"
            )

        breach = getattr(metrics, "stressed_var_breach", False)
        if breach:
            flags.append("🔴 Stressed VaR > 2 × VaR₉₉ — acil durum tetiklenebilir")

        lvar = getattr(metrics, "lvar", 0.0) or 0.0
        if lvar > 0.06:
            flags.append(f"⚠️ LVaR yüksek: {lvar:.4f} — likidite riski gözden geçirin")

    kup = bt.get("kupiec")
    if kup and not kup.get("model_valid", True):
        flags.append("⚠️ Kupiec POF test başarısız — VaR modeli güncellenmeli")

    cc = bt.get("christoffersen")
    if cc and not cc.get("model_valid", True):
        flags.append("⚠️ Christoffersen CC test başarısız — exceedance kümelenmesi var")

    tl = bt.get("traffic_light")
    if tl and tl.get("zone") == "RED":
        flags.append("🔴 Basel traffic light RED — model reddedildi")
    elif tl and tl.get("zone") == "YELLOW":
        flags.append("🟡 Basel traffic light YELLOW — sermaye ek yüklemesi gerekli")

    if breaches:
        flags.append(f"⚠️ {len(breaches)} limit ihlali kaydedildi — detay bölüm 9")

    if not flags:
        return "## 10. Manuel İnceleme\n\n> Manuel inceleme gerektiren olay yok. ✅\n"

    lines = ["## 10. Manuel İnceleme Gerektiren Olaylar\n"]
    for f in flags:
        lines.append(f"- {f}")

    return "\n".join(lines) + "\n"


# ── Report assembly ─────────────────────────────────────────────────────────


def generate_report(
    *,
    report_date: Optional[str] = None,
) -> str:
    """Generate the full daily risk report as Markdown."""
    date_str = report_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Collect data
    cap = _collect_capital_snapshot()
    returns = _load_returns()
    positions = _load_positions()
    metrics = _collect_risk_metrics(returns, positions or None)
    stress_results = _load_stress_results()
    bt = _load_backtest_results(returns)
    pnl_attr = _load_pnl_attribution()
    breaches = _load_limit_breaches()

    # VaR limits for header
    try:
        from super_otonom.risk.var_limits import load_var_limits

        limits = load_var_limits()
        limits_valid = limits.is_valid
    except Exception:
        limits = None
        limits_valid = None

    # Header
    header = f"""# Günlük Risk Raporu

**Tarih:** {date_str}
**Üretim zamanı:** {now_str}
**Return gözlem sayısı:** {len(returns)}
**VaR Limit Hierarchy:** {'✅ Geçerli' if limits_valid else '⚠️ Geçersiz veya yüklenemedi'}

---
"""

    # Assemble sections
    sections = [
        header,
        _section_1_summary(cap),
        _section_2_var_matrix(metrics),
        _section_3_cvar_matrix(metrics),
        _section_4_stressed_var(metrics),
        _section_5_positions(metrics, positions),
        _section_6_stress(stress_results),
        _section_7_backtest(bt),
        _section_8_pnl_attribution(pnl_attr),
        _section_9_breach_log(breaches),
        _section_10_manual_review(metrics, bt, breaches),
    ]

    footer = f"""---

*Otomatik üretildi: `scripts/generate_daily_risk_report.py` (VR-22)*
*Sonraki rapor: {date_str} 23:55 UTC*
"""
    sections.append(footer)

    return "\n".join(sections)


def generate_report_json(
    *,
    report_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate report data as structured JSON."""
    date_str = report_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cap = _collect_capital_snapshot()
    returns = _load_returns()
    positions = _load_positions()
    metrics = _collect_risk_metrics(returns, positions or None)
    bt = _load_backtest_results(returns)
    pnl_attr = _load_pnl_attribution()
    breaches = _load_limit_breaches()

    metrics_dict: Dict[str, Any] = {}
    if metrics is not None:
        for attr in (
            "var_95_1d", "var_99_1d", "var_975_1d",
            "cvar_95_1d", "cvar_975_1d", "cvar_99_1d",
            "stressed_var", "stressed_var_worst_period", "stressed_var_breach",
            "model_dispersion_pct", "lvar", "lvar_data_health",
            "var_for_limits_95", "var_for_limits_99",
        ):
            metrics_dict[attr] = getattr(metrics, attr, None)

    return {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "capital": cap,
        "n_returns": len(returns),
        "risk_metrics": metrics_dict,
        "backtest": bt,
        "pnl_attribution": pnl_attr,
        "breach_count": len(breaches),
        "positions": positions,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    _reconfigure_stdio_utf8()

    parser = argparse.ArgumentParser(
        description="VR-22: Günlük Risk Raporu üretici.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Rapor tarihi (YYYY-MM-DD). Varsayılan: bugün UTC.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Çıktı dosyası. Varsayılan: docs/risk_reports/risk_YYYY-MM-DD.md",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON çıktısı (stdout).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Markdown'ı dosya yerine stdout'a yaz.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if args.json:
        data = generate_report_json(report_date=date_str)
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return 0

    report = generate_report(report_date=date_str)

    if args.stdout:
        print(report)
        return 0

    out_path = Path(args.out) if args.out else _ROOT / "docs" / "risk_reports" / f"risk_{date_str}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Rapor yazıldı: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
