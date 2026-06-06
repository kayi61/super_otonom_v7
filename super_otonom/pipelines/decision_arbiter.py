"""P-2 — Tek, degismez karar onceligi merdiveni (decision arbiter).

PROBLEM (audit): 20 faz birbiriyle dovusuyor. Oncelik, cagri sirasi + dagininik
guard'larla (FAZ80 `_p0_preserved`, signal_pipeline force_all_close re-check,
autonomous_decision_core block_reason elif zinciri) EMERGENT olarak olusuyor. Sonuc:
- Yuksek oncelikli karar (FORCE_ALL_CLOSE) dusuk oncelikli FAZ80 tarafindan ezilebiliyor.
- Atif yanlis: force_close, manipulation (phase73) olarak raporlanabiliyor.
- "Hangi katman kazandi" tek yerden izlenemiyor.

COZUM: tek, DEGISMEZ oncelik merdiveni. Katmanlar oncelik sirasinda taranir; ilk
BLOKLAYAN (ALLOW olmayan) katman kazanir ve taramayi durdurur. Boylece:
  * Dusuk oncelikli katman, yuksek oncelikli BLOK kararini ASLA ezemez (kanit: ilk
    blokta return; sonraki katmanlara bakilmaz).
  * Atif her zaman dogru en-yuksek-oncelikli bloklayan katmana gider.
  * Tum gate'ler (1-5) ALLOW ise yalnizca o zaman execution-policy (6) aktuator karari
    verir — yani en dusuk katman hicbir gate'i gevsetemez.

Bu modul SAF ve ADDITIVE'dir: mevcut 20 fazi sokmez. Pipeline'a baglama (wiring) ayri,
riskli, cok-oturumluk adimdir; bu modul o baglamanin test edilmis temelidir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Mapping, Optional, Sequence


class Priority(IntEnum):
    """Degismez oncelik merdiveni — kucuk numara = yuksek oncelik."""

    EMERGENCY_STOP = 1   # risk.emergency_stop — tum sistemi durdur
    FORCE_CLOSE = 2      # force_all_close_requested — pozisyonlari kapat, yeni giris yok
    HARD_LIMIT = 3       # kill_switch / hard limit tracker — emir hizi / fiyat sicramasi
    PRE_TRADE_GATE = 4   # pre_trade_gate + likidite/giris kapilari (phase39)
    SIGNAL_QUALITY = 5   # sinyal kalitesi tabani (phase64) + AI validate_signal
    EXECUTION_POLICY = 6  # FAZ80 final_action — aktuator (yalnizca tum gate ALLOW ise)


# Gate katmanlari (yalnizca KISITLAYABILIR) vs aktuator (kararı uretir).
_GATE_PRIORITIES = (
    Priority.EMERGENCY_STOP,
    Priority.FORCE_CLOSE,
    Priority.HARD_LIMIT,
    Priority.PRE_TRADE_GATE,
    Priority.SIGNAL_QUALITY,
)

# Bir gate katmani icin "ALLOW" disindaki her sey bloklayicidir.
ALLOW = "ALLOW"


@dataclass(frozen=True)
class LayerVerdict:
    """Tek bir oncelik katmaninin bu tick'teki karari."""

    priority: Priority
    action: str            # gate: ALLOW|BLOCK|HALT|FLATTEN ; execution: ENTER|WAIT|HEDGE|EXIT|HALT
    reason: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.priority.name

    @property
    def is_blocking(self) -> bool:
        """Gate icin: ALLOW degilse bloklayici. Execution icin anlami yok (aktuator)."""
        return str(self.action).upper() != ALLOW


@dataclass(frozen=True)
class ArbiterDecision:
    """Tek, izlenebilir nihai karar + tam katman dokumu."""

    final_action: str          # kazanan katmanin action'i
    winning_layer: str         # ornek: "FORCE_CLOSE"
    winning_priority: int
    decision_reason: str       # tek izlenebilir sebep ("<LAYER>: <reason>")
    allowed: bool              # yalnizca execution-policy ENTER kazandiysa True
    decision_context: Dict[str, Any]  # her katmanin {action, reason, detail, won}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "final_action": self.final_action,
            "winning_layer": self.winning_layer,
            "winning_priority": self.winning_priority,
            "decision_reason": self.decision_reason,
            "allowed": self.allowed,
            "decision_context": self.decision_context,
        }


