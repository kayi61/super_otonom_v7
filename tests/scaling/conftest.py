"""Scaling altındaki analyze yoğun testlerde Hurst polyfit RuntimeWarning susturulur."""

from __future__ import annotations

import warnings

import pytest


@pytest.fixture(autouse=True)
def _suppress_hurst_log_runtime_warning() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="divide by zero encountered in log",
            category=RuntimeWarning,
        )
        yield
