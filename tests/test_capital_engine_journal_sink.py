"""CapitalEngine ``journal_sink`` — TimescaleDB yolunda test edilmez (DB yok); mock ile doğrulanır."""

from __future__ import annotations

import pytest
from super_otonom.capital_engine import CapitalEngine

pytestmark = pytest.mark.fastrun


def test_journal_sink_receives_journal_dict_rows(tmp_path) -> None:
    buf: list[dict] = []

    def sink(row: dict) -> None:
        buf.append(row)

    jf = tmp_path / "j.jsonl"
    e = CapitalEngine(10_000, journal_file=str(jf), journal_sink=sink, reserve_pct=0.0)
    e.deposit(50.0, note="unit")

    assert len(buf) == 1
    assert buf[0]["event"] == "DEPOSIT"
    assert buf[0]["amount"] == 50.0
    assert "snap_nav" in buf[0]