def _build_context(verdicts: Sequence[LayerVerdict], winner: Priority) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {}
    for v in sorted(verdicts, key=lambda x: int(x.priority)):
        ctx[v.name] = {
            "priority": int(v.priority),
            "action": str(v.action).upper(),
            "reason": v.reason,
            "detail": dict(v.detail),
            "won": v.priority == winner,
        }
    return ctx


def arbitrate(verdicts: Sequence[LayerVerdict]) -> ArbiterDecision:
    """Degismez oncelik merdiveni: ilk bloklayan gate kazanir; yoksa execution-policy.

    KANIT (low-cannot-override-high): gate'ler oncelik sirasinda taranir ve ilk
    bloklayanda DONULUR. Daha dusuk oncelikli (daha buyuk numara) hicbir katman bu
    karari goremez bile -> ezemez. Tum gate'ler ALLOW ise execution-policy karari
    gecerli olur; execution-policy bir gate'i gevsetemez cunku oraya ancak tum
    gate'ler ALLOW iken ulasilir.
    """
    by_prio: Dict[Priority, LayerVerdict] = {}
    for v in verdicts:
        # Ayni katman birden fazla verilirse en kisitlayicisini (ilk bloklayan) tut.
        if v.priority not in by_prio or (v.is_blocking and not by_prio[v.priority].is_blocking):
            by_prio[v.priority] = v

    # 1-5: gate'ler, oncelik sirasinda. Ilk bloklayan kazanir.
    for prio in _GATE_PRIORITIES:
        v = by_prio.get(prio)
        if v is not None and v.is_blocking:
            return ArbiterDecision(
                final_action=str(v.action).upper(),
                winning_layer=v.name,
                winning_priority=int(prio),
                decision_reason=f"{v.name}: {v.reason}" if v.reason else v.name,
                allowed=False,
                decision_context=_build_context(list(by_prio.values()), prio),
            )

    # Tum gate'ler ALLOW -> execution-policy (6) aktuator.
    exec_v = by_prio.get(Priority.EXECUTION_POLICY)
    if exec_v is None:
        # Execution katmani verilmediyse: gate'ler temiz ama eylem yok -> WAIT.
        neutral = LayerVerdict(Priority.EXECUTION_POLICY, "WAIT", "no_execution_layer")
        all_v = list(by_prio.values()) + [neutral]
        return ArbiterDecision(
            final_action="WAIT",
            winning_layer=Priority.EXECUTION_POLICY.name,
            winning_priority=int(Priority.EXECUTION_POLICY),
            decision_reason="EXECUTION_POLICY: no_execution_layer",
            allowed=False,
            decision_context=_build_context(all_v, Priority.EXECUTION_POLICY),
        )

    action = str(exec_v.action).upper()
    return ArbiterDecision(
        final_action=action,
        winning_layer=exec_v.name,
        winning_priority=int(Priority.EXECUTION_POLICY),
        decision_reason=f"{exec_v.name}: {exec_v.reason}" if exec_v.reason else exec_v.name,
        allowed=(action == "ENTER"),
        decision_context=_build_context(list(by_prio.values()), Priority.EXECUTION_POLICY),
    )


# ── Mevcut faz dict'lerinden verdict uretici (gelecekteki wiring icin adapter) ──


def _perm(phase: Any) -> str:
    """phase dict/dataclass -> trade_permission (ALLOW/BLOCK/HALT)."""
    if phase is None:
        return ALLOW
    if isinstance(phase, Mapping):
        return str(phase.get("trade_permission", ALLOW)).upper()
    return str(getattr(phase, "trade_permission", ALLOW)).upper()


