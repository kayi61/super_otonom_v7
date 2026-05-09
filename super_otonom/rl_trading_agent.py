"""
Faz 30 — RL ticaret ajanı (NumPy PPO-benzeri politika + 3 uzman ajan + koordinatör).

Girdi `market_data` (esnek dict):
- close | prices | ohlcv (kapanış sütunu)

Bileşenler:
- TinyPolicy: durum vektörü → logits (SELL/HOLD/BUY), softmax + entropi (belirsizlik)
- TrendAgent: kısa momentum / vol oranı
- MeanRevertAgent: son getiri vs dağılım uçları
- BreakoutAgent: volatilite rejimi + son getiri yüzdelikleri

Koordinatör: PPO oyu + 3 uzman oyu çoğunluk; beraberlikte PPO logits ağırlığı.

Özel kurallar:
- Uzmanlar anlaşmazsa güven düşer
- Dört oy da SELL → yüksek risk, BLOCK
- PPO yüksek entropi → WAIT, düşük alpha

Çıktı Faz 16–35 ile uyumlu; phase30 / faz30.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np

from super_otonom.standard_phase_output import attach_phase_alias

ScoreType = Literal["ALPHA", "RISK", "QUALITY"]
TradePermission = Literal["ALLOW", "BLOCK", "HALT"]
CoordAction = Literal["BUY", "HOLD", "SELL", "WAIT"]

_EPS = 1e-12
_MIN_CLOSES = 36
_POLICY_SEED = 42
_STATE_TAIL = 32


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


def _normalize(raw: Any) -> Dict[str, Any]:
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
    return np.diff(np.log(np.maximum(xs, _EPS))).astype(float)


def build_state_vector(ret: np.ndarray, tail: int) -> np.ndarray:
    """Son tail bar getiri + vol + momentum özeti (sabit 16 boyut)."""
    t = max(8, min(int(tail), int(ret.size)))
    seg = ret[-t:] if ret.size else np.zeros(1)
    vol = float(np.std(seg)) if seg.size else 0.0
    mom_short = float(np.mean(seg[-min(8, seg.size) :])) if seg.size else 0.0
    mom_long = float(np.mean(seg)) if seg.size else 0.0
    pad = 13
    feat = np.zeros(pad + 3, dtype=float)
    take = min(pad, seg.size)
    if take > 0:
        feat[:take] = seg[-take:]
    feat[pad] = vol
    feat[pad + 1] = mom_short
    feat[pad + 2] = mom_long
    return feat


def softmax(x: np.ndarray) -> np.ndarray:
    z = x - np.max(x)
    e = np.exp(np.clip(z, -40.0, 40.0))
    return e / np.maximum(np.sum(e), _EPS)


def entropy_probs(p: np.ndarray) -> float:
    p = np.maximum(p, _EPS)
    p = p / np.sum(p)
    return float(-np.sum(p * np.log(p + _EPS)))


class TinyPPOPolicy:
    """İki katmanlı politika — sabit tohumlu ağırlıklar (eğitim yok, deterministik)."""

    def __init__(self, state_dim: int, rng: np.random.Generator) -> None:
        scale = 0.25 / math.sqrt(max(state_dim, 1))
        self.w1 = rng.normal(0.0, scale, size=(32, state_dim)).astype(float)
        self.b1 = rng.normal(0.0, 0.08, size=(32,)).astype(float)
        self.w2 = rng.normal(0.0, scale, size=(3, 32)).astype(float)
        self.b2 = rng.normal(0.0, 0.06, size=(3,)).astype(float)

    def forward(self, s: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        h = np.tanh(self.w1 @ s + self.b1)
        logits = self.w2 @ h + self.b2
        probs = softmax(logits)
        ent = entropy_probs(probs)
        return logits, probs, ent


def vote_from_probs(probs: np.ndarray) -> int:
    """0=SELL, 1=HOLD, 2=BUY → -1,0,1."""
    return int(np.argmax(probs) - 1)


def agent_trend(ret: np.ndarray) -> int:
    if ret.size < 10:
        return 0
    seg = ret[-min(16, ret.size) :]
    sig = float(np.std(seg)) + _EPS
    z = float(np.mean(seg[-8:])) / sig
    if z > 0.38:
        return 1
    if z < -0.38:
        return -1
    return 0


def agent_mean_revert(ret: np.ndarray) -> int:
    if ret.size < 12:
        return 0
    seg = ret[-min(24, ret.size) :]
    mu = float(np.mean(seg))
    sd = float(np.std(seg)) + _EPS
    last = float(seg[-1])
    if last < mu - 1.15 * sd:
        return 1
    if last > mu + 1.15 * sd:
        return -1
    return 0


def agent_breakout(ret: np.ndarray) -> int:
    if ret.size < 24:
        return 0
    short = ret[-10:]
    long = ret[:-10] if ret.size > 10 else ret[: max(6, ret.size // 2)]
    if long.size < 6:
        return 0
    vol_s = float(np.std(short))
    vol_l = float(np.std(long)) + _EPS
    ratio = vol_s / vol_l
    last = float(short[-1])
    hi_q = float(np.percentile(long, 93))
    lo_q = float(np.percentile(long, 7))
    if ratio > 1.32 and last > hi_q:
        return 1
    if ratio > 1.32 and last < lo_q:
        return -1
    return 0


def action_to_label(a: int) -> str:
    return "SELL" if a == -1 else ("HOLD" if a == 0 else "BUY")


def majority_vote(
    votes: List[int],
    tie_logits: np.ndarray,
) -> Tuple[int, float]:
    """
    Oy çoğunluğu; beraberlikte softmax logits ile kırılır.
    Dönüş: işaret (-1,0,1), anlaşmazlık [0,1].
    """
    if not votes:
        return 0, 1.0
    counts = {-1: 0, 0: 0, 1: 0}
    for v in votes:
        if v in counts:
            counts[v] += 1
    mx = max(counts.values())
    cand = [k for k, c in counts.items() if c == mx]
    if len(cand) == 1:
        winner = cand[0]
    else:
        # tie-break: PPO logits öncelik SELL,HOLD,BUY sırası idx 0,1,2
        alt = [tie_logits[0], tie_logits[1], tie_logits[2]]
        winner = int(np.argmax(alt)) - 1
    # anlaşmazlık: oy dağılımının normalize entropisi
    tot = sum(counts.values())
    ps = np.array([counts[k] / max(tot, 1) for k in (-1, 0, 1)], dtype=float)
    ps = np.maximum(ps, _EPS)
    ps = ps / np.sum(ps)
    disagree = float(-np.sum(ps * np.log(ps + _EPS)) / math.log(3.0))
    return winner, _clamp01(disagree)


def analyze_rl_agent(
    symbol: str,
    market_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 52_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """
    RL / çoklu ajan özeti; `analysis['phase30']` / `['faz30']` yazar.
    """
    _ = symbol
    a = analysis if analysis is not None else {}
    ts = int(event_ts) if event_ts is not None else _try_ts_ms(a)
    d = _normalize(market_data)

    if not d:
        payload = _empty_phase30(ts, half_life_ms, "no_market_data")
        if attach_to_analysis:
            attach_phase_alias(a, "30", payload)
        return payload

    closes_list = _extract_close_series(d)
    if len(closes_list) < _MIN_CLOSES:
        payload = _empty_phase30(ts, half_life_ms, "insufficient_bars")
        if attach_to_analysis:
            attach_phase_alias(a, "30", payload)
        return payload

    ret = log_returns(closes_list)
    if ret.size < 16:
        payload = _empty_phase30(ts, half_life_ms, "returns_too_short")
        if attach_to_analysis:
            attach_phase_alias(a, "30", payload)
        return payload

    tail = int(d.get("state_window") or d.get("lookback") or _STATE_TAIL)
    state = build_state_vector(ret, tail)
    rng = np.random.default_rng(_POLICY_SEED)
    pol = TinyPPOPolicy(state.size, rng)
    logits, probs, ent_raw = pol.forward(state)
    ppo_vote = vote_from_probs(probs)
    ent_norm = _clamp01(ent_raw / math.log(3.0))
    max_p = float(np.max(probs))

    v_trend = agent_trend(ret)
    v_mr = agent_mean_revert(ret)
    v_bo = agent_breakout(ret)

    votes_all = [ppo_vote, v_trend, v_mr, v_bo]
    maj, disagree_three = majority_vote(votes_all, logits)

    # Uzman üçlü anlaşmazlığı (trend, mr, bo)
    tri = [v_trend, v_mr, v_bo]
    tc = { -1: tri.count(-1), 0: tri.count(0), 1: tri.count(1)}
    pt = np.array([tc[-1], tc[0], tc[1]], dtype=float) / 3.0
    pt = np.maximum(pt, _EPS)
    pt /= np.sum(pt)
    disagree_experts = float(-np.sum(pt * np.log(pt + _EPS)) / math.log(3.0))

    sell_all = all(v == -1 for v in votes_all)
    # Belirsiz politika: neredeyse düzgün softmax (max olasılık çok düşük)
    ppo_uncertain = max_p < 0.34

    coord_action: CoordAction
    if ppo_uncertain:
        coord_action = "WAIT"
        maj_eff = 0
    else:
        maj_eff = maj
        coord_action = action_to_label(maj_eff)  # type: ignore[assignment]

    risk_01 = _clamp01(
        0.28 * float(sum(1 for v in votes_all if v == -1) / 4.0)
        + 0.26 * disagree_three
        + 0.22 * disagree_experts
        + 0.14 * ent_norm
        + 0.10 * (1.0 if sell_all else 0.0)
    )
    if sell_all:
        risk_01 = _clamp01(max(risk_01, 0.82))

    alpha_01 = _clamp01(
        (0.35 * float(sum(1 for v in votes_all if v == 1) / 4.0))
        + 0.28 * (1.0 - ent_norm)
        + 0.22 * (1.0 - disagree_three)
        + 0.15 * (1.0 - disagree_experts)
    )
    if ppo_uncertain or coord_action == "WAIT":
        alpha_01 = _clamp01(alpha_01 * 0.32)

    conf_base = _clamp01(
        0.24 + 0.38 * (1.0 - disagree_three) + 0.22 * (1.0 - disagree_experts) + 0.16 * (1.0 - ent_norm)
    )
    conf = _clamp01(conf_base * (0.42 + 0.58 * (1.0 - disagree_experts)))

    dh = _clamp01(
        0.27 + 0.33 * (1.0 - ent_norm) + 0.22 * (1.0 - disagree_three) + 0.18 * min(1.0, ret.size / 96.0)
    )

    perm: TradePermission = "ALLOW"
    if sell_all:
        perm = "BLOCK"
    elif risk_01 >= 0.88:
        perm = "BLOCK"
    elif risk_01 >= 0.72:
        perm = "BLOCK"

    st = _pick_score_type(dh, risk_01)

    payload: Dict[str, Any] = {
        "trade_permission": perm,
        "alpha_score": float(alpha_01),
        "risk_score": float(risk_01),
        "confidence": float(conf),
        "data_health": float(dh),
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": st,
        "phase": "30",
        "source": "rl_trading_agent",
        "rl_agent": {
            "coordinated_action": coord_action,
            "ppo_entropy_normalized": float(ent_norm),
            "ppo_policy_uncertain": bool(ppo_uncertain),
            "votes": {
                "ppo": int(ppo_vote),
                "trend": int(v_trend),
                "mean_revert": int(v_mr),
                "breakout": int(v_bo),
            },
            "ppo_action": int(ppo_vote),
            "expert_votes": {
                "trend": int(v_trend),
                "mean_revert": int(v_mr),
                "breakout": int(v_bo),
            },
            "vote_labels": {k: action_to_label(v) for k, v in zip(("ppo", "trend", "mean_revert", "breakout"), votes_all)},
            "majority_vote_sign": int(maj_eff),
            "disagreement_all": float(disagree_three),
            "disagreement_experts": float(disagree_experts),
            "all_sell": bool(sell_all),
            "bars_used": int(ret.size),
        },
    }

    if attach_to_analysis:
        attach_phase_alias(a, "30", payload)

    return payload


def run_rl_agent_phase(
    symbol: str,
    market_data: Any,
    analysis: Optional[Dict[str, Any]] = None,
    *,
    attach_to_analysis: bool = True,
    half_life_ms: int = 52_000,
    event_ts: Optional[int] = None,
) -> Dict[str, Any]:
    """Pipeline girişi — `analyze_rl_agent` ile aynı."""
    return analyze_rl_agent(
        symbol,
        market_data,
        analysis,
        attach_to_analysis=attach_to_analysis,
        half_life_ms=half_life_ms,
        event_ts=event_ts,
    )


def _empty_phase30(ts: int, half_life_ms: int, reason: str) -> Dict[str, Any]:
    return {
        "trade_permission": "BLOCK",
        "alpha_score": 0.0,
        "risk_score": 1.0,
        "confidence": 0.0,
        "data_health": 0.0,
        "event_ts": float(ts),
        "half_life_ms": int(half_life_ms),
        "score_type": "QUALITY",
        "phase": "30",
        "source": "rl_trading_agent",
        "empty_reason": reason,
        "rl_agent": {},
    }
