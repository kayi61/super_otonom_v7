from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_bridge_phase50_halt_when_emergency_stop() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    engine = MagicMock()
    engine.risk.emergency_stop = True
    analysis: dict = {}
    dctx = MagicMock()
    dctx.entry_blocked = None
    dctx.adj_signal_quality = None
    dctx.effective_quality_min = None

    attach_override_phases_to_analysis(analysis, engine=engine, dctx=dctx, out={})

    assert analysis["phase50"]["trade_permission"] == "HALT"
    assert analysis["phase50"]["source"] == "risk_manager"


def test_bridge_phase39_block_when_entry_scale_blocked() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    engine = MagicMock()
    engine.risk.emergency_stop = False
    analysis = {"entry_scale": "blocked"}
    dctx = MagicMock()
    dctx.entry_blocked = None
    dctx.adj_signal_quality = 80
    dctx.effective_quality_min = 50

    attach_override_phases_to_analysis(analysis, engine=engine, dctx=dctx, out={})

    assert analysis["phase39"]["trade_permission"] == "BLOCK"


def test_bridge_phase64_block_when_quality_below_min() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    engine = MagicMock()
    engine.risk.emergency_stop = False
    analysis = {}
    dctx = MagicMock()
    dctx.entry_blocked = None
    dctx.adj_signal_quality = 40
    dctx.effective_quality_min = 50

    attach_override_phases_to_analysis(analysis, engine=engine, dctx=dctx, out={})

    assert analysis["phase64"]["trade_permission"] == "BLOCK"


def test_bridge_phase68_halt_when_force_all_close() -> None:
    from super_otonom.pipelines.override_phase_bridge import attach_override_phases_to_analysis

    engine = MagicMock()
    engine.risk.emergency_stop = False
    analysis = {}
    dctx = MagicMock()
    dctx.entry_blocked = None
    dctx.adj_signal_quality = None
    dctx.effective_quality_min = None

    with patch(
        "super_otonom.pipelines.override_phase_bridge.risk_pipeline.force_all_close_requested",
        return_value=True,
    ):
        attach_override_phases_to_analysis(analysis, engine=engine, dctx=dctx, out={})

    assert analysis["phase68"]["trade_permission"] == "HALT"
