"""Faz 30 — rl_trading_agent (PPO proxy, çoklu uzman, koordinatör)."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

import super_otonom.rl_trading_agent as rl_mod
from super_otonom.rl_trading_agent import analyze_rl_agent, run_rl_agent_phase


def _closes_from_lr(lr: np.ndarray) -> list:
    return (100 * np.exp(np.cumsum(np.concatenate([[0], lr])))).tolist()


def test_rl_empty_blocks_quality() -> None:
    """1. Boş veri → BLOCK, data_health 0, QUALITY."""
    a: dict = {}
    r = analyze_rl_agent("BTC/USDT", {}, a, attach_to_analysis=True)

    assert r["trade_permission"] == "BLOCK"
    assert r["data_health"] == 0.0
    assert r["score_type"] == "QUALITY"
    assert r.get("empty_reason") == "no_market_data"


def test_rl_insufficient_bars() -> None:
    """2. Yetersiz bar (<36) → BLOCK, empty_reason."""
    np.random.seed(42)
    short = (100 * np.exp(np.cumsum(np.random.randn(30) * 0.004))).tolist()
    r = analyze_rl_agent("S/USDT", {"close": short}, {})

    assert r["trade_permission"] == "BLOCK"
    assert r.get("empty_reason") == "insufficient_bars"


def test_rl_strong_uptrend_buy_high_alpha() -> None:
    """3. Güçlü trend → coordinated BUY, alpha_score yüksek."""
    np.random.seed(42)
    lr = 0.028 + np.random.randn(79) * 0.0008
    r = analyze_rl_agent("UP/USDT", {"close": _closes_from_lr(lr)}, {}, attach_to_analysis=False)

    assert r["rl_agent"]["coordinated_action"] == "BUY"
    assert r["alpha_score"] >= 0.28


def test_rl_all_sell_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """4. Tüm oylar SELL → all_sell, BLOCK."""

    def _sell_ppo(self: object, s: np.ndarray) -> tuple:
        probs = np.array([0.88, 0.07, 0.05], dtype=float)
        logits = np.log(np.maximum(probs, 1e-9))
        ent = float(-np.sum(probs * np.log(probs + 1e-12)))
        return logits, probs, ent

    monkeypatch.setattr(rl_mod.TinyPPOPolicy, "forward", _sell_ppo)
    monkeypatch.setattr(rl_mod, "agent_trend", lambda ret: -1)
    monkeypatch.setattr(rl_mod, "agent_mean_revert", lambda ret: -1)
    monkeypatch.setattr(rl_mod, "agent_breakout", lambda ret: -1)

    np.random.seed(42)
    lr = np.random.randn(79) * 0.004
    r = analyze_rl_agent("SELL/USDT", {"close": _closes_from_lr(lr)}, {}, attach_to_analysis=False)

    assert r["rl_agent"]["all_sell"] is True
    assert r["trade_permission"] == "BLOCK"


def test_rl_ppo_uncertain_wait_low_alpha(monkeypatch: pytest.MonkeyPatch) -> None:
    """5. Düz PPO softmax → WAIT, düşük alpha (karşılaştırma için orijinal politika geri yüklenir)."""

    def _flat_ppo(self: object, s: np.ndarray) -> tuple:
        probs = np.array([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0], dtype=float)
        logits = np.log(np.maximum(probs, 1e-9))
        ent = float(-np.sum(probs * np.log(probs + 1e-12)))
        return logits, probs, ent

    _orig_forward = rl_mod.TinyPPOPolicy.forward
    monkeypatch.setattr(rl_mod.TinyPPOPolicy, "forward", _flat_ppo)

    np.random.seed(42)
    lr = np.random.randn(79) * 0.003
    r_flat = analyze_rl_agent("WT/USDT", {"close": _closes_from_lr(lr)}, {}, attach_to_analysis=False)

    monkeypatch.setattr(rl_mod.TinyPPOPolicy, "forward", _orig_forward)

    np.random.seed(42)
    lr_up = 0.028 + np.random.randn(79) * 0.0008
    r_buy = analyze_rl_agent("CMP/USDT", {"close": _closes_from_lr(lr_up)}, {}, attach_to_analysis=False)

    assert r_flat["rl_agent"]["coordinated_action"] == "WAIT"
    assert r_flat["rl_agent"]["ppo_policy_uncertain"] is True
    assert r_flat["alpha_score"] < r_buy["alpha_score"]


def test_rl_expert_disagreement_lowers_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """6. Üç uzman uyumsuz → disagreement_experts yüksek, confidence düşük."""

    def _split_experts(ret: np.ndarray) -> int:
        return 1

    def _split_mr(ret: np.ndarray) -> int:
        return -1

    def _split_bo(ret: np.ndarray) -> int:
        return 0

    monkeypatch.setattr(rl_mod, "agent_trend", _split_experts)
    monkeypatch.setattr(rl_mod, "agent_mean_revert", _split_mr)
    monkeypatch.setattr(rl_mod, "agent_breakout", _split_bo)

    np.random.seed(42)
    lr = np.random.randn(79) * 0.004
    r_split = analyze_rl_agent("DIS/USDT", {"close": _closes_from_lr(lr)}, {}, attach_to_analysis=False)

    monkeypatch.setattr(rl_mod, "agent_trend", lambda ret: 1)
    monkeypatch.setattr(rl_mod, "agent_mean_revert", lambda ret: 1)
    monkeypatch.setattr(rl_mod, "agent_breakout", lambda ret: 1)
    r_agree = analyze_rl_agent("AGR/USDT", {"close": _closes_from_lr(lr)}, {}, attach_to_analysis=False)

    assert r_split["rl_agent"]["disagreement_experts"] > r_agree["rl_agent"]["disagreement_experts"]
    assert r_split["confidence"] < r_agree["confidence"]


def test_rl_dict_core_fields() -> None:
    """7. rl dict: ppo_action, expert_votes, coordinated_action, disagreement_all."""
    np.random.seed(42)
    lr = np.random.randn(79) * 0.004
    r = analyze_rl_agent("K/USDT", {"close": _closes_from_lr(lr)}, {})

    rl = r["rl_agent"]
    assert "ppo_action" in rl and isinstance(rl["ppo_action"], int)
    assert "expert_votes" in rl and isinstance(rl["expert_votes"], dict)
    assert "coordinated_action" in rl
    assert "disagreement_all" in rl and isinstance(rl["disagreement_all"], float)


def test_rl_phase30_faz30_attached() -> None:
    """8. analysis['phase30'] ve analysis['faz30'] aynı payload."""
    a: dict = {}
    np.random.seed(42)
    lr = np.random.randn(79) * 0.004
    analyze_rl_agent("PH/USDT", {"close": _closes_from_lr(lr)}, a)

    assert "phase30" in a and "faz30" in a
    assert a["phase30"] is a["faz30"]
    assert a["phase30"]["phase"] == "30"


def test_run_rl_agent_phase_writes_analysis() -> None:
    """9. run_rl_agent_phase çalışır ve phase30 yazar."""
    a: dict = {}
    np.random.seed(42)
    lr = np.random.randn(79) * 0.004
    r = run_rl_agent_phase("RUN/USDT", {"close": _closes_from_lr(lr)}, a)

    assert r["source"] == "rl_trading_agent"
    assert a.get("phase30") is r


def test_rl_no_gym_torch_sb_imports() -> None:
    """10. gym / torch / stable_baselines import yok."""
    tree = ast.parse(Path(rl_mod.__file__).read_text(encoding="utf-8"))
    banned_roots = ("gym", "torch", "stable_baselines", "stable_baselines3", "gymnasium")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in banned_roots
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in banned_roots
