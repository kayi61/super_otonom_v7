from __future__ import annotations

"""
Ops metrikleri — MetricsExporter'a gecikmeli baglama (Vault config import sirasi).
"""

from typing import Any, Optional

_metrics: Optional[Any] = None


def bind_metrics(exporter: Any) -> None:
    global _metrics
    _metrics = exporter


def inc_order_error(err_type: str = "order") -> None:
    if _metrics is not None:
        _metrics.inc_order_error(err_type)


def inc_ws_reconnect() -> None:
    if _metrics is not None:
        _metrics.inc_ws_reconnect()


def set_dependency_up(name: str, up: bool) -> None:
    if _metrics is not None:
        _metrics.set_dependency_up(name, up)


def record_clock_skew(exchange_id: str, skew_ms: int) -> None:
    if _metrics is not None:
        _metrics.record_clock_skew(exchange_id, skew_ms)


def record_host_ntp(synced: Optional[bool]) -> None:
    if _metrics is not None:
        _metrics.record_host_ntp(synced)


def refresh_dependencies() -> None:
    """Vault + Timescale + host NTP sondası → Prometheus gauge."""
    try:
        from super_otonom.config import _vault_bridge

        set_dependency_up("vault", bool(_vault_bridge().status().get("available")))
    except Exception:
        set_dependency_up("vault", False)

    try:
        from super_otonom.infra.timescale_bridge import probe_timescale_available

        set_dependency_up("timescale", probe_timescale_available())
    except Exception:
        set_dependency_up("timescale", False)

    try:
        from super_otonom.clock_skew import probe_host_ntp_sync

        record_host_ntp(probe_host_ntp_sync())
    except Exception:
        record_host_ntp(None)