def arbitrate_from_phases(
    *,
    emergency_stop: bool,
    force_all_close: bool,
    has_open_position: bool,
    hard_limit_blocked: bool = False,
    hard_limit_reason: str = "",
    phase39: Any = None,
    phase64: Any = None,
    execution_action: str = "WAIT",
    execution_reason: str = "",
    extra: Optional[Mapping[str, Any]] = None,
) -> ArbiterDecision:
    """Mevcut pipeline sinyallerini degismez merdivene cevirir (shadow/wiring adapteri).

    Bu fonksiyon, execution_pipeline'da elde edilen mevcut faz/bayraklarla CAGRILABILIR;
    boylece ayni tick icin tek izlenebilir karar uretilir. Davranisi degistirmeden once
    shadow modda (yalnizca observability) kullanilabilir.
    """
    verdicts: List[LayerVerdict] = []

    verdicts.append(
        LayerVerdict(
            Priority.EMERGENCY_STOP,
            "HALT" if emergency_stop else ALLOW,
            "risk.emergency_stop" if emergency_stop else "",
        )
    )
    verdicts.append(
        LayerVerdict(
            Priority.FORCE_CLOSE,
            ("FLATTEN" if has_open_position else "HALT") if force_all_close else ALLOW,
            "FORCE_ALL_CLOSE" if force_all_close else "",
        )
    )
    verdicts.append(
        LayerVerdict(
            Priority.HARD_LIMIT,
            "HALT" if hard_limit_blocked else ALLOW,
            hard_limit_reason or ("hard_limit" if hard_limit_blocked else ""),
        )
    )
    p39 = _perm(phase39)
    verdicts.append(
        LayerVerdict(
            Priority.PRE_TRADE_GATE,
            p39 if p39 != ALLOW else ALLOW,
            "pre_trade/liquidity_gate" if p39 != ALLOW else "",
            detail=dict(phase39) if isinstance(phase39, Mapping) else {},
        )
    )
    p64 = _perm(phase64)
    verdicts.append(
        LayerVerdict(
            Priority.SIGNAL_QUALITY,
            p64 if p64 != ALLOW else ALLOW,
            "signal_quality_gate" if p64 != ALLOW else "",
            detail=dict(phase64) if isinstance(phase64, Mapping) else {},
        )
    )
    verdicts.append(
        LayerVerdict(
            Priority.EXECUTION_POLICY,
            str(execution_action).upper(),
            execution_reason or "faz80",
            detail=dict(extra) if extra else {},
        )
    )
    return arbitrate(verdicts)


def tick_decision_context(
    *,
    emergency_stop: bool,
    force_all_close: bool,
    has_open_position: bool,
    analysis: Optional[Mapping[str, Any]],
    execution_action: str,
    execution_reason: str = "",
    hard_limit_blocked: bool = False,
    hard_limit_reason: str = "",
) -> Dict[str, Any]:
    """Bir tick'in tek izlenebilir kararini mevcut analiz/bayraklardan uretir.

    SHADOW kullanim: execution_pipeline bunu cagirir ve sonucu yalnizca
    ``out["priority_arbiter"]``'a yazar — final_signal/davranis DEGISMEZ. Boylece
    "her tick'te tek izlenebilir karar" (P-2 kabul) canli yolda gerceklesir ve
    legacy karar ile arbiter karari arasindaki uyusmazliklar (kalan oncelik
    bug'lari) ``legacy_mismatch`` ile yakalanir.
    """
    a = analysis or {}
    decision = arbitrate_from_phases(
        emergency_stop=emergency_stop,
        force_all_close=force_all_close,
        has_open_position=has_open_position,
        hard_limit_blocked=hard_limit_blocked,
        hard_limit_reason=hard_limit_reason,
        phase39=a.get("phase39") or a.get("faz39"),
        phase64=a.get("phase64") or a.get("faz64"),
        execution_action=execution_action,
        execution_reason=execution_reason,
    )
    payload = decision.to_dict()
    # Legacy uyusmazlik: arbiter girise IZIN VERMIYOR ama execution ENTER istedi mi?
    payload["legacy_mismatch"] = bool(
        (not decision.allowed) and str(execution_action).upper() == "ENTER"
    )
    return payload
