"""
Cross-module invariant: RiskManager._peak_equity vs CapitalEngine.nav.

Eski ``super_otonom/test_cross_module_invariant.py`` scriptindeki ``check()``
akışı pytest'te ``gate_check`` fixture'ı + fabrika fixture'ları ile (legacy imza).
"""

from __future__ import annotations

import logging

import pytest

logging.disable(logging.CRITICAL)


@pytest.fixture(autouse=True)
def _cross_module_drawdown_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eski ``test_cross_module_invariant`` script RISK özetine yaklaştır."""
    import super_otonom.config as cfg

    monkeypatch.setitem(cfg.RISK, "max_total_drawdown", 0.15)
    monkeypatch.setitem(cfg.RISK, "max_exposure_pct", 0.95)
    monkeypatch.setitem(cfg.RISK, "max_daily_loss_pct", 0.03)


def test_t1_peak_equity_desync_without_update_peak(
    gate_check,
    capital_engine_factory,
    risk_manager_factory,
) -> None:
    """onto=None: NAV zirve yapar; RiskManager peak güncellenmezse DD yanlış."""
    ce = capital_engine_factory(10000.0)
    rm = risk_manager_factory(10000.0)

    oid = "test_order_1"
    ce.open_position("BTC/USDT", oid, 50000.0, 0.1, 5000.0)
    ce.update_unrealized({"BTC/USDT": 55000.0})

    nav_peak = ce.nav
    gate_check(
        "T1.1 nav_peak doğru hesaplandı",
        nav_peak > 10000.0,
        f"nav_peak={nav_peak:.2f}",
    )

    gate_check.check(
        "T1.2 rm._peak_equity hala initial (güncellenmedi)",
        rm._peak_equity == 10000.0,
        f"rm._peak_equity={rm._peak_equity:.2f} (beklenen=10000.0)",
    )

    ce.update_unrealized({"BTC/USDT": 35000.0})
    nav_now = ce.nav
    real_dd = (nav_peak - nav_now) / nav_peak

    gate_check(
        "T1.3 gerçek drawdown %15 üstünde",
        real_dd > 0.15,
        f"real_dd={real_dd * 100:.1f}%",
    )

    risk_result = rm.check_risk(
        current_equity=nav_now,
        open_exposure=ce._margin_used,
        current_vol=0.0,
    )

    if rm._peak_equity > 0:
        rm_dd = (rm._peak_equity - nav_now) / rm._peak_equity
    else:
        rm_dd = 0.0

    gate_check.check(
        "T1.4 rm drawdown hesabı gerçek peak'e göre YANLIŞ",
        abs(rm_dd - real_dd) > 0.01,
        f"rm_dd={rm_dd * 100:.1f}% real_dd={real_dd * 100:.1f}% fark={abs(rm_dd - real_dd) * 100:.1f}%",
    )

    gate_check.check(
        "T1.5 emergency_stop tetiklenmeli (drawdown > %15)",
        not risk_result,
        f"risk_result={risk_result} (False bekleniyor)",
    )


def test_t2_manual_update_peak_triggers_emergency(
    gate_check,
    capital_engine_factory,
    risk_manager_factory,
) -> None:
    ce2 = capital_engine_factory(10000.0)
    rm2 = risk_manager_factory(10000.0)

    oid2 = "test_order_2"
    ce2.open_position("ETH/USDT", oid2, 2000.0, 1.0, 2000.0)
    ce2.update_unrealized({"ETH/USDT": 2400.0})

    nav_peak2 = ce2.nav
    rm2.update_peak(nav_peak2)

    gate_check(
        "T2.1 rm._peak_equity güncellendi",
        rm2._peak_equity == nav_peak2,
        f"rm._peak_equity={rm2._peak_equity:.2f} nav_peak={nav_peak2:.2f}",
    )

    ce2.update_unrealized({"ETH/USDT": 700.0})
    nav_now2 = ce2.nav
    real_dd2 = (nav_peak2 - nav_now2) / nav_peak2

    rm2.update_peak(nav_now2)

    risk_result2 = rm2.check_risk(
        current_equity=nav_now2,
        open_exposure=ce2._margin_used,
        current_vol=0.0,
    )

    gate_check.check(
        "T2.2 update_peak sonrası emergency doğru tetiklendi",
        not risk_result2,
        f"risk_result={risk_result2} real_dd={real_dd2 * 100:.1f}%",
    )

    gate_check(
        "T2.3 emergency_reason doğru",
        rm2.emergency_reason == "max_drawdown",
        f"emergency_reason={rm2.emergency_reason}",
    )


def test_t3_margin_zero_after_close(
    gate_check,
    capital_engine_factory,
) -> None:
    ce3 = capital_engine_factory(10000.0)
    oid3 = "test_order_3"
    ce3.open_position("SOL/USDT", oid3, 100.0, 10.0, 1000.0)

    gate_check("T3.1 margin_used pozitif", ce3._margin_used > 0, f"margin_used={ce3._margin_used:.2f}")

    ce3.close_position("SOL/USDT", "close_3", 110.0, 10.0)

    gate_check.check(
        "T3.2 margin_used sıfıra yakın",
        abs(ce3._margin_used) < 0.01,
        f"margin_used={ce3._margin_used:.2f}",
    )
    gate_check.check(
        "T3.3 SOL pozisyonu kapandı",
        "SOL/USDT" not in ce3._positions,
        f"positions={list(ce3._positions.keys())}",
    )
    gate_check("T3.4 CE invariant", ce3._check_invariant(), f"nav={ce3.nav:.2f}")


def test_t4_open_drop_close_reopen_chain(
    gate_check,
    capital_engine_factory,
    risk_manager_factory,
) -> None:
    ce4 = capital_engine_factory(10000.0)
    rm4 = risk_manager_factory(10000.0)

    ce4.open_position("BTC/USDT", "o1", 50000.0, 0.01, 500.0)
    rm4.update_peak(ce4.nav)

    ce4.update_unrealized({"BTC/USDT": 48000.0})
    rm4.update_peak(ce4.nav)

    pnl = ce4.close_position("BTC/USDT", "c1", 48000.0, 0.01)
    if pnl is not None:
        rm4.record_pnl(pnl)

    gate_check.check(
        "T4.1 kapanış sonrası zarar kaydedildi",
        rm4.daily_loss > 0,
        f"daily_loss={rm4.daily_loss:.2f}",
    )

    ce4.open_position("BTC/USDT", "o2", 45000.0, 0.1, 4500.0)

    gate_check(
        "T4.2 ikinci açılış sonrası invariant korunuyor",
        ce4._check_invariant(),
        f"nav={ce4.nav:.2f}",
    )

    gate_check.check(
        "T4.3 margin_used pozitif",
        ce4._margin_used > 0,
        f"margin_used={ce4._margin_used:.2f}",
    )

    risk_ok = rm4.check_risk(
        current_equity=ce4.nav,
        open_exposure=ce4._margin_used,
        current_vol=0.0,
    )

    gate_check.check(
        "T4.4 düşük kayıp sonrası risk check geçiyor",
        risk_ok is True,
        f"risk_ok={risk_ok} nav={ce4.nav:.2f}",
    )
