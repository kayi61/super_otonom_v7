from __future__ import annotations

"""
AsyncExchangeHandler v5
─────────────────────────────────────────────────────────────────────────────
YENİLİKLER (v4 → v5):
  • CircuitBreaker sınıfı — art arda hatalar devre kesici açar
  • fetch_all_ohlcv → CircuitBreaker kontrolü ile koruma altında
  • Her sembol için ayrı CircuitBreaker instance (izolasyon)
  • circuit_breaker_status() → hangi semboller kapalı, raporlama
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from super_otonom.kill_switch import get_rate_limit_storm_tracker, is_ratelimit_error

log = logging.getLogger("super_otonom.exchange_async")

try:
    import ccxt.async_support as ccxt_async
    _CCXT_AVAILABLE = True
except ImportError:
    ccxt_async = None          # type: ignore
    _CCXT_AVAILABLE = False
    log.warning("AsyncExchangeHandler: ccxt kurulu degil, simule mod aktif.")


# ─────────────────────────────────────────────────────────────────────────────
#  v5 YENİLİK: CircuitBreaker
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Devre Kesici — Art arda gelen hatalarda exchange çağrısını geçici olarak durdurur.

    Durum makinesi:
      CLOSED  → Normal çalışma (can_proceed=True)
      OPEN    → Devre açık, çağrılar engellenir (can_proceed=False)
      HALF    → Recovery bekleniyor; bir sonraki başarılı çağrıda CLOSED'a döner

    failure_threshold : Bu kadar art arda hata → devre açılır
    recovery_time     : Bu kadar saniye sonra HALF duruma geçilir (tekrar dener)
    """

    def __init__(self, failure_threshold: int = 5, recovery_time: float = 60.0):
        self.failures          = 0
        self.threshold         = failure_threshold
        self.recovery_time     = recovery_time
        self.last_failure_time = 0.0
        self.is_open           = False

    def record_failure(self) -> None:
        """Başarısız çağrı kaydet. Eşiğe ulaşıldıysa devreyi aç."""
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.threshold:
            if not self.is_open:
                log.warning(
                    "CircuitBreaker: %d art arda hata — devre AÇILDI, "
                    "%.0fs sonra tekrar denenecek.",
                    self.failures, self.recovery_time,
                )
            self.is_open = True

    def record_success(self) -> None:
        """Başarılı çağrı: sayacı sıfırla, devre kapat."""
        if self.is_open:
            log.info("CircuitBreaker: başarılı çağrı — devre KAPATILDI.")
        self.failures   = 0
        self.is_open    = False

    def can_proceed(self) -> bool:
        """
        True  → çağrıya izin ver
        False → devre açık, çağrıyı engelle
        """
        if not self.is_open:
            return True
        # Recovery süresi geçtiyse HALF-OPEN: bir deneme izni ver
        if time.time() - self.last_failure_time > self.recovery_time:
            log.info(
                "CircuitBreaker: recovery süresi doldu — HALF-OPEN, deneme izni veriliyor."
            )
            self.is_open = False   # Sonuç başarısızsa record_failure tekrar açar
            self.failures = max(0, self.failures - 1)
            return True
        return False

    @property
    def state(self) -> str:
        if self.is_open:
            remaining = self.recovery_time - (time.time() - self.last_failure_time)
            return f"OPEN (recovery={max(0.0, remaining):.0f}s kaldı)"
        if self.failures > 0:
            return f"HALF-OPEN (hatalar={self.failures}/{self.threshold})"
        return "CLOSED"


# ─────────────────────────────────────────────────────────────────────────────
#  Ana Exchange Handler
# ─────────────────────────────────────────────────────────────────────────────

