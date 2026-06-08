"""Null-kontrol motorunun KANITI (laf degil, calisan ispat).

Bu testler null-kontrolun uc isi de dogru yaptigini gosterir:
  1. GERCEK yapiyi (autocorrelation/momentum) yakalar  -> passes_null=True
  2. SAHTE/sans (random walk'ta momentum) elenir         -> passes_null=False
  3. SIZINTI (ayni-bara bakan look-ahead) yakalanir       -> passes_null=False
Hepsi deterministik (sabit seed). Sahte gecmez, gercek elenmez.
"""
from __future__ import annotations

import numpy as np
import pytest
from super_otonom.research.null_control import (
    empirical_pvalue,
    format_report,
    null_control_test,
    permutation_null_distribution,
    random_walk_candles,
    shuffle_bars,
)


# --------------------------------------------------------------------------- #
# yardimcilar: sentetik veri + strateji-istatistikleri
# --------------------------------------------------------------------------- #
def _candles_from_close(close: np.ndarray) -> list:
    out = []
    for i in range(len(close)):
        o = float(close[i - 1]) if i > 0 else float(close[0])
        c = float(close[i])
        out.append(
            {
                "timestamp": float(i),
                "open": o,
                "high": max(o, c) * 1.001,
                "low": min(o, c) * 0.999,
                "close": c,
                "volume": 1.0,
            }
        )
    return out


def _ar1_candles(n: int, phi: float, sigma: float, seed: int) -> list:
    """Pozitif-autocorrelation getiriler (momentum gercekten kazanir)."""
    rng = np.random.default_rng(seed)
    e = rng.normal(0.0, sigma, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]
    return _candles_from_close(100.0 * np.exp(np.cumsum(r)))


def _bar_returns(candles: list) -> np.ndarray:
    c = np.asarray([x["close"] for x in candles], dtype=float)
    return np.diff(c) / c[:-1]


def _momentum_stat(candles: list) -> float:
    """Onceki barin getirisi yonunde dur; ortalama bar PnL. Autocorrelation'a duyarli."""
    r = _bar_returns(candles)
    if r.size < 3:
        return 0.0
    pos = np.sign(r[:-1])
    return float(np.mean(pos * r[1:]))


def _lookahead_stat(candles: list) -> float:
    """SIZINTILI: AYNI barin getirisine bakar -> mean(|getiri|), her zaman pozitif.
    Karistirilmis veride de calisir (gelecege bakma her veride 'kazanir')."""
    r = _bar_returns(candles)
    if r.size < 1:
        return 0.0
    return float(np.mean(np.sign(r) * r))


# --------------------------------------------------------------------------- #
# 1) saf matematik: ampirik p-deger
# --------------------------------------------------------------------------- #
def test_empirical_pvalue_bounds_and_monotonic():
    null = np.linspace(-1.0, 1.0, 101)
    # cok yuksek gozlem -> kucuk p (add-one ile asla 0 degil)
    assert empirical_pvalue(10.0, null) == pytest.approx(1.0 / 102.0)
    # cok dusuk gozlem -> p ~ 1
    assert empirical_pvalue(-10.0, null) == pytest.approx(1.0)
    # monotonluk: gozlem buyudukce p kuculur (ya da esit)
    p_hi = empirical_pvalue(0.8, null)
    p_lo = empirical_pvalue(-0.8, null)
    assert p_hi < p_lo
    # bos null -> guvenli 1.0
    assert empirical_pvalue(0.0, np.array([])) == 1.0


