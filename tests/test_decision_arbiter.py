"""P-2 kabul testi: degismez oncelik merdiveni — dusuk oncelik yuksegi ASLA ezemez.

Eksiksiz kombinatoryal matris (240 vaka) + gercek bug senaryolari (force-close vs FAZ80).
"""
from __future__ import annotations

import itertools

from super_otonom.pipelines.decision_arbiter import (
    ALLOW,
    ArbiterDecision,
    LayerVerdict,
    Priority,
    arbitrate,
    arbitrate_from_phases,
)

# Her gate katmaninin test edilecek action secenekleri (ALLOW + bloklayicilar).
_GATE_OPTIONS = {
    Priority.EMERGENCY_STOP: [ALLOW, "HALT"],
    Priority.FORCE_CLOSE: [ALLOW, "FLATTEN", "HALT"],
    Priority.HARD_LIMIT: [ALLOW, "HALT"],
    Priority.PRE_TRADE_GATE: [ALLOW, "BLOCK"],
    Priority.SIGNAL_QUALITY: [ALLOW, "BLOCK"],
}
_EXEC_OPTIONS = ["ENTER", "WAIT", "HEDGE", "EXIT", "HALT"]
_GATE_PRIOS = list(_GATE_OPTIONS)


def _expected_winner(gate_actions, exec_action):
    """Beklenen: oncelik sirasinda ilk bloklayan gate; yoksa execution-policy."""
    for prio in sorted(gate_actions, key=int):
        if gate_actions[prio] != ALLOW:
            return prio, gate_actions[prio].upper()
    return Priority.EXECUTION_POLICY, exec_action.upper()


# ── 1) Eksiksiz kombinatoryal matris (2*3*2*2*2 * 5 = 240 vaka) ─────────────


def test_full_priority_matrix():
    combos = itertools.product(*[_GATE_OPTIONS[p] for p in _GATE_PRIOS])
    n_cases = 0
    for combo in combos:
        gate_actions = dict(zip(_GATE_PRIOS, combo))
        for exec_action in _EXEC_OPTIONS:
            verdicts = [LayerVerdict(p, gate_actions[p]) for p in _GATE_PRIOS]
            verdicts.append(LayerVerdict(Priority.EXECUTION_POLICY, exec_action))
            d = arbitrate(verdicts)

            exp_prio, exp_action = _expected_winner(gate_actions, exec_action)
            assert d.winning_priority == int(exp_prio), (
                f"{gate_actions} exec={exec_action}: kazanan {d.winning_priority} != {int(exp_prio)}"
            )
            assert d.final_action == exp_action
            # Tek izlenebilir karar + 6 katmanin tam dokumu
            assert d.decision_reason
            assert len(d.decision_context) == 6
            assert d.decision_context[exp_prio.name]["won"] is True
            # TAM OLARAK bir kazanan
            assert sum(1 for c in d.decision_context.values() if c["won"]) == 1
            # allowed yalnizca execution-policy ENTER'a ulasildiginda
            assert d.allowed == (
                exp_prio == Priority.EXECUTION_POLICY and exec_action == "ENTER"
            )
            n_cases += 1
    assert n_cases == 240


# ── 2) Dusuk oncelik yuksegi ezemez — dogrudan kanit ────────────────────────


def test_execution_enter_cannot_override_emergency():
    d = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, "HALT", "emergency"),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER", "faz80"),
    ])
    assert d.winning_layer == "EMERGENCY_STOP"
    assert d.final_action == "HALT"
    assert d.allowed is False


def test_faz80_enter_cannot_override_force_close():
    # TAM OLARAK kullanicinin bildirdigi bug: FAZ80 FORCE_ALL_CLOSE'u eziyordu.
    d = arbitrate([
        LayerVerdict(Priority.FORCE_CLOSE, "FLATTEN", "FORCE_ALL_CLOSE"),
        LayerVerdict(Priority.SIGNAL_QUALITY, ALLOW),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER", "faz80"),
    ])
    assert d.winning_layer == "FORCE_CLOSE"
    assert d.final_action == "FLATTEN"
    assert "FORCE_ALL_CLOSE" in d.decision_reason
    assert d.allowed is False


def test_higher_priority_block_wins_over_lower_block():
    # force_close (2) + signal_quality (5) ayni anda bloklarsa force_close kazanmali.
    d = arbitrate([
        LayerVerdict(Priority.FORCE_CLOSE, "HALT", "FORCE_ALL_CLOSE"),
        LayerVerdict(Priority.SIGNAL_QUALITY, "BLOCK", "low_quality"),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER"),
    ])
    assert d.winning_priority == int(Priority.FORCE_CLOSE)
    # signal_quality bloku context'te gorunur ama KAZANAMAZ
    assert d.decision_context["SIGNAL_QUALITY"]["won"] is False


def test_emergency_beats_force_close():
    d = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, "HALT", "emergency"),
        LayerVerdict(Priority.FORCE_CLOSE, "FLATTEN", "FORCE_ALL_CLOSE"),
    ])
    assert d.winning_layer == "EMERGENCY_STOP"


