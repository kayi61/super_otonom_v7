"""
PROMPT-A9 — Meta-orchestrator: rejim → faz ailesi ağırlık tablosu (kurallı, ML değil).

Üç mod:
  - ``shadow`` (varsayılan): yalnızca gözlem; ``ai_confidence`` değişmez. Ağırlıklar
    ``analysis["meta_regime"]`` üzerinden A5 / A7 / log akışlarına yazılır.
  - ``advisory``: aktif faz aileleri ile ağırlıklı ortalamadan sınırlı bir güven
    çarpanı türetilir; sonuç ``META_ADVISORY_MIN``..``META_ADVISORY_MAX`` arası
    clamplenir (varsayılan 0.92..1.08).
  - ``off``: hiçbir şey yapmaz; ``analysis`` da yazılmaz.

"Ölçüm olmadan ağırlık değiştirme yok": varsayılan **shadow**; **advisory** modda
güven çarpanı yalnızca ölçüm onay dosyası varken uygulanır (``META_ADVISORY_ACK_FILE``
veya varsayılan ``data/reports/meta_advisory_measurement_ack``). Dosya yoksa
``advisory_blocked_reason``. Yerel/test için ``META_ADVISORY_LOOSE=1``. Onay
dosyası: ``python -m super_otonom.meta_regime_orchestrator --message "A5 …"``.

Kanonik rejim sözlüğü (omega ile aynı): **trend** → ``TRENDING``, **chop** →
``RANGING``, **crisis** → ``CRASH_RISK``. ``normalize_regime`` bazı takma
adları da kabul eder (``CHOP`` → ``RANGING``, ``CRISIS`` → ``CRASH_RISK``, …).

**ML:** Bu modülde öğrenilmiş ağırlık yok; isteğe bağlı ML yalnızca ayrı bir
PROMPT ve ölçüm hattı onayından sonra düşünülür (kurallı tablo her zaman
referans / floor olarak kalır).

Env (opsiyonel)::

  META_REGIME_MODE       — "shadow" | "advisory" | "off"  (varsayılan: "shadow")
  META_ADVISORY_MIN      — varsayılan 0.92  (çarpan tabanı)
  META_ADVISORY_MAX      — varsayılan 1.08  (çarpan tavanı)
  META_ADVISORY_ACK_FILE — doluysa: advisory modda güven çarpanı yalnızca bu
                           dosya mevcut ve boş değilse uygulanır.
  META_ADVISORY_DEFAULT_ACK_FILE — ``META_ADVISORY_ACK_FILE`` boşken kullanılan
                           varsayılan yol (std: ``data/reports/meta_advisory_measurement_ack``).
                           Üretimde advisory açıkken bu dosya (veya explicit ACK)
                           yoksa çarpan uygulanmaz.
  META_ADVISORY_LOOSE      — ``1`` / ``true``: ölçüm kilidini kapat (yalnızca
                           yerel geliştirme / birim test; üretimde kullanmayın).

Kanonik rejim kaynağı: ``analysis["omega_regime"]`` (Faz 26 → Faz 45 üretir;
``super_otonom/omega_regime.py``).  Etiketler: ``TRENDING``, ``RANGING``, ``CRASH_RISK``.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from super_otonom.confidence_calibration import family_for_phase_num, phase_key_to_int

SCHEMA_VERSION = "a9/v1"
META_REGIME_KEY = "meta_regime"

# Üretim advisory: ``META_ADVISORY_ACK_FILE`` tanımlı değilse bu göreli yol zorunlu.
DEFAULT_META_ADVISORY_ACK_RELPATH = "data/reports/meta_advisory_measurement_ack"

KNOWN_REGIMES = ("TRENDING", "RANGING", "CRASH_RISK")
KNOWN_FAMILIES = ("gov", "micro", "exec", "other")

# Kurallı (rule-based) tablo. Tasarım ilkesi:
#   - TRENDING: yürütme katmanı (exec) hafif yukarı, mikro orta, gov nötr.
#   - RANGING:  exec ve mikro hafif aşağı (üst üste yüksek güven iddiasına karşı korumacı).
#   - CRASH_RISK: gov yukarı (override yüzeyi), exec ve mikro belirgin aşağı.
#   - UNKNOWN: her aile 1.0 (etkisiz).
#
# Sayılar BİLİNÇLİ olarak küçük tutuldu: "ölçüm olmadan ağırlık değiştirme yok".
# advisory modda dahi clamp ile global etki ±%8 ile sınırlı kalır.
DEFAULT_FAMILY_WEIGHTS: Dict[str, Dict[str, float]] = {
    "TRENDING": {"gov": 1.00, "micro": 1.05, "exec": 1.10, "other": 1.00},
    "RANGING": {"gov": 1.00, "micro": 0.95, "exec": 0.90, "other": 1.00},
    "CRASH_RISK": {"gov": 1.10, "micro": 0.85, "exec": 0.70, "other": 0.85},
    "UNKNOWN": {"gov": 1.00, "micro": 1.00, "exec": 1.00, "other": 1.00},
}

_VALID_MODES = ("shadow", "advisory", "off")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _resolve_mode(mode: Optional[str] = None) -> str:
    raw = mode if mode is not None else os.getenv("META_REGIME_MODE", "shadow")
    s = (raw or "shadow").strip().lower()
    return s if s in _VALID_MODES else "shadow"


def _resolve_advisory_bounds() -> Tuple[float, float]:
    try:
        lo = float(os.getenv("META_ADVISORY_MIN", "0.92") or 0.92)
    except ValueError:
        lo = 0.92
    try:
        hi = float(os.getenv("META_ADVISORY_MAX", "1.08") or 1.08)
    except ValueError:
        hi = 1.08
    lo = _clamp(lo, 0.80, 1.00)
    hi = _clamp(hi, 1.00, 1.20)
    if hi < lo:
        lo, hi = 0.92, 1.08
    return lo, hi


# İnsan / harici analiz etiketleri → omega ile aynı üçlü (trend / chop / crisis).
_REGIME_ALIASES: Dict[str, str] = {
    "TREND": "TRENDING",
    "CHOP": "RANGING",
    "CHOPPY": "RANGING",
    "RANGE": "RANGING",
    "RANGEBOUND": "RANGING",
    "MEAN_REVERTING": "RANGING",
    "NOISY": "RANGING",
    "CRISIS": "CRASH_RISK",
    "CRASH": "CRASH_RISK",
    "STRESS": "CRASH_RISK",
}


def normalize_regime(regime: Any) -> str:
    """Bilinen etiketler büyük harfe; takma adlar kanonik üçlüye; aksi ``UNKNOWN``."""
    s = str(regime or "").strip().upper()
    s = _REGIME_ALIASES.get(s, s)
    return s if s in KNOWN_REGIMES else "UNKNOWN"


def _env_truthy(name: str) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def advisory_ack_path_for_gate(eff_mode: str) -> Optional[str]:
    """
    Ölçüm kilidi için kontrol edilecek dosya yolu.

    ``None`` → kilit kapalı (shadow/off, veya ``META_ADVISORY_LOOSE``).
    Aksi halde dosya mevcut ve boyutu > 0 olmalı.
    """
    if eff_mode != "advisory":
        return None
    if _env_truthy("META_ADVISORY_LOOSE"):
        return None
    explicit = (os.getenv("META_ADVISORY_ACK_FILE") or "").strip()
    if explicit:
        return explicit
    default = (
        os.getenv("META_ADVISORY_DEFAULT_ACK_FILE") or DEFAULT_META_ADVISORY_ACK_RELPATH
    ).strip()
    return default or None


def _advisory_measurement_ack_passes(eff_mode: str) -> Tuple[bool, Optional[str]]:
    path = advisory_ack_path_for_gate(eff_mode)
    if path is None:
        return True, None
    try:
        ok = os.path.isfile(path) and os.path.getsize(path) > 0
        return ok, path
    except OSError:
        return False, path


def write_meta_advisory_ack_file(
    *,
    path: Optional[str] = None,
    operator_note: str = "",
) -> str:
    """
    A5 (veya eşdeğer) inceleme sonrası advisory kilidini açmak için işaret dosyası yazar.

    Hedef sırası: ``path`` argümanı → ``META_ADVISORY_ACK_FILE`` →
    ``META_ADVISORY_DEFAULT_ACK_FILE`` → :data:`DEFAULT_META_ADVISORY_ACK_RELPATH`.
    Üst dizinler oluşturulur.
    """
    candidates = [
        (path or "").strip(),
        (os.getenv("META_ADVISORY_ACK_FILE") or "").strip(),
        (os.getenv("META_ADVISORY_DEFAULT_ACK_FILE") or "").strip(),
        DEFAULT_META_ADVISORY_ACK_RELPATH,
    ]
    target = next((c for c in candidates if c), DEFAULT_META_ADVISORY_ACK_RELPATH)
    p = Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = (operator_note or "").strip()
    body = f"meta_advisory_measurement_ack\nwritten_utc={ts}\n"
    if note:
        body += f"note={note}\n"
    p.write_text(body, encoding="utf-8")
    return str(p.resolve())


def family_weights_for_regime(regime: Any) -> Dict[str, float]:
    """Rejim için tüm KNOWN_FAMILIES anahtarlarını içeren ağırlık dict'i."""
    r = normalize_regime(regime)
    base = DEFAULT_FAMILY_WEIGHTS.get(r) or DEFAULT_FAMILY_WEIGHTS["UNKNOWN"]
    return {fam: float(base.get(fam, 1.0)) for fam in KNOWN_FAMILIES}


