from __future__ import annotations

"""
SentimentLayer v7
─────────────────────────────────────────────────────────────────────────────
v6   → Haber duyarlılığı filtresi
v6.1 → FIX: Mock modda gereksiz cache güncellemesi giderildi.
v7   → FIX: Fallback sabit 0.5 yerine piyasa saatine göre dinamik skor.
             Asya seansı (02-08 UTC): 0.45 (hafif bearish)
             Avrupa seansı (08-14 UTC): 0.50 (nötr)
             ABD seansı (14-22 UTC): 0.55 (hafif bullish)
             Gece (22-02 UTC): 0.48 (düşük likidite, ihtiyatlı)
"""

import datetime
import logging
import os
import time
from typing import Dict, Optional, Tuple

log = logging.getLogger("super_otonom.sentiment")

_BEARISH_THRESHOLD = float(os.getenv("SENTIMENT_BEARISH_THRESHOLD", "0.3") or 0.3)
_BULLISH_THRESHOLD = float(os.getenv("SENTIMENT_BULLISH_THRESHOLD", "0.7") or 0.7)
_CACHE_TTL_SEC = int(os.getenv("SENTIMENT_CACHE_TTL", "300") or 300)


def _dynamic_fallback_score() -> float:
    """
    API erişilemediğinde sabit 0.5 yerine piyasa saatine göre dinamik skor.
    UTC saatine göre hangi seans aktif olduğunu belirler.

    Asya    02-08 UTC → 0.45 (ihtiyatlı, düşük likidite)
    Avrupa  08-14 UTC → 0.50 (nötr, piyasa açılışı)
    ABD     14-22 UTC → 0.55 (aktif seans, hafif bullish yanlı)
    Gece    22-02 UTC → 0.48 (düşük likidite, ihtiyatlı)
    """
    hour = datetime.datetime.now(datetime.timezone.utc).hour
    if 2 <= hour < 8:
        return 0.45
    elif 8 <= hour < 14:
        return 0.50
    elif 14 <= hour < 22:
        return 0.55
    else:
        return 0.48


try:
    import json as _json
    import urllib.request

    _HTTP_AVAILABLE = True
except ImportError:
    _HTTP_AVAILABLE = False


class SentimentLayer:
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        mock_score: Optional[float] = None,
    ):
        self._api_url = api_url or os.getenv("FEAR_GREED_API_URL", "")
        self._api_key = api_key or os.getenv("SENTIMENT_API_KEY", "")
        self._mock_score = mock_score

        # Önbellek — yalnızca gerçek API modu için
        self._cache: Optional[Dict] = None
        self._cache_ts: float = 0.0

    def _fetch_from_api(self) -> Optional[float]:
        if not self._api_url or not _HTTP_AVAILABLE:
            return None
        try:
            headers = {"Accept": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            req = urllib.request.Request(self._api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = _json.loads(resp.read().decode())
            if "data" in raw and raw["data"]:
                val = float(raw["data"][0].get("value", 50))
                return round(val / 100.0, 3)
            if "score" in raw:
                return float(raw["score"])
        except Exception as exc:
            log.warning("SentimentLayer: API hatasi — fallback kullanilacak. err=%s", exc)
        return None

    def get_market_sentiment(self) -> Dict:
        # FIX: Mock modda cache hiç kullanılmaz — saf hesaplama
        if self._mock_score is not None:
            score = float(self._mock_score)
            source = "mock"
            # Mock modda cache güncellemesi YAPILMAZ (önceki versiyonda gereksiz yapılıyordu)
        else:
            # Yalnızca gerçek API modunda TTL önbelleği kullan
            now = time.time()
            if self._cache and (now - self._cache_ts) < _CACHE_TTL_SEC:
                return dict(self._cache)

            api_score = self._fetch_from_api()
            if api_score is not None:
                score = max(0.0, min(1.0, api_score))
                source = "api"
            else:
                score = _dynamic_fallback_score()
                source = "fallback_dynamic"

        if score < _BEARISH_THRESHOLD:
            status = "BEARISH_PANIC"
        elif score > _BULLISH_THRESHOLD:
            status = "BULLISH_EUPHORIA"
        else:
            status = "NEUTRAL"

        result = {"score": round(score, 3), "status": status, "source": source}

        # FIX: Önbelleği YALNIZCA gerçek API modunda güncelle
        if self._mock_score is None:
            self._cache = result
            self._cache_ts = time.time()

        log.debug(
            "SentimentLayer: score=%.3f status=%s source=%s",
            score,
            status,
            source,
        )
        return result

    def validate_with_sentiment(
        self, signal: str, sentiment: Optional[Dict] = None
    ) -> Tuple[str, str]:
        if sentiment is None:
            sentiment = self.get_market_sentiment()

        status = sentiment.get("status", "NEUTRAL")
        score = sentiment.get("score", 0.5)

        if signal == "BUY" and status == "BEARISH_PANIC":
            reason = (
                f"NEWS_VETO: Piyasa panik modunda (score={score:.2f}) — "
                "BUY sinyali HOLD'a dönüştürüldü"
            )
            return "HOLD", reason

        if signal == "SELL" and status == "BULLISH_EUPHORIA":
            reason = (
                f"NEWS_VETO: Piyasa aşırı coşku modunda (score={score:.2f}) — "
                "SELL sinyali HOLD'a dönüştürüldü"
            )
            return "HOLD", reason

        reason = f"SENTIMENT_OK: status={status} score={score:.2f}"
        return signal, reason

    def set_mock_score(self, score: float) -> None:
        self._mock_score = max(0.0, min(1.0, float(score)))
        self._cache = None

    def clear_mock(self) -> None:
        self._mock_score = None
        self._cache = None

    def __repr__(self) -> str:
        return (
            f"SentimentLayer(api={'var' if self._api_url else 'yok'} "
            f"mock={self._mock_score} cache_ttl={_CACHE_TTL_SEC}s)"
        )
