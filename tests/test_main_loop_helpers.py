"""main_loop modülü— yardımcı fonksiyonlar (ağır async döngü yok)."""
from __future__ import annotations

from typing import Any

import pytest
import super_otonom.main_loop as ml


def test_handle_signal_sets_shutdown() -> None:
    ml._shutdown.clear()
    ml._handle_signal()
    assert ml._shutdown.is_set()


@pytest.fixture
def mock_engine() -> Any:
    class E:
        risk = type("R", (), {"emergency_stop": False})()

    return E()


def test_log_elite_startup(mock_engine: Any) -> None:
    ml._log_elite_startup(mock_engine)