class AsyncExchangeHandler:
    """
    v5 — Paralel çok-parite OHLCV çekici + CircuitBreaker koruması.

    Özellikler:
    - Tüm sembolleri aynı anda (asyncio.gather) çeker → hız
    - Her sembol için bağımsız CircuitBreaker — bir sembol devreyi bozmaz
    - Başarısız sembollerde devre açık → gereksiz retry bant genişliği tüketmez
    - Hata izolasyonu: bir sembol başarısız olsa diğerleri etkilenmez
    - Otomatik yeniden deneme (retry) desteği
    - Rate-limit farkındalığı: exchange.rateLimit sırasına saygı
    - ccxt yoksa veya testnet modunda sahte veri üretir (Paper Trading uyumu)
    """

    def __init__(
        self,
        exchange_id: str,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        extra_config: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        cb_failure_threshold: int = 5,
        cb_recovery_time: float = 60.0,
    ):
        self.exchange_id  = exchange_id
        self.testnet      = testnet
        self.max_retries  = max_retries
        self.retry_delay  = retry_delay
        self._ex: Any     = None

        # CircuitBreaker ayarları (sembol başına oluşturulur)
        self._cb_threshold    = cb_failure_threshold
        self._cb_recovery     = cb_recovery_time
        self._breakers: Dict[str, CircuitBreaker] = {}

        if not _CCXT_AVAILABLE:
            log.warning("ccxt yok — AsyncExchangeHandler simule modda calisacak.")
            return

        config: Dict[str, Any] = {
            "apiKey":    api_key,
            "secret":    api_secret,
            "enableRateLimit": True,
        }
        if extra_config:
            config.update(extra_config)

        exchange_cls = getattr(ccxt_async, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"AsyncExchangeHandler: bilinmeyen exchange '{exchange_id}'")

        self._ex = exchange_cls(config)

        if testnet and hasattr(self._ex, "set_sandbox_mode"):
            self._ex.set_sandbox_mode(True)

    def _get_breaker(self, symbol: str) -> CircuitBreaker:
        """Sembol için CircuitBreaker instance'ını döndür; yoksa oluştur."""
        if symbol not in self._breakers:
            self._breakers[symbol] = CircuitBreaker(
                failure_threshold=self._cb_threshold,
                recovery_time=self._cb_recovery,
            )
        return self._breakers[symbol]

    # ── Tek sembol çekici (retry + CircuitBreaker) ────────────────────────────

    async def _fetch_one(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> Any:
        """Tek sembol için CircuitBreaker + retry döngüsü."""
        breaker = self._get_breaker(symbol)

        # Devre açıksa — hemen boş dön, retry bile yapma
        if not breaker.can_proceed():
            log.debug("CircuitBreaker OPEN | symbol=%s | atlanıyor", symbol)
            return []

        if self._ex is None:
            return _fake_ohlcv(symbol, limit)

        last_err: Exception = RuntimeError("bilinmeyen hata")
        for attempt in range(1, self.max_retries + 1):
            try:
                data = await self._ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                breaker.record_success()   # Başarı → sayacı sıfırla
                get_rate_limit_storm_tracker().on_success()
                return data
            except Exception as exc:
                last_err = exc
                if is_ratelimit_error(exc):
                    get_rate_limit_storm_tracker().on_ratelimit()
                breaker.record_failure()   # Her hata CircuitBreaker'a bildir
                log.warning(
                    "fetch_ohlcv hata | symbol=%s attempt=%d/%d err=%s cb=%s",
                    symbol, attempt, self.max_retries, exc, breaker.state,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * attempt)

        log.error("fetch_ohlcv basarisiz | symbol=%s | son_hata=%s | cb=%s",
                  symbol, last_err, breaker.state)
        return last_err

    # ── Paralel çok-parite çekici ─────────────────────────────────────────────

    async def fetch_all_ohlcv(
        self,
        symbols: List[str],
        timeframe: str = "5m",
        limit: int = 150,
    ) -> Dict[str, Any]:
        """
        Tüm sembolleri asyncio.gather ile paralel çeker.
        CircuitBreaker açık semboller veri çekilmeden [] döner.

        Dönüş: {symbol: [[ts, o, h, l, c, v], ...] veya []}
        """
        tasks = [self._fetch_one(s, timeframe, limit) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        out: Dict[str, Any] = {}
        for sym, res in zip(symbols, results):
            if isinstance(res, Exception):
                log.error("fetch_all_ohlcv: %s icin veri alinamadi: %s", sym, res)
                out[sym] = []
            else:
                out[sym] = res

        return out

    # ── CircuitBreaker durum raporu ───────────────────────────────────────────

    def circuit_breaker_status(self) -> Dict[str, str]:
        """Tüm semboller için devre durumunu döndürür. Loglama/monitoring için."""
        return {sym: cb.state for sym, cb in self._breakers.items()}

    # ── Emir defteri çekici ───────────────────────────────────────────────────

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 20,
    ) -> Dict[str, List]:
        """
        Order book çeker — PositionSizer.calculate_with_slippage() için.
        ccxt yoksa boş yapı döner.
        """
        if self._ex is None:
            return {"asks": [], "bids": []}
        try:
            ob = await self._ex.fetch_order_book(symbol, limit=limit)
            get_rate_limit_storm_tracker().on_success()
            return {"asks": ob.get("asks", []), "bids": ob.get("bids", [])}
        except Exception as exc:
            if is_ratelimit_error(exc):
                get_rate_limit_storm_tracker().on_ratelimit()
            log.warning("fetch_order_book hata | symbol=%s err=%s", symbol, exc)
            return {"asks": [], "bids": []}

    # ── Emir yönetimi (OrderTracker için) ────────────────────────────────────

    async def get_order_status(self, order_id: str, symbol: str) -> str:
        """
        Emir durumunu sorgular.
        Dönüş: 'open', 'filled', 'canceled', 'unknown'
        """
        if self._ex is None:
            return "unknown"
        try:
            order = await self._ex.fetch_order(order_id, symbol)
            status = str(order.get("status", "unknown")).lower()
            # ccxt statüsleri: open, closed, canceled
            if status == "closed":
                return "filled"
            return status
        except Exception as exc:
            log.warning("get_order_status hata | order_id=%s symbol=%s err=%s",
                        order_id, symbol, exc)
            return "unknown"

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        Emri iptal eder. Başarılı iptal için True döner.
        ccxt yoksa veya hata varsa False döner.
        """
        if self._ex is None:
            return False
        try:
            await self._ex.cancel_order(order_id, symbol)
            log.info("cancel_order: iptal edildi | order_id=%s symbol=%s", order_id, symbol)
            return True
        except Exception as exc:
            log.warning("cancel_order hata | order_id=%s symbol=%s err=%s",
                        order_id, symbol, exc)
            return False

    # ── Yaşam döngüsü ─────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self._ex is not None:
            try:
                await self._ex.close()
            except Exception as exc:
                log.warning("AsyncExchangeHandler.close hata: %s", exc)
            finally:
                self._ex = None

    async def __aenter__(self) -> "AsyncExchangeHandler":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()


# ── OHLCV → candle dict dönüştürücü ──────────────────────────────────────────

def ohlcv_to_candles(raw: List[List[float]]) -> List[Dict[str, float]]:
    """
    ccxt'nin [[ts, o, h, l, c, v], ...] formatını
    analyzer.py'nin beklediği [{"open":..., "high":..., ...}] formatına çevirir.
    """
    candles = []
    for row in raw:
        if len(row) < 6:
            continue
        candles.append({
            "timestamp": float(row[0]),
            "open":      float(row[1]),
            "high":      float(row[2]),
            "low":       float(row[3]),
            "close":     float(row[4]),
            "volume":    float(row[5]),
        })
    return candles


# ── Simülasyon (ccxt olmadan test için) ───────────────────────────────────────

def _fake_ohlcv(symbol: str, limit: int) -> List[List[float]]:
    """Gerçek exchange olmadan unit test için basit sahte veri."""
    import random
    price = {"BTC/USDT": 65000.0, "ETH/USDT": 3500.0}.get(symbol, 100.0)
    ts = int(time.time() * 1000) - limit * 300_000
    out = []
    for _ in range(limit):
        o = price * (1 + random.uniform(-0.002, 0.002))
        h = o * (1 + random.uniform(0, 0.005))
        lo = o * (1 - random.uniform(0, 0.005))
        c = random.uniform(lo, h)
        v = random.uniform(1.0, 50.0)
        out.append([ts, o, h, lo, c, v])
        price = c
        ts += 300_000
    return out
