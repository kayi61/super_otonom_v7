"""
Açık edge case testleri: OMEGA, merge_entry_notional, HardLimitTracker.

Eskiden: 2×5×2=20 + 10×6=60 + 5×7×2=70 kombinatoryal case (assert oreg, assert n >= 0).
Şimdi: her koşul için tek, anlamlı, beklenen çıktıyı doğrulayan test.
"""
from __future__ import annotations

import pytest
from super_otonom.kill_switch import HardLimitTracker
from super_otonom.omega_regime import compute_omega_regime
from super_otonom.pre_trade_gate import merge_entry_notional

# ─── compute_omega_regime — kenar koşullar ───────────────────────────────────


def test_omega_empty_analysis_defaults() -> None:
    """Boş analiz: regime=NOISY, hurst=0.5, vol=0.02 → RANGING."""
    oreg, _, _, _, log = compute_omega_regime({}, base_quality=50)
    assert oreg == "RANGING"
    assert "[OMEGA-AI]" in log


def test_omega_unknown_regime_handled_gracefully() -> None:
    """Bilinmeyen rejim → çökmemeli, geçerli çıktı üretmeli."""
    oreg, _, _, adj, log = compute_omega_regime(
        {"regime": "UNKNOWN", "hurst": 0.52, "volatility": 0.02}, base_quality=60
    )
    assert oreg in ("TRENDING", "RANGING", "CRASH_RISK")
    assert 0 <= adj <= 100
    assert "[OMEGA-AI]" in log


def test_omega_low_quality_range_caps_size_factor() -> None:
    """base_quality 40–52 → CRASH_RISK dışında sf ≤ 0.45."""
    _, _, sf, _, _ = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.60, "volatility": 0.02}, base_quality=45
    )
    assert sf <= 0.45


def test_omega_high_quality_trending_boosts_sf() -> None:
    """base_quality ≥ 90, TRENDING → sf ≥ 1.0."""
    _, _, sf, _, _ = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.65, "volatility": 0.02}, base_quality=95
    )
    assert sf >= 1.0


def test_omega_flash_crash_overrides_to_crash_risk() -> None:
    oreg, qm, sf, _, _ = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.80, "flash_crash": True, "volatility": 0.01},
        base_quality=88,
    )
    assert oreg == "CRASH_RISK"
    assert sf == pytest.approx(0.35)


def test_omega_base_quality_zero_gives_zero_adj() -> None:
    _, _, _, adj, _ = compute_omega_regime(
        {"regime": "TRENDING", "hurst": 0.65, "volatility": 0.02}, base_quality=0
    )
    assert adj == 0


# ─── merge_entry_notional — kenar koşullar ───────────────────────────────────


def test_merge_negative_technical_clamped_to_zero() -> None:
    notional, _, _ = merge_entry_notional(-100.0, None)
    assert notional == pytest.approx(0.0)


def test_merge_both_zero() -> None:
    notional, _, blocked = merge_entry_notional(0.0, 0.0)
    assert notional == pytest.approx(0.0)
    assert blocked == "ob_safe_size_zero"


def test_merge_negative_ob_blocks_entry() -> None:
    notional, source, blocked = merge_entry_notional(100.0, -50.0)
    assert notional == pytest.approx(0.0)
    assert blocked == "ob_safe_size_zero"


def test_merge_ob_exactly_equal_to_tech() -> None:
    notional, source, blocked = merge_entry_notional(100.0, 100.0)
    assert notional == pytest.approx(100.0)
    assert source == "min_technical_ob_safe"
    assert blocked == ""


# ─── HardLimitTracker — kenar koşullar ───────────────────────────────────────


def test_hard_limit_status_line_has_expected_keys() -> None:
    h = HardLimitTracker(max_orders=5, window_sec=1.0, max_price_jump_pct=0.01)
    st = h.status_line()
    assert "orders_in_window" in st
    assert "order_limit" in st


def test_hard_limit_orders_counted_correctly() -> None:
    h = HardLimitTracker(max_orders=3, window_sec=60.0, max_price_jump_pct=0.05)
    h.record_order()
    h.record_order()
    assert h.status_line()["orders_in_window"] == 2


def test_hard_limit_price_jump_check_does_not_raise() -> None:
    """Büyük fiyat atlaması log atar ama exception fırlatmaz."""
    h = HardLimitTracker(max_orders=10, window_sec=60.0, max_price_jump_pct=0.001)
    h.check_price_tick("BTC/USDT", 100.0)
    h.check_price_tick("BTC/USDT", 110.0)  # %10 atlama — eşiği aşar
    # hata fırlatmadan devam etmeli
    assert "orders_in_window" in h.status_line()
