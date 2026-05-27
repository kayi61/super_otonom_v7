"""
Saat / clock skew — borsa offset ölçümü ve host NTP sondası (audit madde 6).

Kurumsal NTP işletimi iddiası yok; ccxt ``timeDifference`` + Prometheus gauge + alarm.
Mum sırası: ``check_candle_timestamps_monotonic`` ile tespit (mutabakat öncesi uyarı).
"""

from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

log = logging.getLogger("super_otonom.clock_skew")

_REPO = Path(__file__).resolve().parents[1]
_COMPOSE_MARKER = "audit 6"

CLOCK_SKEW_WARN_MS = int(os.getenv("CLOCK_SKEW_WARN_MS", "500"))
CLOCK_SKEW_CRIT_MS = int(os.getenv("CLOCK_SKEW_CRIT_MS", "2000"))


@dataclass(frozen=True)
class SkewEvaluation:
    skew_ms: int
    abs_skew_ms: int
    level: str  # ok | warning | critical
    warn_threshold_ms: int
    crit_threshold_ms: int


def read_ccxt_skew_ms(exchange: Any) -> Optional[int]:
    """ccxt ``load_time_difference`` sonrası ``options['timeDifference']`` (ms)."""
    if exchange is None:
        return None
    opts = getattr(exchange, "options", None) or {}
    raw = opts.get("timeDifference")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def evaluate_skew(
    skew_ms: int,
    *,
    warn_ms: int = CLOCK_SKEW_WARN_MS,
    crit_ms: int = CLOCK_SKEW_CRIT_MS,
) -> SkewEvaluation:
    abs_ms = abs(int(skew_ms))
    if abs_ms >= crit_ms:
        level = "critical"
    elif abs_ms >= warn_ms:
        level = "warning"
    else:
        level = "ok"
    return SkewEvaluation(
        skew_ms=int(skew_ms),
        abs_skew_ms=abs_ms,
        level=level,
        warn_threshold_ms=warn_ms,
        crit_threshold_ms=crit_ms,
    )


