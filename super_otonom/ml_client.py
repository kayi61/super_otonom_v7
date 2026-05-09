"""
ML Service Wrapper — dış sinir ağı (HTTP JSON POST).

- gRPC/Unix soket: aynı arayüzle `MLClient` alt sınıfı veya `fetch_inference` içi
  protokol dalı eklenebilir (ortak `MLInferenceResult`).
- Hata/timeout: `analysis` içinde `ml_score` set edilmez → `blend_omega_confidence` no_external_ml.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple

if TYPE_CHECKING:
    from super_otonom.decision_context import DecisionContext

log = logging.getLogger("super_otonom.ml_client")


@dataclass
class MLInferenceResult:
    """Dış servis cevabı (normalize)."""

    score: Optional[float]  # 0-1, blend için
    raw: Dict[str, Any]
    latency_ms: float
    error: Optional[str] = None


def format_ml_inference_payload(symbol: str, analysis: Dict[str, Any], *, tick_id: int = 0) -> Dict[str, Any]:
    """
    MarketAnalyzer + zenginleştirme alanlarını dış servise uygun hafif JSON.
    (Büyük OHLCV dizisi yok; sadece özet sayılar — bant genişliği dostu.)
    """
    a = analysis or {}
    return {
        "schema":    "super_otonom.ml.inference.v1",
        "symbol":    symbol,
        "tick_id":   int(tick_id),
        "signal":    str(a.get("signal", "HOLD")),
        "regime":    str(a.get("regime", "NOISY")),
        "hurst":     float(a.get("hurst", 0.5) or 0.5),
        "volatility": float(a.get("volatility", 0.02) or 0.02),
        "rsi":       float(a.get("rsi", 50.0) or 50.0),
        "bb_pct_b":  float(a.get("bb_pct_b", 0.5) or 0.5),
        "ema_diff":  float(a.get("ema_diff", 0.0) or 0.0),
        "vol_ratio": float(a.get("vol_ratio", 1.0) or 1.0),
        "flash_crash": bool(a.get("flash_crash", False)),
        "high_tf_trend": a.get("high_tf_trend"),
        "mtf_filtered": bool(a.get("mtf_filtered", False)),
        "liquidity_ratio": a.get("liquidity_ratio"),
        "entry_scale":   str(a.get("entry_scale", "unknown") or "unknown"),
        "ob_safe_size":  a.get("ob_safe_size"),
        "quality_score": a.get("quality_score"),
    }


class MLClient:
    """
    Asenkron dış ML çağrısı. ML_SERVICE_URL yok veya enabled=false → no-op.
    """

    def __init__(
        self,
        service_url: str = "",
        timeout_sec: float = 2.0,
        enabled: bool = False,
    ) -> None:
        self._url = (service_url or "").strip()
        self._timeout = max(0.2, float(timeout_sec))
        self._enabled = bool(enabled) and bool(self._url)

    @classmethod
    def from_env(cls) -> "MLClient":
        url = os.getenv("ML_SERVICE_URL", "") or os.getenv("OMEGA_ML_SERVICE_URL", "")
        to  = float(os.getenv("ML_SERVICE_TIMEOUT", "2.0") or 2.0)
        en  = (os.getenv("ML_SERVICE_ENABLED", "false") or "false").lower() in (
            "1", "true", "yes", "on"
        )
        return cls(service_url=url, timeout_sec=to, enabled=en)

    def _parse_response_body(self, body: bytes) -> Dict[str, Any]:
        if not body:
            return {}
        try:
            d = json.loads(body.decode("utf-8", errors="replace"))
            return d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _sync_http_post(self, payload: Dict[str, Any]) -> Tuple[bytes, float]:
        t0 = time.perf_counter()
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            raw = resp.read()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return raw, elapsed_ms

    async def fetch_inference(
        self, symbol: str, analysis: Dict[str, Any], *, tick_id: int = 0
    ) -> MLInferenceResult:
        if not self._enabled:
            return MLInferenceResult(None, {}, 0.0, error="disabled")

        payload = format_ml_inference_payload(symbol, analysis, tick_id=tick_id)
        t0 = time.perf_counter()
        try:
            raw_b, lat_ms = await asyncio.to_thread(self._sync_http_post, payload)
            doc = self._parse_response_body(raw_b)
        except (OSError, ValueError) as e:
            log.debug("MLClient: cagri basarisiz | %s", e)
            el = (time.perf_counter() - t0) * 1000.0
            return MLInferenceResult(None, {}, el, error=type(e).__name__)

        sc = doc.get("score", doc.get("ml_score", doc.get("confidence")))
        if sc is None:
            return MLInferenceResult(None, doc, lat_ms, error="no_score_field")
        try:
            score = float(sc)
        except (TypeError, ValueError):
            return MLInferenceResult(None, doc, lat_ms, error="score_not_float")
        score = max(0.0, min(1.0, score))
        return MLInferenceResult(score, doc, lat_ms, error=None)

    async def enrich_analysis(
        self,
        symbol: str,
        analysis: Dict[str, Any],
        dctx: Optional["DecisionContext"] = None,
        *,
        tick_id: int = 0,
    ) -> None:
        """
        Başarılıysa analysis['ml_score'] ve gecikme yazar; hata/timeout: kilitlemez.
        dctx: external_ai_* ve [EXTERNAL-AI] log doldurur.
        """
        if not self._enabled:
            if dctx is not None:
                dctx.external_ai_log = "[EXTERNAL-AI] disabled_or_no_url"
            return

        res = await self.fetch_inference(symbol, analysis, tick_id=tick_id)
        if res.error or res.score is None:
            if dctx is not None:
                dctx.external_ai_latency_ms = res.latency_ms or None
                dctx.external_ai_confidence = None
                err = res.error or "unknown"
                dctx.external_ai_log = f"[EXTERNAL-AI] fallback no_external_ml err={err}"
            analysis.pop("ml_score", None)
            return

        analysis["ml_score"] = res.score
        analysis["external_ai_latency_ms"] = res.latency_ms
        if res.raw:
            analysis["ml_service_raw"] = {k: res.raw[k] for k in list(res.raw)[:20]}

        if dctx is not None:
            dctx.external_ai_latency_ms = res.latency_ms
            dctx.external_ai_confidence = float(res.score)
            dctx.external_ai_log = (
                f"[EXTERNAL-AI] ok latency_ms={res.latency_ms:.0f} "
                f"score={res.score:.4f}"
            )


_ml_default: Optional[MLClient] = None


def get_ml_client() -> MLClient:
    global _ml_default
    if _ml_default is None:
        _ml_default = MLClient.from_env()
    return _ml_default


def reset_ml_client_for_tests() -> None:
    global _ml_default
    _ml_default = None
