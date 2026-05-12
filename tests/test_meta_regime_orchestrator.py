"""PROMPT-A9 — meta-orchestrator (rejim → faz ailesi ağırlık) MVP."""

from __future__ import annotations

import pytest
from super_otonom.meta_regime_orchestrator import (
    DEFAULT_FAMILY_WEIGHTS,
    KNOWN_FAMILIES,
    KNOWN_REGIMES,
    META_REGIME_KEY,
    SCHEMA_VERSION,
    advisory_ack_path_for_gate,
    attach_meta_regime,
    compact_meta_regime_for_attribution,
    compute_meta_regime,
    family_weights_for_regime,
    normalize_regime,
    write_meta_advisory_ack_file,
)


@pytest.fixture(autouse=True)
def _meta_advisory_loose_autouse(monkeypatch):
    """Üretimde advisory sıkı kilittir; bu dosyadaki testler varsayılan olarak gevşetilir."""
    monkeypatch.setenv("META_ADVISORY_LOOSE", "1")


def test_advisory_ack_path_none_when_not_advisory(monkeypatch):
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)
    assert advisory_ack_path_for_gate("shadow") is None
    assert advisory_ack_path_for_gate("off") is None


def test_advisory_ack_path_respects_explicit_file(monkeypatch, tmp_path):
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)
    p = tmp_path / "custom_ack"
    monkeypatch.setenv("META_ADVISORY_ACK_FILE", str(p))
    assert advisory_ack_path_for_gate("advisory") == str(p)


def test_advisory_ack_path_none_when_loose(monkeypatch):
    monkeypatch.setenv("META_ADVISORY_LOOSE", "1")
    assert advisory_ack_path_for_gate("advisory") is None


def test_known_regimes_table_complete():
    """Tüm bilinen rejimler için 4 aile ağırlığı tanımlı, 0 < w <= 1.2."""
    for r in KNOWN_REGIMES + ("UNKNOWN",):
        w = DEFAULT_FAMILY_WEIGHTS[r]
        assert set(w.keys()) == set(KNOWN_FAMILIES), f"{r}: aile seti eksik"
        for fam, val in w.items():
            assert 0.5 <= val <= 1.2, f"{r}/{fam} ağırlığı sınır dışı: {val}"


def test_normalize_regime_variants():
    assert normalize_regime("trending") == "TRENDING"
    assert normalize_regime(" CRASH_RISK ") == "CRASH_RISK"
    assert normalize_regime("RANGING") == "RANGING"
    assert normalize_regime("chop") == "RANGING"
    assert normalize_regime("crisis") == "CRASH_RISK"
    assert normalize_regime("trend") == "TRENDING"
    assert normalize_regime(None) == "UNKNOWN"
    assert normalize_regime("BULL") == "UNKNOWN"


def test_family_weights_for_regime_unknown_neutral():
    w = family_weights_for_regime("MYSTERY")
    assert w == {fam: 1.0 for fam in KNOWN_FAMILIES}


def test_family_weights_for_regime_crash_skews_gov_up_exec_down():
    w = family_weights_for_regime("CRASH_RISK")
    assert w["gov"] > 1.0
    assert w["exec"] < 1.0
    assert w["micro"] < 1.0


def test_shadow_mode_does_not_change_confidence():
    """Varsayılan shadow modda güven değişmez; analysis'e meta yazılır."""
    analysis = {"omega_regime": "TRENDING"}
    chain = {"faz71": {"confidence": 0.8}, "faz80": {"confidence": 0.7}}
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.65, mode="shadow"
    )
    assert eff == pytest.approx(0.65)
    assert payload["mode"] == "shadow"
    assert payload["applied"] is False
    assert payload["schema"] == SCHEMA_VERSION
    assert analysis[META_REGIME_KEY]["regime"] == "TRENDING"
    # Faz aileleri sayım: faz71 -> micro, faz80 -> exec
    counts = analysis[META_REGIME_KEY]["family_counts"]
    assert counts["micro"] == 1
    assert counts["exec"] == 1


def test_off_mode_writes_nothing_and_keeps_confidence():
    analysis: dict = {"omega_regime": "RANGING"}
    eff, payload = attach_meta_regime(
        analysis, {"faz72": {}}, base_confidence=0.77, mode="off"
    )
    assert eff == pytest.approx(0.77)
    assert payload["mode"] == "off"
    assert payload["applied"] is False
    assert META_REGIME_KEY not in analysis


