"""Faz 9 — edge_evidence hızlı duman (synthetic, ağ yok)."""

import io
import json
from contextlib import redirect_stdout

import pytest

from super_otonom.edge_evidence import main

pytestmark = pytest.mark.fastrun


def test_edge_evidence_synthetic_json_exit_zero():
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(
            [
                "--source",
                "synthetic",
                "--timeframe",
                "5m",
                "--limit",
                "220",
                "--window-size",
                "120",
                "--step-size",
                "60",
                "--json",
            ]
        )
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["timeframe"] == "5m"
    assert payload["periods_per_year"] > 100_000
