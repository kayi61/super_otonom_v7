"""P-3 kabul + regresyon testi: RiskEngine.compute() her input'ta <2s.

Kok sebep (cProfile ile bulundu): evt.py'nin bootstrap GPD fit'i her resample'da
scipy.stats.genpareto.fit (Nelder-Mead MLE) cagiriyordu -> 500 fit ~40s, trading
loop'u bloklardi (zarardaki pozisyon kapatilamaz). 250-gun (institutional) input en
kotu durumdu cunku n in [200,500) -> adaptive bootstrap yolu aktiflesir.

Fix: vektorel kapali-form PWM (Hosking & Wallis 1987). Bu test hem hizi (<2s) hem de
PWM'in DOGRULUGUNU (sahte-hizli degil) dogrular.
"""
from __future__ import annotations

import time

import numpy as np
import pytest
from scipy.stats import genpareto
from super_otonom.risk.config import RiskConfig
from super_otonom.risk.evt import _bootstrap_gpd_fit, pot_var_cvar
from super_otonom.risk.risk_engine import RiskEngine

_BUDGET_S = 2.0
_ENGINE = RiskEngine()


def _series(n, df, sigma, seed):
    rng = np.random.RandomState(seed)
    return (rng.standard_t(df, n) * sigma).tolist()


# 250-gun ve komsu boyutlar; eskiden 14-39s suren input'lar dahil.
_CASES = {
    "t_df4_250_institutional": _series(250, 4, 0.02, 1),
    "t_df2_250_fat_tail": _series(250, 2, 0.03, 2),       # eskiden ~13.8s
    "normal_250": (np.random.RandomState(3).normal(0, 0.02, 250)).tolist(),  # ~20.7s
    "big_sigma_250": _series(250, 3, 0.15, 4),            # eskiden ~39s
    "n300_bootstrap": _series(300, 4, 0.02, 5),
    "n499_max_bootstrap": _series(499, 3, 0.025, 6),      # bootstrap araliginin ucu
}


def _best_time(ret, runs=3):
    _ENGINE.compute(ret)  # warmup (lazy import maliyetini disla)
    best = float("inf")
    for _ in range(runs):
        t = time.perf_counter()
        _ENGINE.compute(ret)
        best = min(best, time.perf_counter() - t)
    return best


@pytest.mark.parametrize("name", list(_CASES))
def test_compute_under_2s(name):
    elapsed = _best_time(_CASES[name])
    assert elapsed < _BUDGET_S, f"{name}: compute() {elapsed:.2f}s >= {_BUDGET_S}s (P-3 ihlali)"


def test_compute_under_2s_with_fhs_default_config():
    # Varsayilan config (FHS/GARCH dahil) ile de 250-gun <2s olmali.
    cfg = RiskConfig()  # fhs default'ta acik
    ret = _CASES["t_df4_250_institutional"]
    _ENGINE.compute(ret, config=cfg)  # warmup
    t = time.perf_counter()
    _ENGINE.compute(ret, config=cfg)
    elapsed = time.perf_counter() - t
    assert elapsed < _BUDGET_S, f"compute(+fhs) {elapsed:.2f}s >= {_BUDGET_S}s"


def test_evt_bootstrap_is_fast():
    # Bootstrap GPD fit'i tek basina cok hizli olmali (eski: ~40s, yeni: ms).
    rng = np.random.RandomState(7)
    exceedances = np.abs(rng.standard_t(4, 30)) * 0.01
    t = time.perf_counter()
    _bootstrap_gpd_fit(exceedances, n_bootstrap=500, seed=42)
    elapsed = time.perf_counter() - t
    assert elapsed < 0.5, f"bootstrap GPD fit {elapsed:.3f}s cok yavas"


def test_pwm_recovers_known_gpd_shape():
    # SAHTE-HIZLI degil: PWM bilinen GPD shape'ini makul dogrulukla geri kazanmali.
    true_shape, true_scale = 0.2, 0.01
    rng = np.random.default_rng(333)
    exceedances = genpareto.rvs(true_shape, scale=true_scale, size=3000, random_state=rng)
    shape, scale = _bootstrap_gpd_fit(np.asarray(exceedances), n_bootstrap=200, seed=11)
    assert abs(shape - true_shape) < 0.12, f"PWM shape={shape:.4f} (true {true_shape})"
    assert abs(scale - true_scale) / true_scale < 0.25, f"PWM scale={scale:.5f}"


def test_evt_still_returns_valid_var_cvar():
    # Fonksiyonel: bootstrap yolu (n in [200,500)) hala gecerli VaR/CVaR uretir.
    ret = _series(250, 4, 0.02, 99)
    var, cvar = pot_var_cvar(ret, conf=0.99)
    assert var is not None and cvar is not None
    assert var > 0 and cvar >= var - 1e-9
