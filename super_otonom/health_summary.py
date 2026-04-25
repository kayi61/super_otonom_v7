"""
Tick başına / döngü başına bir satırlık sağlık özeti (kokpit).

Terminal + ayrı health logger (logs/health.log) için ortak metin.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

log_health = logging.getLogger("super_otonom.health")

_HEALTH_FILE_SETUP = False


def ensure_health_file_logger(log_dir: str = "logs") -> None:
    """
    Aynı process içinde bir kez: health.log dosyasına INFO yazar; root logger'a dokunmaz.
    """
    global _HEALTH_FILE_SETUP
    if _HEALTH_FILE_SETUP:
        return
    path = os.path.join(log_dir, "health.log")
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        log_health.addHandler(fh)
        log_health.setLevel(logging.INFO)
        log_health.propagate = True
    except OSError:
        log_health.propagate = True
    _HEALTH_FILE_SETUP = True


def format_durum_line(st: Dict[str, Any]) -> str:
    """
    Döngü sonu özet: equity, pnl, sigortalar, emergency, hard_limits, 429 fırtına sayacı.
    """
    hl = st.get("hard_limits") or {}
    oin  = int(hl.get("orders_in_window", 0))
    olim = int(hl.get("order_limit", 1))
    em = st.get("emergency_stop", False)
    eline = (st.get("emergency_code_line") or "—")
    rl  = st.get("rate_limit") or {}
    rls = int(rl.get("rl_streak", 0))
    rlt = int(rl.get("rl_trip", 0))
    fuses = f"Fuses ob={oin}/{olim} win={round(float(hl.get('window_sec', 0)), 1)}s rl={rls}/{rlt}"
    return (
        f"eq={st.get('equity', 0):.2f} pnl={st.get('total_pnl', 0):.2f}({st.get('pnl_pct', 0):.1f}%%) "
        f"dd={st.get('peak_drawdown_pct', 0):.1f}%% exp={st.get('exposure_pct', 0):.1f}%% "
        f"tr={st.get('total_trades', 0)} emerg={em} code={eline} | {fuses}"
    )


def format_tick_health(
    st: Dict[str, Any],
    dctx: Optional[Dict[str, Any]],
) -> str:
    """
    Örnek: [OK] PnL: +0.2% | Exp: 15% | Lim: 0/10 | Status: Active | tick=42 BTC/USDT
    """
    hl = st.get("hard_limits") or {}
    oin  = int(hl.get("orders_in_window", 0))
    olim = int(hl.get("order_limit", 1))
    pnl  = float(st.get("pnl_pct", 0.0))
    exp  = float(st.get("exposure_pct", 0.0))
    emerg = bool(st.get("emergency_stop"))
    d_em = (dctx or {}).get("emergency_code")
    if d_em or emerg:
        tag = "[HALT]"
    else:
        tag = "[OK]"

    reason = st.get("emergency_reason") or ""
    if dctx and dctx.get("emergency_code"):
        reason = str(dctx["emergency_code"]).replace("EMERGENCY_STOP:", "")

    if reason:
        st_label = f"Emergency({reason})"
    elif emerg:
        st_label = "Emergency(on)"
    else:
        st_label = "Active"

    sym  = (dctx or {}).get("symbol", "—")
    t_id = (dctx or {}).get("tick_id", "—")
    pnl_s = f"{pnl:+.1f}%"
    scale  = (dctx or {}).get("entry_scale") or "—"
    scale_u = str(scale).upper() if scale != "—" else "—"
    liq_r  = (dctx or {}).get("liquidity_ratio")
    liq_s  = f"{float(liq_r):.2f}" if liq_r is not None else "—"
    sig = (dctx or {}).get("final_signal", "HOLD")
    qv  = (dctx or {}).get("signal_quality")
    qadj = (dctx or {}).get("adj_signal_quality")
    effq = (dctx or {}).get("effective_quality_min")
    qstr = f"{int(qv)}" if qv is not None else "—"
    qadj_s = f"{int(qadj)}" if qadj is not None else "—"
    effq_s = f"{int(effq)}" if effq is not None else "—"
    olog = (dctx or {}).get("omega_ai_log") or ""
    oshort = (olog[:120] + "…") if len(olog) > 120 else olog
    return (
        f"{tag} {sig} | Qraw:{qstr} Qadj:{qadj_s} | effective_qmin:{effq_s} | Scale:{scale_u} | "
        f"PnL: {pnl_s} | Exp: {exp:.0f}% | Lim: {oin}/{olim} | Liq:{liq_s} | "
        f"Status: {st_label} | tick={t_id} {sym}"
        + (f" | {oshort}" if oshort else "")
    )


def log_tick_health(
    st: Dict[str, Any],
    dctx: Optional[Dict[str, Any]],
) -> None:
    line = format_tick_health(st, dctx)
    log_health.info("%s", line)
    for h in log_health.handlers:
        if isinstance(h, logging.FileHandler):
            h.flush()
