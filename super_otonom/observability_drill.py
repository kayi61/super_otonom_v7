"""
PROMPT 3 — Gozlemlenebilirlik uctan uca drill (Bant 4).

Stack ayakta olsa bile alarm teslimi (Telegram koprusu) dogrulanmadan PASS sayilmaz.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_DOC = _REPO / "docs" / "OBSERVABILITY_DRILL.md"

_PROM_URL = os.getenv("OBS_DRILL_PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
_METRICS_URL = os.getenv("OBS_DRILL_METRICS_URL", "http://127.0.0.1:8000/metrics").rstrip("/")
_BRIDGE_URL = os.getenv("OBS_DRILL_BRIDGE_URL", "http://127.0.0.1:8081").rstrip("/")
_AM_URL = os.getenv("OBS_DRILL_ALERTMANAGER_URL", "http://127.0.0.1:9093").rstrip("/")
_GRAFANA_OPS = os.getenv(
    "OBS_DRILL_GRAFANA_DASH",
    "http://127.0.0.1:3000/d/super-otonom-ops",
)

_REQUIRED_METRICS = (
    "bot_dependency_up",
    "bot_order_errors_total",
    "bot_circuit_breaker_open",
)


@dataclass
class StepResult:
    adim: str
    sonuc: str  # PASS | FAIL | WARN
    not_: str


def _http_get(url: str, timeout: float = 12.0) -> Tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), body
    except Exception as exc:
        return 0, str(exc)


def _http_post_json(url: str, payload: Dict[str, Any], timeout: float = 15.0) -> Tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), body
    except Exception as exc:
        return 0, str(exc)


def _test_alertmanager_payload() -> Dict[str, Any]:
    return {
        "receiver": "webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "ObservabilityDrillTest",
                    "severity": "warning",
                    "instance": "drill",
                },
                "annotations": {
                    "summary": "super_otonom observability drill (kasitli test)",
                    "description": "Bu mesaj drill scriptinden gelir; gercek olay degil.",
                },
                "startsAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        ],
        "groupLabels": {"alertname": "ObservabilityDrillTest"},
        "commonLabels": {"alertname": "ObservabilityDrillTest"},
        "commonAnnotations": {},
        "externalURL": "http://prometheus:9090",
        "version": "4",
        "groupKey": "observability-drill",
    }


def run_drill(*, write_doc: bool = True, doc_path: Optional[Path] = None) -> int:
    doc_path = doc_path or _DEFAULT_DOC
    verified_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    machine = platform.node() or "unknown"
    rows: List[StepResult] = []

    code, body = _http_get(f"{_PROM_URL}/-/healthy")
    rows.append(
        StepResult(
            "Prometheus saglik",
            "PASS" if code == 200 else "FAIL",
            f"HTTP {code}" if code else body[:120],
        )
    )

    code, body = _http_get(f"{_PROM_URL}/api/v1/rules")
    n_groups = 0
    if code == 200:
        try:
            n_groups = len(json.loads(body).get("data", {}).get("groups", []))
        except json.JSONDecodeError:
            n_groups = 0
    rows.append(
        StepResult(
            "Prometheus alert kurallari",
            "PASS" if code == 200 and n_groups > 0 else "FAIL",
            f"groups={n_groups}",
        )
    )

    code, body = _http_get(_METRICS_URL)
    missing = [m for m in _REQUIRED_METRICS if m not in body]
    rows.append(
        StepResult(
            "Bot /metrics (Prometheus scrape hedefi)",
            "PASS" if code == 200 and not missing else "FAIL",
            f"HTTP {code}; eksik: {', '.join(missing) if missing else 'yok'}",
        )
    )

    code, _ = _http_get(f"{_BRIDGE_URL}/health")
    rows.append(
        StepResult(
            "alert_telegram /health",
            "PASS" if code == 200 else "FAIL",
            f"HTTP {code}",
        )
    )

    post_code, post_body = _http_post_json(
        f"{_BRIDGE_URL}/alert",
        _test_alertmanager_payload(),
    )
    if post_code == 200:
        delivery = "PASS"
        delivery_note = "Telegram gonderimi OK (HTTP 200)"
    elif post_code == 202:
        delivery = "FAIL"
        delivery_note = (
            "Telegram kimligi yok veya gonderilemedi (HTTP 202). "
            "data/local/telegram.env veya Vault telegram + setup_telegram_alerts"
        )
    else:
        delivery = "FAIL"
        delivery_note = f"HTTP {post_code} {post_body[:80]}"
    rows.append(
        StepResult(
            "Alarm teslimi: kasitli test -> Telegram koprusu",
            delivery,
            delivery_note,
        )
    )

    code, _ = _http_get(f"{_AM_URL}/-/healthy")
    rows.append(
        StepResult(
            "Alertmanager saglik (referans)",
            "PASS" if code == 200 else "WARN",
            f"HTTP {code}",
        )
    )

    blockers = [r for r in rows if r.sonuc == "FAIL"]
    overall = "PASS" if not blockers else "FAIL"

    lines = [
        "# Observability drill (PROMPT 3 — Bant 4)",
        "",
        f"**Son drill:** {verified_at} | **Makine:** `{machine}` | **Sonuc:** **{overall}**",
        "",
        "## URL / portlar (yerel, docker-compose.dev.yml)",
        "",
        "| Bileşen | URL |",
        "|---------|-----|",
        f"| Prometheus | `{_PROM_URL}` |",
        f"| Prometheus alerts UI | `{_PROM_URL}/alerts` |",
        f"| Alertmanager | `{_AM_URL}` |",
        f"| Bot metrics | `{_METRICS_URL}` |",
        f"| Telegram köprüsü | `{_BRIDGE_URL}/health` , POST `{_BRIDGE_URL}/alert` |",
        f"| Grafana Ops | `{_GRAFANA_OPS}` |",
        "",
        "## Hizli calistirma",
        "",
        "```powershell",
        "Set-Location -LiteralPath '<repo_koku>'",
        ".\\scripts\\fastrun_observability.cmd",
        "# yalnizca dogrulama (stack zaten ayaktaysa):",
        "python -m super_otonom.observability_drill",
        "```",
        "",
        "**Onkosul:** Docker; istege bagli `data\\local\\telegram.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).",
        "",
        "## Drill adimlari (otomatik)",
        "",
        "| Adim | Sonuc | Not |",
        "|------|--------|-----|",
    ]
    for r in rows:
        note = (r.not_ or "").replace("|", "\\|")
        lines.append(f"| {r.adim} | **{r.sonuc}** | {note} |")

    lines.extend(
        [
            "",
            "## Kabul kriteri",
            "",
            "- Stack ayakta **yetmez**; **kasitli test alert** Telegram koprusunden **HTTP 200** donmeli.",
            "- Bot metrikleri `8000/metrics` uzerinde gorunur olmali.",
            "- Prometheus'ta en az bir alert rule grubu yuklu olmali.",
            "",
            "## Elle tam zincir (Alertmanager uzerinden, yavas)",
            "",
            "1. Prometheus'ta kural tetiklenmesini bekle veya metrikleri kontrol et.",
            "2. `http://127.0.0.1:9093/#/alerts` — alert gorunur mu?",
            "3. Telegram'da mesaj geldi mi?",
            "",
            "Hizli yol: drill scripti dogrudan `POST /alert` ile kopruyu test eder.",
            "",
        ]
    )

    if write_doc:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"observability_drill: {overall}")
    for r in rows:
        print(f"  [{r.sonuc}] {r.adim}: {r.not_}")
    if write_doc:
        print(f"Yazildi: {doc_path}")

    return 0 if overall == "PASS" else 1


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Observability uctan uca drill")
    p.add_argument("--no-write-doc", action="store_true")
    p.add_argument("--doc", type=Path, default=_DEFAULT_DOC)
    args = p.parse_args(argv)
    return run_drill(write_doc=not args.no_write_doc, doc_path=args.doc)


if __name__ == "__main__":
    raise SystemExit(main())
