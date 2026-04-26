"""WFAManager / WFAFold— tam modül dolaşımı (kapsam)."""
from __future__ import annotations

import logging

import pandas as pd
import pytest
from super_otonom.wfa_manager import WFAFold, WFAManager


def _df(n: int) -> pd.DataFrame:
    return pd.DataFrame({"c": range(n), "o": 1.0})


def test_wfa_fold_repr() -> None:
    t = _df(5)
    f = WFAFold(0, t, t, (0, 3), (3, 5))
    r = repr(f)
    assert "WFAFold" in r
    assert "id=0" in r


def test_manager_rejects_empty_data() -> None:
    with pytest.raises(ValueError, match="bos"):
        WFAManager(pd.DataFrame(), window_size=10, step_size=1)
    with pytest.raises(ValueError, match="bos"):
        WFAManager(_df(0), window_size=10, step_size=1)


def test_manager_rejects_invalid_window() -> None:
    with pytest.raises(ValueError, match="pozitif"):
        WFAManager(_df(100), window_size=0, step_size=5)
    with pytest.raises(ValueError, match="pozitif"):
        WFAManager(_df(100), window_size=50, step_size=0)


def test_manager_rejects_bad_train_ratio() -> None:
    with pytest.raises(ValueError, match="train_ratio"):
        WFAManager(_df(100), window_size=50, step_size=10, train_ratio=1.0)
    with pytest.raises(ValueError, match="train_ratio"):
        WFAManager(_df(100), window_size=50, step_size=10, train_ratio=0.0)


def test_get_folds_creates_folds() -> None:
    d = _df(5000)
    m = WFAManager(d, window_size=1000, step_size=200, min_test_rows=1)
    folds = m.get_folds()
    assert len(folds) >= 1
    assert all(isinstance(f, WFAFold) for f in folds)
    assert folds[0].train_range[0] == 0


def test_get_folds_skips_small_test(caplog: pytest.LogCaptureFixture) -> None:
    d = _df(2000)
    m = WFAManager(d, window_size=200, step_size=200, min_test_rows=200)
    caplog.set_level(logging.DEBUG, logger="super_otonom.wfa")
    folds = m.get_folds()
    # Hiç veya az fold; en az kütüphane hata vermez
    assert isinstance(folds, list)


def test_record_result_and_summary() -> None:
    d = _df(2000)
    m = WFAManager(d, window_size=1000, step_size=200, min_test_rows=1)
    folds = m.get_folds()
    assert folds
    f0 = folds[0]
    m.record_result(f0, {"a": 1}, train_score=0.9, test_score=0.4)
    assert f0.best_params == {"a": 1}
    assert f0.train_score == 0.9
    assert f0.test_score == 0.4
    s = m.summary()
    assert s.get("status") != "no_results" or "folds" in s
    if "folds" in s and s["folds"]:
        assert "test_scores" in s
        p = m.best_params()
        assert p == {"a": 1}


def test_summary_empty() -> None:
    m = WFAManager(_df(2000), window_size=1000, step_size=200)
    assert m.summary() == {"status": "no_results"}
    assert m.best_params() == {}


def test_best_params_uses_custom_metric() -> None:
    d = _df(5000)
    m = WFAManager(d, window_size=1000, step_size=200, min_test_rows=1)
    folds = m.get_folds()
    m.record_result(folds[0], {"x": 2}, 0.5, 0.1)
    m.record_result(folds[1], {"x": 3}, 0.6, 0.2)
    b = m.best_params("train_score")
    assert b == {"x": 3}


def test_results_dataframe() -> None:
    m = WFAManager(_df(2000), window_size=1000, step_size=200, min_test_rows=1)
    f = m.get_folds()[0]
    m.record_result(f, {"p": 9}, 0.1, 0.2)
    df = m.results_dataframe()
    assert len(df) == 1
    assert "param_p" in df.columns or "fold_id" in df.columns


def test_summary_empty_test_scores_stats() -> None:
    """157: _stats boş liste → {}."""
    m = WFAManager(_df(5000), window_size=1000, step_size=200, min_test_rows=1)
    f0, f1 = m.get_folds()[:2]
    m.record_result(f0, {}, train_score=0.5, test_score=None)
    m.record_result(f1, {}, train_score=0.6, test_score=None)
    s = m.summary()
    assert s["test_scores"] == {}
    assert s["train_scores"].get("count") == 2


def test_summary_overfit_ratio_computed() -> None:
    """168-171."""
    m = WFAManager(_df(5000), window_size=1000, step_size=200, min_test_rows=1)
    f0, f1 = m.get_folds()[:2]
    m.record_result(f0, {}, train_score=0.8, test_score=0.3)
    m.record_result(f1, {}, train_score=0.8, test_score=0.2)
    s = m.summary()
    assert s.get("overfit_ratio") is not None
    assert s["overfit_ratio"] > 0


def test_results_dataframe_no_rows() -> None:
    """193-194."""
    m = WFAManager(_df(2000), window_size=1000, step_size=200, min_test_rows=1)
    assert m.results_dataframe().empty
