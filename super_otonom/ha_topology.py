"""
Dağıtım topolojisi — tek-host / tek bot instance (audit madde 5).

Docker Compose varsayılanı: bir ``bot`` servisi, sabit ``container_name``,
active-passive veya çoklu AZ yok. Kurumsal HA iddiası bu topoloji ile uyumlu değildir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_COMPOSE = _REPO / "docker-compose.yml"

_COMPOSE_HA_MARKER = "audit 5"
_BOT_SERVICE_RE = re.compile(
    r"^  bot:\s*$.*?(?=^  [a-zA-Z0-9_]+:\s*$|\Z)",
    re.MULTILINE | re.DOTALL,
)
_REPLICAS_RE = re.compile(r"^\s+replicas:\s*(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class ComposeTopology:
    compose_path: str
    bot_replicas: int
    bot_fixed_container_name: bool
    bot_deploy_mode: Optional[str]
    supporting_services: List[str] = field(default_factory=list)

    @property
    def single_bot_instance(self) -> bool:
        return self.bot_replicas <= 1

    @property
    def institutional_ha_claim_allowed(self) -> bool:
        return False


def _extract_service_names(text: str) -> List[str]:
    return re.findall(r"^  ([a-zA-Z0-9_]+):\s*$", text, re.MULTILINE)


def inspect_docker_compose(path: str | Path | None = None) -> ComposeTopology:
    """``docker-compose.yml`` içinden bot örneği ve destek servisleri."""
    p = Path(path) if path is not None else _DEFAULT_COMPOSE
    text = p.read_text(encoding="utf-8")
    m = _BOT_SERVICE_RE.search(text)
    block = m.group(0) if m else ""
    replicas = 1
    for rm in _REPLICAS_RE.finditer(block):
        replicas = int(rm.group(1))
    deploy_mode = None
    dm = re.search(r"^\s+mode:\s*(\S+)\s*$", block, re.MULTILINE)
    if dm:
        deploy_mode = dm.group(1)
    services = _extract_service_names(text)
    support = [s for s in services if s != "bot"]
    return ComposeTopology(
        compose_path=p.as_posix(),
        bot_replicas=replicas,
        bot_fixed_container_name="container_name:" in block and "super_otonom_bot" in block,
        bot_deploy_mode=deploy_mode,
        supporting_services=support,
    )


def ha_disclosure(
    *,
    topology: Optional[ComposeTopology] = None,
) -> Dict[str, Any]:
    """Rapor / JSON için açık sınırlar — varsayılan: kurumsal HA iddiası yok."""
    topo = topology or inspect_docker_compose()
    limitations: List[str] = [
        "single_host_docker_compose",
        "single_bot_trading_instance",
        "no_active_passive_failover",
        "no_multi_az",
    ]
    if topo.bot_replicas > 1:
        limitations.append("bot_replicas_gt_1_detected")
    if not topo.bot_fixed_container_name:
        limitations.append("bot_container_name_not_fixed")

    return {
        "ha_bias_controlled": True,
        "institutional_ha_claim_allowed": False,
        "topology": {
            "compose_path": topo.compose_path,
            "bot_replicas": topo.bot_replicas,
            "bot_fixed_container_name": topo.bot_fixed_container_name,
            "bot_deploy_mode": topo.bot_deploy_mode,
            "supporting_service_count": len(topo.supporting_services),
            "supporting_services": list(topo.supporting_services),
        },
        "limitations": limitations,
        "disclaimer_tr": (
            "Bu stack tek makinede Docker Compose ile çalışır; yalnızca bir bot işlem "
            "örneği vardır (active-passive veya çoklu availability zone yok). "
            "Yeniden başlatma ve yedekleme (DR_BCP) süreklilik sağlar; bu kurumsal HA değildir."
        ),
    }


def validate_compose_ha_contract(path: str | Path | None = None) -> List[str]:
    """Topoloji + compose dosyasında zorunlu audit işaretçisi."""
    issues: List[str] = []
    p = Path(path) if path is not None else _DEFAULT_COMPOSE
    if not p.is_file():
        return [f"{p.as_posix()}: docker-compose.yml missing"]
    text = p.read_text(encoding="utf-8")
    if _COMPOSE_HA_MARKER not in text.lower():
        issues.append(
            f"{p.as_posix()}: must document single-host HA limit (audit 5 marker in header)"
        )
    topo = inspect_docker_compose(p)
    if topo.bot_replicas > 1:
        issues.append(
            f"{p.as_posix()}: bot replicas={topo.bot_replicas} — "
            "multi-instance HA not supported; use replicas: 1"
        )
    return issues
