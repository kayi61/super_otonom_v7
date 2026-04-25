"""CorrelationManager — getiri ve korelasyon."""
from __future__ import annotations

from super_otonom.correlation_manager import CorrelationManager


def test_empty_returns_no_pairs() -> None:
    cm = CorrelationManager(threshold=0.5, min_periods=5)
    assert cm.get_correlated_pairs() == []


def test_adjust_risk_no_positions_is_one() -> None:
    cm = CorrelationManager()
    assert cm.adjust_risk_exposure("BTC/USDT", [], None) == 1.0


def test_highly_correlated_pair_detected() -> None:
    """İki seri aynı yönde hareket → yüksek korelasyon."""
    cm = CorrelationManager(threshold=0.7, min_periods=8)
    for i in range(25):
        b = 200.0 + i * 0.5
        cm.update_returns("ETH/USDT", b)
        cm.update_returns("SOL/USDT", 50.0 + i * 0.5)
    pairs = cm.get_correlated_pairs()
    assert len(pairs) >= 1
    any_pair = pairs[0]
    assert "ETH/USDT" in any_pair and "SOL/USDT" in any_pair


def test_summary_returns_dict() -> None:
    cm = CorrelationManager()
    for i in range(5):
        cm.update_returns("A", 100.0 + i)
    summ = cm.summary()
    assert isinstance(summ, dict)
    assert summ["tracked_symbols"] == 1