def test_advisory_mode_trending_lifts_within_bounds():
    """TRENDING + exec/micro ağırlıklı zincir → hafif yükseliş, tavanda clamp."""
    analysis = {"omega_regime": "TRENDING"}
    chain = {
        "faz71": {"confidence": 0.8},  # micro 1.05
        "faz72": {"confidence": 0.8},  # micro 1.05
        "faz80": {"confidence": 0.7},  # exec 1.10
    }
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.60, mode="advisory"
    )
    assert payload["mode"] == "advisory"
    assert payload["applied"] is True
    # Ağırlıklı ortalama ≈ (1.05 + 1.05 + 1.10)/3 ≈ 1.0667 → bound içinde
    assert payload["weighted_mult"] == pytest.approx(1.0667, abs=1e-3)
    assert 1.0 < payload["advised_confidence_mult"] <= 1.08
    assert eff > 0.60
    assert eff <= 1.0


def test_advisory_mode_crash_dampens_within_bounds():
    """CRASH_RISK + exec ağır zincir → çarpan tabana clamp (0.92)."""
    analysis = {"omega_regime": "CRASH_RISK"}
    chain = {
        "faz76": {"confidence": 0.8},  # exec 0.70
        "faz77": {"confidence": 0.8},  # exec 0.70
        "faz80": {"confidence": 0.7},  # exec 0.70
    }
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.80, mode="advisory"
    )
    assert payload["applied"] is True
    # Aritmetik ort = 0.70 → clamp tabanı 0.92
    assert payload["weighted_mult"] == pytest.approx(0.70, abs=1e-3)
    assert payload["advised_confidence_mult"] == pytest.approx(0.92, abs=1e-3)
    assert eff < 0.80
    assert eff >= 0.0


def test_advisory_unknown_regime_neutral_no_apply():
    """UNKNOWN rejim → tüm aileler 1.0 → advisory'da bile değişim yok."""
    analysis = {"omega_regime": "BULL"}  # bilinmeyen → UNKNOWN
    chain = {"faz72": {}, "faz80": {}}
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.70, mode="advisory"
    )
    assert payload["regime"] == "UNKNOWN"
    assert payload["weighted_mult"] == pytest.approx(1.0)
    assert payload["applied"] is False
    assert eff == pytest.approx(0.70)


def test_advisory_empty_chain_no_apply():
    analysis = {"omega_regime": "TRENDING"}
    eff, payload = attach_meta_regime(
        analysis, {}, base_confidence=0.55, mode="advisory"
    )
    assert payload["weighted_mult"] is None
    assert payload["applied"] is False
    assert eff == pytest.approx(0.55)


def test_compute_pure_no_side_effects():
    analysis = {"omega_regime": "TRENDING"}
    payload = compute_meta_regime(
        analysis, {"faz71": {}}, base_confidence=0.6, mode="shadow"
    )
    assert META_REGIME_KEY not in analysis
    assert payload["regime"] == "TRENDING"


def test_invalid_mode_falls_back_to_shadow():
    analysis = {"omega_regime": "TRENDING"}
    eff, payload = attach_meta_regime(
        analysis, {"faz72": {}}, base_confidence=0.6, mode="banana"
    )
    assert payload["mode"] == "shadow"
    assert eff == pytest.approx(0.6)


def test_env_default_mode_is_shadow(monkeypatch):
    monkeypatch.delenv("META_REGIME_MODE", raising=False)
    analysis = {"omega_regime": "CRASH_RISK"}
    eff, payload = attach_meta_regime(
        analysis, {"faz80": {}}, base_confidence=0.7
    )
    assert payload["mode"] == "shadow"
    assert eff == pytest.approx(0.7)


def test_env_advisory_mode_via_env(monkeypatch):
    monkeypatch.setenv("META_REGIME_MODE", "advisory")
    analysis = {"omega_regime": "TRENDING"}
    eff, payload = attach_meta_regime(
        analysis, {"faz72": {}, "faz80": {}}, base_confidence=0.5
    )
    assert payload["mode"] == "advisory"
    assert eff > 0.5


def test_env_off_mode_via_env(monkeypatch):
    monkeypatch.setenv("META_REGIME_MODE", "off")
    analysis: dict = {"omega_regime": "TRENDING"}
    eff, payload = attach_meta_regime(
        analysis, {"faz72": {}}, base_confidence=0.5
    )
    assert payload["mode"] == "off"
    assert META_REGIME_KEY not in analysis
    assert eff == pytest.approx(0.5)


def test_compact_for_attribution():
    analysis = {"omega_regime": "RANGING"}
    _, payload = attach_meta_regime(
        analysis, {"faz72": {}, "faz80": {}}, base_confidence=0.5, mode="shadow"
    )
    snap = compact_meta_regime_for_attribution(payload)
    assert snap is not None
    assert snap["regime"] == "RANGING"
    assert snap["mode"] == "shadow"
    assert snap["applied"] is False
    assert "weighted_mult" in snap
    assert snap["schema"] == SCHEMA_VERSION