def _families_present(phase_chain: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    """phase_chain anahtarlarından (faz71, phase50, …) aile sayımı."""
    out: Dict[str, int] = {}
    if not isinstance(phase_chain, Mapping):
        return out
    for key in phase_chain.keys():
        pid = phase_key_to_int(str(key))
        fam = "other" if pid is None else family_for_phase_num(int(pid))
        out[fam] = out.get(fam, 0) + 1
    return out


def _weighted_mean(weights: Mapping[str, float], counts: Mapping[str, int]) -> Optional[float]:
    """Aile sayım ağırlıklı ortalama; sayım toplam 0 ise ``None``."""
    total = sum(int(c) for c in counts.values())
    if total <= 0:
        return None
    s = 0.0
    for fam, c in counts.items():
        s += float(weights.get(fam, 1.0)) * int(c)
    return s / float(total)


def compute_meta_regime(
    analysis: Optional[Mapping[str, Any]],
    phase_chain: Optional[Mapping[str, Any]],
    *,
    base_confidence: float,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Saf fonksiyon (side-effect yok): meta_regime payload üretir.

    ``applied=True`` yalnızca ``mode='advisory'`` ve güven değişimi anlamlı ise.
    """
    eff_mode = _resolve_mode(mode)

    regime_raw = analysis.get("omega_regime") if isinstance(analysis, Mapping) else None
    regime = normalize_regime(regime_raw)
    weights = family_weights_for_regime(regime)
    counts = _families_present(phase_chain or {})
    weighted = _weighted_mean(weights, counts)

    base = _clamp(base_confidence, 0.0, 1.0)
    advisory_min, advisory_max = _resolve_advisory_bounds()

    ack_ok, ack_path_checked = _advisory_measurement_ack_passes(eff_mode)
    advisory_blocked_reason: Optional[str] = None
    if eff_mode == "advisory" and not ack_ok:
        advisory_blocked_reason = "missing_measurement_ack_file"

    applied = False
    advised_mult = 1.0
    advised_conf = base

    apply_advisory = eff_mode == "advisory" and ack_ok and weighted is not None and base > 0.0
    if apply_advisory:
        advised_mult = _clamp(float(weighted), advisory_min, advisory_max)
        advised_conf = _clamp(base * advised_mult, 0.0, 1.0)
        applied = abs(advised_conf - base) > 1e-6

    delta = advised_conf - base
    payload: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "regime": regime,
        "regime_source": "omega_regime" if regime != "UNKNOWN" else "missing",
        "mode": eff_mode,
        "applied": bool(applied),
        "advisory_blocked_reason": advisory_blocked_reason,
        "measurement_ack_path": ack_path_checked,
        "family_weights": {k: round(weights[k], 4) for k in KNOWN_FAMILIES},
        "family_counts": {k: int(counts.get(k, 0)) for k in KNOWN_FAMILIES},
        "weighted_mult": round(float(weighted), 4) if weighted is not None else None,
        "advisory_bounds": [round(advisory_min, 4), round(advisory_max, 4)],
        "advised_confidence_mult": round(advised_mult, 4),
        "base_confidence": round(base, 4),
        "advised_confidence": round(advised_conf, 4),
        "summary": (f"reg={regime} mode={eff_mode} mult={advised_mult:.3f} d_conf={delta:+.3f}"),
    }
    return payload


def attach_meta_regime(
    analysis: Dict[str, Any],
    phase_chain: Optional[Mapping[str, Any]],
    *,
    base_confidence: float,
    mode: Optional[str] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    ``analysis["meta_regime"]`` yazar (off mod hariç) ve geçerli güven değerini döndürür.

    Dönüş: ``(effective_confidence, payload)`` — shadow modda ``effective_confidence``
    her zaman ``base_confidence`` ile aynıdır.
    """
    payload = compute_meta_regime(
        analysis=analysis,
        phase_chain=phase_chain,
        base_confidence=base_confidence,
        mode=mode,
    )
    if payload["mode"] != "off" and isinstance(analysis, dict):
        analysis[META_REGIME_KEY] = payload
    return float(payload["advised_confidence"]), payload


def compact_meta_regime_for_attribution(
    payload: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """A5 / TradeLogger için sadeleştirilmiş özet (BUY anı snapshot)."""
    if not isinstance(payload, Mapping):
        return None
    compact: Dict[str, Any] = {
        "schema": str(payload.get("schema", SCHEMA_VERSION)),
        "regime": str(payload.get("regime", "UNKNOWN")),
        "mode": str(payload.get("mode", "shadow")),
        "applied": bool(payload.get("applied", False)),
        "weighted_mult": payload.get("weighted_mult"),
        "advised_confidence_mult": payload.get("advised_confidence_mult"),
    }
    br = payload.get("advisory_blocked_reason")
    if br:
        compact["advisory_blocked_reason"] = str(br)
    mp = payload.get("measurement_ack_path")
    if br and mp:
        compact["measurement_ack_path"] = str(mp)
    return compact


def _cli_write_ack(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="PROMPT-A9 — advisory ölçüm onay dosyası oluşturur.")
    p.add_argument(
        "--path",
        default="",
        help="Yazılacak dosya (boşsa env / varsayılan sırası kullanılır).",
    )
    p.add_argument("--message", default="", help="İsteğe bağlı tek satır not (ör. A5 haftası).")
    args = p.parse_args(argv)
    written = write_meta_advisory_ack_file(
        path=(args.path or None),
        operator_note=args.message,
    )
    print(written)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    return _cli_write_ack(argv)


__all__ = (
    "SCHEMA_VERSION",
    "META_REGIME_KEY",
    "KNOWN_REGIMES",
    "KNOWN_FAMILIES",
    "DEFAULT_FAMILY_WEIGHTS",
    "DEFAULT_META_ADVISORY_ACK_RELPATH",
    "normalize_regime",
    "family_weights_for_regime",
    "advisory_ack_path_for_gate",
    "write_meta_advisory_ack_file",
    "compute_meta_regime",
    "attach_meta_regime",
    "compact_meta_regime_for_attribution",
)


if __name__ == "__main__":
    raise SystemExit(main())