def test_lower_gate_blocks_when_higher_allow():
    # emergency/force/hard ALLOW, pre_trade BLOCK -> pre_trade kazanir.
    d = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, ALLOW),
        LayerVerdict(Priority.FORCE_CLOSE, ALLOW),
        LayerVerdict(Priority.HARD_LIMIT, ALLOW),
        LayerVerdict(Priority.PRE_TRADE_GATE, "BLOCK", "pre_trade"),
        LayerVerdict(Priority.SIGNAL_QUALITY, ALLOW),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER"),
    ])
    assert d.winning_layer == "PRE_TRADE_GATE"
    assert d.allowed is False


def test_all_gates_allow_execution_enter_passes():
    d = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, ALLOW),
        LayerVerdict(Priority.FORCE_CLOSE, ALLOW),
        LayerVerdict(Priority.HARD_LIMIT, ALLOW),
        LayerVerdict(Priority.PRE_TRADE_GATE, ALLOW),
        LayerVerdict(Priority.SIGNAL_QUALITY, ALLOW),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER", "faz80"),
    ])
    assert d.winning_layer == "EXECUTION_POLICY"
    assert d.final_action == "ENTER"
    assert d.allowed is True


# ── 3) Monotonluk: yuksek blok eklemek kazananı yukseltir; dusuk blok degistirmez ──


def test_adding_lower_block_never_changes_winner_when_higher_blocks():
    base = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, "HALT", "emergency"),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER"),
    ])
    with_lower = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, "HALT", "emergency"),
        LayerVerdict(Priority.PRE_TRADE_GATE, "BLOCK", "x"),
        LayerVerdict(Priority.SIGNAL_QUALITY, "BLOCK", "y"),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER"),
    ])
    assert base.winning_layer == with_lower.winning_layer == "EMERGENCY_STOP"


def test_duplicate_verdict_keeps_most_restrictive():
    d = arbitrate([
        LayerVerdict(Priority.PRE_TRADE_GATE, ALLOW),
        LayerVerdict(Priority.PRE_TRADE_GATE, "BLOCK", "second_blocks"),
        LayerVerdict(Priority.EXECUTION_POLICY, "ENTER"),
    ])
    assert d.winning_layer == "PRE_TRADE_GATE"


def test_no_execution_layer_defaults_wait():
    d = arbitrate([
        LayerVerdict(Priority.EMERGENCY_STOP, ALLOW),
        LayerVerdict(Priority.PRE_TRADE_GATE, ALLOW),
    ])
    assert d.final_action == "WAIT"
    assert d.allowed is False


# ── 4) Adapter: gercek pipeline sinyallerinden (wiring temeli) ───────────────


def test_adapter_force_close_beats_faz80_enter():
    # Gercek bug senaryosu adapter uzerinden.
    d = arbitrate_from_phases(
        emergency_stop=False,
        force_all_close=True,
        has_open_position=True,
        execution_action="ENTER",
        execution_reason="faz80:ENTER",
    )
    assert d.winning_layer == "FORCE_CLOSE"
    assert d.final_action == "FLATTEN"
    assert d.allowed is False
    assert "FORCE_ALL_CLOSE" in d.decision_reason


def test_adapter_force_close_no_open_position_halts_new():
    d = arbitrate_from_phases(
        emergency_stop=False,
        force_all_close=True,
        has_open_position=False,
        execution_action="ENTER",
    )
    assert d.winning_layer == "FORCE_CLOSE"
    assert d.final_action == "HALT"  # acik pozisyon yok -> yeni giris yok


def test_adapter_emergency_beats_everything():
    d = arbitrate_from_phases(
        emergency_stop=True,
        force_all_close=True,
        has_open_position=True,
        hard_limit_blocked=True,
        execution_action="ENTER",
    )
    assert d.winning_layer == "EMERGENCY_STOP"


def test_adapter_signal_quality_block():
    d = arbitrate_from_phases(
        emergency_stop=False,
        force_all_close=False,
        has_open_position=False,
        phase64={"trade_permission": "BLOCK"},
        execution_action="ENTER",
    )
    assert d.winning_layer == "SIGNAL_QUALITY"
    assert d.allowed is False


def test_adapter_all_clear_enter_allowed():
    d = arbitrate_from_phases(
        emergency_stop=False,
        force_all_close=False,
        has_open_position=False,
        phase39={"trade_permission": "ALLOW"},
        phase64={"trade_permission": "ALLOW"},
        execution_action="ENTER",
        execution_reason="faz80:ENTER",
    )
    assert d.winning_layer == "EXECUTION_POLICY"
    assert d.final_action == "ENTER"
    assert d.allowed is True


def test_adapter_pre_trade_gate_from_phase39():
    d = arbitrate_from_phases(
        emergency_stop=False,
        force_all_close=False,
        has_open_position=False,
        phase39={"trade_permission": "BLOCK"},
        phase64={"trade_permission": "BLOCK"},  # daha dusuk oncelik
        execution_action="ENTER",
    )
    # phase39 (pre-trade, 4) phase64 (signal-quality, 5)'ten once kazanir
    assert d.winning_layer == "PRE_TRADE_GATE"


def test_decision_is_serializable():
    d = arbitrate_from_phases(
        emergency_stop=False, force_all_close=False, has_open_position=False,
        execution_action="WAIT",
    )
    assert isinstance(d, ArbiterDecision)
    payload = d.to_dict()
    assert payload["winning_layer"] and "decision_context" in payload