def test_compact_none_input():
    assert compact_meta_regime_for_attribution(None) is None
    assert compact_meta_regime_for_attribution("not a dict") is None  # type: ignore[arg-type]


def test_advisory_zero_base_confidence_no_apply():
    """base_confidence == 0 → çarpan ne olursa olsun applied=False."""
    analysis = {"omega_regime": "TRENDING"}
    eff, payload = attach_meta_regime(
        analysis, {"faz72": {}, "faz80": {}}, base_confidence=0.0, mode="advisory"
    )
    assert payload["applied"] is False
    assert eff == pytest.approx(0.0)


def test_advisory_bounds_env_clamp(monkeypatch):
    """META_ADVISORY_MIN/MAX env clamp aralığı."""
    monkeypatch.setenv("META_ADVISORY_MIN", "0.95")
    monkeypatch.setenv("META_ADVISORY_MAX", "1.05")
    analysis = {"omega_regime": "CRASH_RISK"}
    chain = {"faz80": {}}  # exec 0.70
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.80, mode="advisory"
    )
    # 0.70 < 0.95 → 0.95'e clamplenir
    assert payload["advised_confidence_mult"] == pytest.approx(0.95)
    assert eff == pytest.approx(0.80 * 0.95)


def test_advisory_blocked_when_ack_file_missing(monkeypatch, tmp_path):
    """META_ADVISORY_ACK_FILE dolu ama dosya yok → advisory çarpanı uygulanmaz."""
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)
    missing = tmp_path / "no_such_meta_ack.txt"
    monkeypatch.setenv("META_ADVISORY_ACK_FILE", str(missing))
    analysis = {"omega_regime": "TRENDING"}
    chain = {"faz72": {}, "faz80": {}}
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.60, mode="advisory"
    )
    assert eff == pytest.approx(0.60)
    assert payload["applied"] is False
    assert payload["advisory_blocked_reason"] == "missing_measurement_ack_file"
    assert payload["weighted_mult"] is not None


def test_advisory_allowed_when_ack_file_present(monkeypatch, tmp_path):
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)
    ack = tmp_path / "meta_ack.txt"
    ack.write_text("a5-reviewed", encoding="utf-8")
    monkeypatch.setenv("META_ADVISORY_ACK_FILE", str(ack))
    analysis = {"omega_regime": "TRENDING"}
    chain = {
        "faz71": {"confidence": 0.8},
        "faz72": {"confidence": 0.8},
        "faz80": {"confidence": 0.7},
    }
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.60, mode="advisory"
    )
    assert payload["advisory_blocked_reason"] is None
    assert payload["applied"] is True
    assert eff > 0.60


def test_advisory_strict_default_path_blocks_without_file(monkeypatch, tmp_path):
    """ACK_FILE boş + LOOSE kapalı → varsayılan yol kontrol edilir; dosya yoksa blok."""
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)
    monkeypatch.delenv("META_ADVISORY_ACK_FILE", raising=False)
    missing = tmp_path / "reports" / "meta_advisory_measurement_ack"
    monkeypatch.setenv("META_ADVISORY_DEFAULT_ACK_FILE", str(missing))
    analysis = {"omega_regime": "TRENDING"}
    eff, payload = attach_meta_regime(
        analysis, {"faz72": {}, "faz80": {}}, base_confidence=0.60, mode="advisory"
    )
    assert eff == pytest.approx(0.60)
    assert payload["applied"] is False
    assert payload["advisory_blocked_reason"] == "missing_measurement_ack_file"
    assert payload["measurement_ack_path"] == str(missing)


def test_write_meta_advisory_ack_file_unblocks_strict_advisory(monkeypatch, tmp_path):
    monkeypatch.delenv("META_ADVISORY_LOOSE", raising=False)
    monkeypatch.delenv("META_ADVISORY_ACK_FILE", raising=False)
    ack = tmp_path / "ack_gate.txt"
    monkeypatch.setenv("META_ADVISORY_DEFAULT_ACK_FILE", str(ack))
    written = write_meta_advisory_ack_file(path=str(ack), operator_note="pytest A5 ok")
    assert written == str(ack.resolve())
    analysis = {"omega_regime": "TRENDING"}
    chain = {"faz71": {"confidence": 0.8}, "faz72": {"confidence": 0.8}, "faz80": {"confidence": 0.7}}
    eff, payload = attach_meta_regime(
        analysis, chain, base_confidence=0.60, mode="advisory"
    )
    assert payload["advisory_blocked_reason"] is None
    assert payload["applied"] is True
    assert eff > 0.60