def probe_host_ntp_sync(*, timeout_sec: float = 3.0) -> Optional[bool]:
    """
  Host NTP senkron durumu (best-effort).

  ``None`` = ölçülemedi (CI, izin yok, araç yok) — audit başarısız sayılmaz.
    """
    system = platform.system()
    try:
        if system == "Windows":
            proc = subprocess.run(
                ["w32tm", "/query", "/status"],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            if proc.returncode != 0:
                return None
            text = (proc.stdout or "") + (proc.stderr or "")
            if re.search(r"Leap Indicator:\s*3", text, re.I):
                return False
            if re.search(r"Source:\s*Local CMOS Clock", text, re.I):
                return False
            if re.search(r"Last Successful Sync Time", text, re.I):
                return True
            return None
        if system == "Linux":
            proc = subprocess.run(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            if proc.returncode != 0:
                return None
            val = (proc.stdout or "").strip().lower()
            if val in ("yes", "1", "true"):
                return True
            if val in ("no", "0", "false"):
                return False
            return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.debug("probe_host_ntp_sync skipped: %s", exc)
        return None
    return None


def check_candle_timestamps_monotonic(
    candles: Sequence[Mapping[str, Any]],
    *,
    ts_key: str = "timestamp",
) -> List[str]:
    """Mum zaman damgası azalmamalı — skew / birleştirme hataları için erken uyarı."""
    issues: List[str] = []
    prev: Optional[int] = None
    for i, c in enumerate(candles):
        raw = c.get(ts_key)
        if raw is None:
            continue
        try:
            ts = int(float(raw))
        except (TypeError, ValueError):
            issues.append(f"candle[{i}]: invalid {ts_key}={raw!r}")
            continue
        if prev is not None and ts <= prev:
            issues.append(f"candle[{i}]: non-monotonic {ts_key} {ts} <= {prev}")
        prev = ts
    return issues


def clock_skew_disclosure(
    *,
    last_skew_ms: Optional[int] = None,
    ntp_sync: Optional[bool] = None,
) -> Dict[str, Any]:
    ev = evaluate_skew(last_skew_ms or 0) if last_skew_ms is not None else None
    limitations = [
        "exchange_skew_via_ccxt_not_host_ntp_daemon",
        "host_ntp_probe_best_effort",
        "no_chrony_ntpd_management",
    ]
    if ntp_sync is False:
        limitations.append("host_ntp_not_synchronized")
    if ev and ev.level != "ok":
        limitations.append(f"exchange_skew_{ev.level}")

    return {
        "clock_skew_controlled": True,
        "institutional_ntp_claim_allowed": False,
        "metrics": [
            "bot_clock_skew_exchange_ms",
            "bot_clock_skew_abs_ms",
            "bot_host_ntp_synchronized",
        ],
        "alert_rules": ["BotClockSkewHigh", "BotHostNtpNotSynchronized"],
        "thresholds_ms": {
            "warn": CLOCK_SKEW_WARN_MS,
            "crit": CLOCK_SKEW_CRIT_MS,
        },
        "last_skew_ms": last_skew_ms,
        "last_skew_level": ev.level if ev else None,
        "host_ntp_synchronized": ntp_sync,
        "limitations": limitations,
        "disclaimer_tr": (
            "Borsa saat farkı ccxt timeDifference ile ölçülür ve Prometheus'a yazılır; "
            "host NTP yalnızca isteğe bağlı sondadır (chrony/w32tm işletimi bu repoda yok). "
            "Mum sırası bozulması mutabakat riski — monotonic kontrolü kullanın."
        ),
    }


def _source_module_path(root: Path, flat: str, impl_relative: str) -> Path:
    """PROMPT-04: kök shim varsa alt paketteki gerçek kaynak dosyayı oku."""
    impl = root / "super_otonom" / impl_relative
    if impl.is_file():
        return impl
    return root / "super_otonom" / flat


def validate_clock_skew_wiring(repo_root: Optional[Path] = None) -> List[str]:
    """Metrik, alarm ve compose işaretçisi — audit 6 sözleşmesi."""
    root = repo_root or _REPO
    issues: List[str] = []

    compose = root / "docker-compose.yml"
    if compose.is_file():
        text = compose.read_text(encoding="utf-8")
        if _COMPOSE_MARKER not in text.lower():
            issues.append(
                f"{compose.as_posix()}: must document clock skew limits (audit 6 marker)"
            )
    else:
        issues.append(f"{compose.as_posix()}: missing")

    alerts = root / "docker" / "prometheus" / "alerts.yml"
    if not alerts.is_file():
        issues.append(f"{alerts.as_posix()}: missing")
    else:
        at = alerts.read_text(encoding="utf-8")
        if "BotClockSkewHigh" not in at:
            issues.append(f"{alerts.as_posix()}: missing BotClockSkewHigh alert")
        if "bot_clock_skew_abs_ms" not in at:
            issues.append(f"{alerts.as_posix()}: must reference bot_clock_skew_abs_ms")

    metrics_py = _source_module_path(
        root, "metrics_exporter.py", "monitoring/metrics_exporter.py"
    )
    if metrics_py.is_file():
        mt = metrics_py.read_text(encoding="utf-8")
        for needle in ("clock_skew_abs_ms", "clock_skew_exchange_ms", "host_ntp_synchronized"):
            if needle not in mt:
                issues.append(f"{metrics_py.as_posix()}: missing metric {needle}")
    else:
        issues.append(f"{metrics_py.as_posix()}: missing")

    cfg = _source_module_path(root, "config.py", "core/config.py")
    if cfg.is_file() and "CLOCK_SKEW" not in cfg.read_text(encoding="utf-8"):
        issues.append(f"{cfg.as_posix()}: missing CLOCK_SKEW config block")

    return issues


def sample_disclosure_payload() -> Dict[str, Any]:
    """Test / fastrun için deterministik örnek."""
    return clock_skew_disclosure(last_skew_ms=42, ntp_sync=None)


def monotonic_check_age_ms(candles: Sequence[Mapping[str, Any]]) -> int:
    """Son mum yaşı (ms) — tazelik kontrolü için yardımcı."""
    if not candles:
        return -1
    last = candles[-1].get("timestamp")
    try:
        ts_ms = int(float(last))
    except (TypeError, ValueError):
        return -1
    return max(0, int(time.time() * 1000) - ts_ms)
