"""
Faz 32 — Transformer-benzeri dikkat analizi (saf NumPy, PyTorch yok).

Girdi `price_data` (esnek dict):
- close | prices | mid — kapanış / işlem fiyatı dizisi
- veya ohlcv: [[ts,o,h,l,c,v], ...] (kapanış sütunu kullanılır)

İçerik:
- Patch tabanlı öz-gömüller üzerinde ölçekli çarpım-dikkat (Q,K,V projeksiyonları deterministik tohumla)
- TemporalGate: son yarım patch’ler (kısa) ile ilk yarım (uzun) özeti harmanlar
- Direction score: dikkat+ağırlıklı momentum ile UP / DOWN / NEUTRAL
- Dikkat düzlüğü (yüksek entropi) → düşük güven

Çıktı Faz 16–31 ile uyumlu; phase32 / faz32.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]
DirectionLabel = Literal["UP", "DOWN", "NEUTRAL"]

_EPS = 1e-12
_SEED = 42
_MIN_CLOSES = 36


def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp01(x: float) -> float:
    if x != x:
        return 0.0
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


def _try_ts_ms(analysis: Dict[str, Any]) -> int:
    v = analysis.get("event_ts") or analysis.get("candle_ts")
    try:
        if v is None:
            return _now_ms()
        fv = float(v)
        if fv < 1e11:
            return int(fv * 1000.0)
        return int(fv)
    except (TypeError, ValueError):
        return _now_ms()


def _pick_score_type(data_health: float, risk_01: float) -> ScoreType:
    if data_health < 0.42:
        return "QUALITY"
    if risk_01 >= 0.72:
        return "RISK"
    return "ALPHA"


def _normalize_price_dict(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return dict(raw)


def _extract_close_series(d: Dict[str, Any]) -> List[float]:
    for key in ("close", "prices", "price", "mid", "last"):
        v = d.get(key)
        if isinstance(v, (list, tuple)) and len(v) >= _MIN_CLOSES:
            out: List[float] = []
            for x in v:
                try:
                    fv = float(x)
                    if fv == fv and fv > 0:
                        out.append(fv)
                except (TypeError, ValueError):
                    continue
            if len(out) >= _MIN_CLOSES:
                return out

    ohlcv = d.get("ohlcv") or d.get("candles") or d.get("klines")
    if isinstance(ohlcv, list) and len(ohlcv) >= _MIN_CLOSES:
        closes: List[float] = []
        for row in ohlcv:
            if isinstance(row, (list, tuple)) and len(row) >= 5:
                try:
                    c = float(row[4])
                    if c == c and c > 0:
                        closes.append(c)
                except (TypeError, ValueError):
                    continue
        if len(closes) >= _MIN_CLOSES:
            return closes

    return []


def log_returns(closes: Sequence[float]) -> np.ndarray:
    xs = np.asarray(closes, dtype=float)
    if xs.size < 3:
        return np.array([])
    r = np.diff(np.log(np.maximum(xs, _EPS)))
    return r.astype(float)


def _reshape_patches(ret: np.ndarray, num_patches: int = 8) -> Tuple[np.ndarray, int, int]:
    """Log-getiriyi P patch'e böler; gömü boyutu d."""
    n = int(ret.size)
    if n < 8:
        return np.array([]), 0, 0
    p = max(2, min(num_patches, n // 4))
    patch_len = max(2, n // p)
    rows: List[np.ndarray] = []
    for i in range(p):
        sl = ret[i * patch_len : (i + 1) * patch_len]
        if sl.size < 2:
            continue
        z = sl.astype(float)
        sig = float(np.std(z))
        if sig > _EPS:
            z = (z - np.mean(z)) / sig
        else:
            z = z * 0.0
        rows.append(z)
    if len(rows) < 2:
        return np.array([]), 0, 0
    d_max = max(r.size for r in rows)
    d = int(min(16, max(4, d_max)))
    E = np.zeros((len(rows), d), dtype=float)
    for i, row in enumerate(rows):
        take = min(row.size, d)
        E[i, :take] = row[:take]
    return E, d, patch_len


def _rng_matrices(d: int, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Deterministik küçük projeksiyonlar (Xavier tarzı ölçek)."""
    scale = math.sqrt(2.0 / max(d, 1))
    wq = rng.normal(0.0, scale, size=(d, d)).astype(float)
    wk = rng.normal(0.0, scale, size=(d, d)).astype(float)
    wv = rng.normal(0.0, scale, size=(d, d)).astype(float)
    return wq, wk, wv


def softmax_rows(x: np.ndarray) -> np.ndarray:
    """Satır bazlı softmax (her satır anahtar dağılımı)."""
    if x.size == 0:
        return x
    x = x - np.max(x, axis=-1, keepdims=True)
    ex = np.exp(np.clip(x, -42.0, 42.0))
    s = np.sum(ex, axis=-1, keepdims=True)
    return ex / np.maximum(s, _EPS)


def patch_self_attention(E: np.ndarray, rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """
    Ölçekli dot-product dikkat.
    Dönüş: A (P,P) satır-normalize dikkat, ctx (P,d) = A @ V.
    """
    p, d = E.shape
    if p < 2 or d < 2:
        return np.zeros((p, p)), np.zeros((p, d))
    wq, wk, wv = _rng_matrices(d, rng)
    q = E @ wq
    k = E @ wk
    v = E @ wv
    scale = 1.0 / math.sqrt(float(d))
    scores = (q @ k.T) * scale
    a = softmax_rows(scores)
    ctx = a @ v
    return a.astype(float), ctx.astype(float)


def attention_entropy_flatness(attn: np.ndarray) -> Tuple[float, float]:
    """
    Ortalama satır entropisi ve [0,1] düzlük (1 = tam düz/uniform).
    """
    if attn.size == 0:
        return 0.0, 1.0
    p = attn.shape[0]
    ent = 0.0
    for i in range(p):
        row = attn[i]
        row = np.maximum(row, _EPS)
        row = row / np.sum(row)
        ent += float(-np.sum(row * np.log(row + _EPS)))
    mean_ent = ent / max(1, p)
    max_ent = math.log(max(2, p))
    flat = _clamp01(mean_ent / max_ent if max_ent > _EPS else 1.0)
    return mean_ent, flat


def temporal_gate_blend(ctx: np.ndarray, attn: np.ndarray) -> Tuple[float, float]:
    """
    Son patch’ler = kısa vade, ilk patch’ler = uzun vade (zaman sırası).
    Kısa/uzun bağlam normlarından kapı skoru ve harmanlanmış özet vektörün normu.
    """
    p = ctx.shape[0]
    if p < 2:
        return 0.5, 0.0
    split = max(1, p // 2)
    short_ctx = ctx[split:]
    long_ctx = ctx[:split]
    s_norm = float(np.linalg.norm(short_ctx))
    l_norm = float(np.linalg.norm(long_ctx))
    # Gelen dikkat: sütun toplamları hangi patch'e odaklanılıyor
    col_sum = np.sum(attn, axis=0)
    col_sum = col_sum / max(_EPS, np.sum(col_sum))
    mass_short = float(np.sum(col_sum[split:]))
    mass_long = float(np.sum(col_sum[:split]))
    z = 1.8 * (mass_short - mass_long) + 0.12 * (s_norm - l_norm)
    gate = float(1.0 / (1.0 + math.exp(-z)))
    blended_norm = gate * s_norm + (1.0 - gate) * l_norm
    return gate, blended_norm


def direction_from_signals(
    ret: np.ndarray,
    pooled_vec: np.ndarray,
    gate: float,
) -> Tuple[DirectionLabel, float, float]:
    """
    UP/DOWN/NEUTRAL ve [-1,1] yön skoru; momentum gücü [0,1].
    """
    if ret.size < 4:
        return "NEUTRAL", 0.0, 0.0
    mom_short = float(np.mean(ret[-min(6, ret.size) :]))
    mom_mid = float(np.mean(ret[max(0, ret.size // 4) :]))
    pooled_scalar = float(np.mean(pooled_vec)) if pooled_vec.size else 0.0
    sig = float(np.std(ret)) + _EPS
    raw = 0.45 * (mom_short / sig) + 0.35 * (mom_mid / sig) + 0.20 * pooled_scalar
    raw *= 0.65 + 0.35 * gate
    strength = _clamp01(abs(raw) / 2.8)
    label: DirectionLabel
    if raw > 0.18:
        label = "UP"
    elif raw < -0.18:
        label = "DOWN"
    else:
        label = "NEUTRAL"
    score = float(max(-1.0, min(1.0, raw)))
    return label, score, strength


def analyze_transformer_intelligence(
    symbol: str,
    price_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 50_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Patch-dikkat özeti; `analysis['phase32']` / `['faz32']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d_in = _normalize_price_dict(price_data)

    if not d_in:
        payload = _empty_phase32(ts, half_life_ms, "no_price_data")
        if attach_to_analysis:
            attach_phase_alias(a, "32", payload)
        return payload

    closes = _extract_close_series(d_in)
    if len(closes) < _MIN_CLOSES:
        payload = _empty_phase32(ts, half_life_ms, "insufficient_bars")
        if attach_to_analysis:
            attach_phase_alias(a, "32", payload)
        return payload

    ret = log_returns(closes)
    if ret.size < 16:
        payload = _empty_phase32(ts, half_life_ms, "returns_too_short")
        if attach_to_analysis:
            attach_phase_alias(a, "32", payload)
        return payload

    num_patches = int(d_in.get("num_patches") or 8)
    E, d, patch_len = _reshape_patches(ret, num_patches=num_patches)
    if E.size == 0 or E.shape[0] < 2:
        payload = _empty_phase32(ts, half_life_ms, "patch_failed")
        if attach_to_analysis:
            attach_phase_alias(a, "32", payload)
        return payload

    rng = np.random.default_rng(_SEED)
    attn, ctx = patch_self_attention(E, rng)
    mean_ent, flat = attention_entropy_flatness(attn)
    gate, blend_norm = temporal_gate_blend(ctx, attn)

    pooled = np.mean(ctx, axis=0)
    label, dir_score, dir_strength = direction_from_signals(ret, pooled, gate)

    # Güçlü UP → yüksek alpha; güçlü DOWN → yüksek risk
    if label == "UP":
        alpha_01 = _clamp01(0.22 + 0.58 * dir_strength + 0.12 * (1.0 - flat) + 0.08 * gate)
    elif label == "DOWN":
        alpha_01 = _clamp01(0.18 + 0.08 * (1.0 - dir_strength))
    else:
        alpha_01 = _clamp01(0.28 + 0.18 * (1.0 - flat) + 0.08 * blend_norm)

    if label == "DOWN":
        risk_01 = _clamp01(0.24 + 0.52 * dir_strength + 0.14 * flat + 0.10 * (1.0 - gate))
    elif label == "UP":
        risk_01 = _clamp01(0.18 + 0.22 * flat + 0.18 * (1.0 - gate) + 0.12 * (1.0 - dir_strength))
    else:
        risk_01 = _clamp01(0.22 + 0.28 * flat + 0.18 * (1.0 - blend_norm * 0.05))

    # Düz dikkat → düşük güven
    conf_base = _clamp01(0.24 + 0.38 * (1.0 - flat) + 0.22 * dir_strength + 0.16 * gate)
    conf = _clamp01(conf_base * (0.35 + 0.65 * (1.0 - flat)))

    dh = _clamp01(
        0.26 + 0.34 * (1.0 - flat * 0.85) + 0.22 * min(1.0, ret.size / 120.0) + 0.18 * gate
    )

    perm: TradePermission = "ALLOW"
    if risk_01 >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    col_incoming = np.sum(attn, axis=0)
    col_incoming = col_incoming / max(_EPS, np.sum(col_incoming))
    focus_idx = int(np.argmax(col_incoming))

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": st,
        "phase": "32",
        "source": "transformer_intelligence",
        "transformer": {
            "direction": label,
            "direction_score": float(dir_score),
            "direction_strength": float(dir_strength),
            "temporal_gate_short_weight": float(gate),
            "attention_entropy_mean": float(mean_ent),
            "attention_uniformity": float(flat),
            "primary_focus_patch_index": focus_idx,
            "attention_column_weights": col_incoming.tolist(),
            "patch_count": int(E.shape[0]),
            "patch_length_bars": int(patch_len),
            "embedding_dim": int(d),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "32", payload)

    return payload


def run_transformer_phase(
    symbol: str,
    price_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 50_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_transformer_intelligence` ile aynı."""
    return analyze_transformer_intelligence(
        symbol,
        price_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase32(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "32",
        "source": "transformer_intelligence",
        "empty_reason": reason,
        "transformer": {},
    }
