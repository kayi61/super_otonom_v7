"""sharpe_audit — repo taraması fastrun."""

from __future__ import annotations

import pytest
from super_otonom.sharpe_audit import audit_sharpe_annualization, main

pytestmark = pytest.mark.fastrun


def test_sharpe_repo_audit_passes() -> None:
    assert audit_sharpe_annualization() == []


def test_sharpe_audit_cli() -> None:
    assert main([]) == 0