# --------------------------------------------------------------------------- #
# 2) shuffle_bars: getiri coklugunu KORUR, zaman yapisini (autocorr) YOK EDER
# --------------------------------------------------------------------------- #
def test_shuffle_preserves_return_multiset_destroys_autocorr():
    candles = _ar1_candles(800, phi=0.45, sigma=0.01, seed=7)
    rng = np.random.default_rng(123)
    shuffled = shuffle_bars(candles, rng)

    r0 = _bar_returns(candles)
    r1 = _bar_returns(shuffled)
    # bar-getiri coklugu (sirali) korunur
    assert np.allclose(np.sort(r0), np.sort(r1), atol=1e-9)

    def lag1(x):
        return float(np.corrcoef(x[:-1], x[1:])[0, 1])

    # gercek veri pozitif autocorr; karistirilmis ~0
    assert lag1(r0) > 0.2
    assert abs(lag1(r1)) < 0.12


def test_random_walk_candles_have_no_drift_edge():
    rng = np.random.default_rng(11)
    candles = random_walk_candles(500, rng, mu=0.0, sigma=0.02)
    assert len(candles) == 500
    # driftsiz -> momentum istatistigi ~0 civari (kesin sifir degil ama kucuk)
    assert abs(_momentum_stat(candles)) < 0.01


# --------------------------------------------------------------------------- #
# 3) GERCEK yapi yakalanir: AR(1) momentum -> passes_null=True, p kucuk
# --------------------------------------------------------------------------- #
def test_real_momentum_structure_passes_null():
    candles = _ar1_candles(700, phi=0.45, sigma=0.01, seed=3)
    res = null_control_test(_momentum_stat, candles, n_perm=400, seed=42)
    assert res["observed"] > res["null_mean"]
    assert res["z_vs_null"] > 2.0
    assert res["p_value"] < 0.05
    assert res["passes_null"] is True
    assert res["verdict"] == "REAL_CANDIDATE"


# --------------------------------------------------------------------------- #
# 4) SIZINTI yakalanir: ayni-bara bakan look-ahead -> null'da DA yuksek -> elenir
#    (en sinsi hata; permutasyon testinin asil degeri burada)
# --------------------------------------------------------------------------- #
def test_lookahead_leak_is_flagged_as_null():
    candles = _ar1_candles(700, phi=0.20, sigma=0.01, seed=5)
    res = null_control_test(_lookahead_stat, candles, n_perm=400, seed=42)
    # gozlem yuksek ve pozitif (mean(|r|)) AMA null da ayni derecede yuksek
    assert res["observed"] > 0.0
    assert res["null_mean"] > 0.0
    assert res["z_vs_null"] < 2.0          # null'dan ayirt edilemiyor
    assert res["p_value"] >= 0.05
    assert res["passes_null"] is False     # SIZINTI artefakt olarak damgalandi
    assert res["verdict"] == "INDISTINGUISHABLE_FROM_NULL"


# --------------------------------------------------------------------------- #
# 5) SAHTE-POZITIF YOK: random walk'ta momentum -> elenir
# --------------------------------------------------------------------------- #
def test_no_false_positive_on_random_walk():
    rng = np.random.default_rng(99)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, 700)))
    candles = _candles_from_close(close)
    res = null_control_test(_momentum_stat, candles, n_perm=400, seed=42)
    assert res["p_value"] > 0.05
    assert res["passes_null"] is False


def test_random_walk_method_runs():
    candles = _ar1_candles(300, phi=0.4, sigma=0.01, seed=1)
    null = permutation_null_distribution(
        _momentum_stat, candles, n_perm=50, method="random_walk", seed=4
    )
    assert null.size > 0 and np.all(np.isfinite(null))


def test_unknown_method_raises():
    candles = _ar1_candles(50, phi=0.3, sigma=0.01, seed=1)
    with pytest.raises(ValueError):
        permutation_null_distribution(_momentum_stat, candles, n_perm=2, method="bogus")


def test_format_report_contains_verdict():
    candles = _ar1_candles(400, phi=0.45, sigma=0.01, seed=2)
    res = null_control_test(_momentum_stat, candles, n_perm=200, seed=42)
    text = format_report("momentum-AR1", res)
    assert "NULL-KONTROL: momentum-AR1" in text
    assert res["verdict"] in text
