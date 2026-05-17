from __future__ import annotations

"""
AsyncExchangeHandler v5
─────────────────────────────────────────────────────────────────────────────
Borsa soyutlama: OHLCV, order book, bakiye, emir durumu ccxt üzerinden.

**Borsa özgü davranış:** Rate limit ve hata kodları ccxt/exchange katmanında kalır;
bu sınıf CircuitBreaker + yeniden deneme ile sarar. Spot için ``fetch_positions``
çoğu borsada boş veya minimal döner; mutabakat (``ReconciliationEngine``) futures veya
margin pozisyonları için anlamlıdır — Binance dışı borsalar üretim öncesi testnet ile
doğrulanmalıdır (bkz. ``config.EXCHANGES`` uyarıları).

YENİLİKLER (v4 → v5):
  • CircuitBreaker sınıfı — art arda hatalar devre kesici açar
  • fetch_all_ohlcv → CircuitBreaker kontrolü ile koruma altında
  • Her sembol için ayrı CircuitBreaker instance (izolasyon)
  • circuit_breaker_status() → hangi semboller kapalı, raporlama
"""

import asyncio
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

from super_otonom.kill_switch import get_rate_limit_storm_tracker, is_ratelimit_error

log = logging.getLogger("super_otonom.exchange_async")


def _binance_testnet_env_enabled() -> bool:
    """Yalnızca ``BINANCE_TESTNET=true`` iken Binance demo (enable_demo_trading) kullanılır."""
    return os.getenv("BINANCE_TESTNET", "").strip().lower() in ("1", "true", "yes", "on")


def _use_aiohttp_default_resolver() -> bool:
    """
    Windows'ta aiohttp+aiodns sık DNS hatası verir; ``DefaultResolver`` ile sistem çözücüsü kullanılır.
    Diğer OS: ``SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER=1`` ile aynı yol zorlanabilir.
    """
    if sys.platform == "win32":
        return True
    return os.getenv("SUPER_OTONOM_AIOHTTP_DEFAULT_RESOLVER", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


async def _install_aiohttp_default_resolver_session(ex: Any) -> None:
    """ccxt async exchange için aiohttp oturumunu ``DefaultResolver`` ile yeniden kurar."""
    import ssl as ssl_mod

    import aiohttp

    from super_otonom.aiohttp_compat import aiohttp_trust_env, make_tcp_connector

    loop = asyncio.get_running_loop()
    if ex.asyncio_loop is None:
        ex.asyncio_loop = loop
    throttler = getattr(ex, "throttler", None)
    if throttler is not None:
        throttler.loop = loop

    if ex.ssl_context is None:
        ex.ssl_context = (
            ssl_mod.create_default_context(cafile=ex.cafile) if ex.verify else ex.verify
        )

    if ex.session is not None:
        await ex.session.close()
        ex.session = None
    if ex.tcp_connector is not None:
        await ex.tcp_connector.close()
        ex.tcp_connector = None

    ex.tcp_connector = make_tcp_connector(loop, ssl_context=ex.ssl_context)
    ex.session = aiohttp.ClientSession(
        loop=loop,
        connector=ex.tcp_connector,
        trust_env=aiohttp_trust_env(),
    )
    ex.own_session = True
    log.info(
        "ccxt aiohttp: ThreadedResolver + trust_env=%s ipv4_only=%s",
        aiohttp_trust_env(),
        os.getenv("SUPER_OTONOM_AIOHTTP_IPV4_ONLY", ""),
    )


# Binance demo (Kasım 2025+): ``set_sandbox_mode`` spot için testnet.binance.vision kullanır (kalkmış).
# ccxt: ``enable_demo_trading(True)`` → ``urls['api']`` = ``urls['demo']`` (demo-api / demo-fapi / demo-dapi).
# Not: ``urls['api'] = "https://.../api/v3"`` (tek string) ccxt binance.sign ile uyumsuzdur (dict şart).

try:
    import ccxt.async_support as ccxt_async

    _CCXT_AVAILABLE = True
except ImportError:
    ccxt_async = None  # type: ignore
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
        self.failures = 0
        self.threshold = failure_threshold
        self.recovery_time = recovery_time
        self.last_failure_time = 0.0
        self.is_open = False

    def record_failure(self) -> None:
        """Başarısız çağrı kaydet. Eşiğe ulaşıldıysa devreyi aç."""
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.threshold:
            if not self.is_open:
                log.warning(
                    "CircuitBreaker: %d art arda hata — devre AÇILDI, "
                    "%.0fs sonra tekrar denenecek.",
                    self.failures,
                    self.recovery_time,
                )
            self.is_open = True

    def record_success(self) -> None:
        """Başarılı çağrı: sayacı sıfırla, devre kapat."""
        if self.is_open:
            log.info("CircuitBreaker: başarılı çağrı — devre KAPATILDI.")
        self.failures = 0
        self.is_open = False

    def can_proceed(self) -> bool:
        """
        True  → çağrıya izin ver
        False → devre açık, çağrıyı engelle
        """
        if not self.is_open:
            return True
        # Recovery süresi geçtiyse HALF-OPEN: bir deneme izni ver
        if time.time() - self.last_failure_time > self.recovery_time:
            log.info("CircuitBreaker: recovery süresi doldu — HALF-OPEN, deneme izni veriliyor.")
            self.is_open = False  # Sonuç başarısızsa record_failure tekrar açar
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
        self.exchange_id = exchange_id
        self.testnet = testnet
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._ex: Any = None

        # CircuitBreaker ayarları (sembol başına oluşturulur)
        self._cb_threshold = cb_failure_threshold
        self._cb_recovery = cb_recovery_time
        self._breakers: Dict[str, CircuitBreaker] = {}

        if not _CCXT_AVAILABLE:
            log.warning("ccxt yok — AsyncExchangeHandler simule modda calisacak.")
            return

        api_key = str(api_key or "").strip().strip('"').strip("'")
        api_secret = str(api_secret or "").strip().strip('"').strip("'")

        config: Dict[str, Any] = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            # Proxy / sistem sertifikası; aiohttp için (ccxt async).
            "aiohttp_trust_env": True,
        }
        if extra_config:
            config.update(extra_config)

        if exchange_id == "binance":
            # Ana agda key olsa bile OHLCV icin sapi/capital zorunlu degil; yanlis/demo key ile kirilir.
            _opts = config.setdefault("options", {})
            _opts.setdefault("fetchCurrencies", False)

        exchange_cls = getattr(ccxt_async, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"AsyncExchangeHandler: bilinmeyen exchange '{exchange_id}'")

        self._ex = exchange_cls(config)
        if self._ex is not None:
            self._ex.aiohttp_trust_env = True

        _binance_demo = (
            exchange_id == "binance"
            and self._ex is not None
            and bool(testnet)
            and _binance_testnet_env_enabled()
        )
        if _binance_demo:
            # Sandbox ile demo trading birlikte ccxt'te desteklenmez; demo URL'ler resmi yol.
            try:
                if hasattr(self._ex, "enable_demo_trading"):
                    self._ex.enable_demo_trading(True)
                    log.info(
                        "Binance testnet: ccxt enable_demo_trading — "
                        "exchangeInfo ve diger uclar demo-api / demo-fapi."
                    )
                else:
                    demo = self._ex.urls.get("demo")
                    if isinstance(demo, dict):
                        self._ex.urls["api"] = dict(demo)
                        self._ex.options["enableDemoTrading"] = True
                        log.info("Binance testnet: urls['demo'] -> urls['api'] (eski ccxt).")
                    else:
                        log.warning("Binance testnet: ccxt urls['demo'] yok — URL ayari atlandi.")
            except Exception as exc:
                log.warning("Binance demo URL ayari basarisiz: %s", exc)
        elif exchange_id == "binance" and bool(testnet) and not _binance_testnet_env_enabled():
            log.info(
                "Binance: testnet bayragi acik ama BINANCE_TESTNET env kapali — "
                "canli spot API (api.binance.com) kullaniliyor."
            )
        elif testnet and exchange_id != "binance" and hasattr(self._ex, "set_sandbox_mode"):
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
                breaker.record_success()  # Başarı → sayacı sıfırla
                get_rate_limit_storm_tracker().on_success()
                return data
            except Exception as exc:
                last_err = exc
                if is_ratelimit_error(exc):
                    get_rate_limit_storm_tracker().on_ratelimit()
                breaker.record_failure()  # Her hata CircuitBreaker'a bildir
                log.warning(
                    "fetch_ohlcv hata | symbol=%s attempt=%d/%d err=%s cb=%s",
                    symbol,
                    attempt,
                    self.max_retries,
                    exc,
                    breaker.state,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * attempt)

        log.error(
            "fetch_ohlcv basarisiz | symbol=%s | son_hata=%s | cb=%s",
            symbol,
            last_err,
            breaker.state,
        )
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

    async def fetch_positions(
        self, symbols: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Açık pozisyonlar — ``ReconciliationEngine`` startup_handshake ile uyumlu.
        Spot rejiminde çoğu borsada boş liste döner; futures/margin için ccxt unified API.
        """
        if self._ex is None:
            return []
        try:
            if symbols:
                out: List[Dict[str, Any]] = []
                for sym in symbols:
                    chunk = await self._ex.fetch_positions([sym])
                    if chunk:
                        out.extend(chunk)
                get_rate_limit_storm_tracker().on_success()
                return out
            pos = await self._ex.fetch_positions()
            get_rate_limit_storm_tracker().on_success()
            return list(pos or [])
        except Exception as exc:
            if is_ratelimit_error(exc):
                get_rate_limit_storm_tracker().on_ratelimit()
            log.warning("fetch_positions hata | err=%s", exc)
            return []

    async def fetch_balance(self) -> Dict[str, Any]:
        """
        ccxt uyumlu bakiye (total.USDT) — ReconciliationEngine startup_handshake için.
        Simülasyon / ccxt yok: INITIAL_CAPITAL ile hizalı sahte bakiye (yanlış hard block önler).
        """
        if self._ex is None:
            try:
                u = float(os.getenv("INITIAL_CAPITAL", "1000"))
            except ValueError:
                u = 1000.0
            return {"total": {"USDT": u}}
        try:
            bal = await self._ex.fetch_balance()
            get_rate_limit_storm_tracker().on_success()
            return bal
        except Exception as exc:
            if is_ratelimit_error(exc):
                get_rate_limit_storm_tracker().on_ratelimit()
            log.warning("fetch_balance hata | err=%s", exc)
            raise

    # ── Emir gönderimi ─────────────────────────────────────────────────────

    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "limit",
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Borsaya emir gönderir.

        Args:
            symbol:     Çift ismi (BTC/USDT)
            side:       'buy' veya 'sell'
            amount:     Miktar (base currency)
            price:      Limit fiyatı (market order için None)
            order_type: 'limit' veya 'market'
            params:     Borsa özel parametreler (clientOrderId vb.)

        Dönüş: ccxt order dict
            {
                'id': '12345',
                'clientOrderId': 'so_xxx',
                'status': 'open'|'closed',
                'filled': 0.01,
                'average': 100000.0,
                'fee': {'cost': 0.1, 'currency': 'USDT'},
                ...
            }

        Raises:
            RuntimeError: ccxt yok veya exchange bağlantısı yok
            Exception: Borsa hatası (ccxt exception'ları)
        """
        if self._ex is None:
            raise RuntimeError("Exchange bağlantısı yok — ccxt başlatılmamış")

        params = params or {}
        side = side.lower()
        order_type = order_type.lower()

        log.info(
            "CREATE_ORDER | %s %s %s | qty=%.8f price=%s | params=%s",
            symbol, side, order_type, amount,
            f"{price:.6f}" if price else "MARKET",
            {k: v for k, v in params.items() if k != "clientOrderId"},
        )

        try:
            if order_type == "market":
                result = await self._ex.create_order(
                    symbol=symbol,
                    type="market",
                    side=side,
                    amount=amount,
                    params=params,
                )
            else:
                if price is None:
                    raise ValueError("Limit order için price gerekli")
                result = await self._ex.create_order(
                    symbol=symbol,
                    type="limit",
                    side=side,
                    amount=amount,
                    price=price,
                    params=params,
                )

            get_rate_limit_storm_tracker().on_success()

            status = result.get("status", "unknown")
            filled = float(result.get("filled", 0) or 0)
            avg_price = float(result.get("average", 0) or 0)
            fee_cost = float((result.get("fee") or {}).get("cost", 0))

            log.info(
                "ORDER_RESULT | %s %s | id=%s | status=%s | filled=%.8f avg=%.6f fee=%.6f",
                symbol, side,
                result.get("id", "?"),
                status, filled, avg_price, fee_cost,
            )
            return result

        except Exception as exc:
            if is_ratelimit_error(exc):
                get_rate_limit_storm_tracker().on_ratelimit()
            log.error("CREATE_ORDER HATA | %s %s | err=%s", symbol, side, exc)
            raise

    async def fetch_order(
        self, order_id: str, symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        Borsadan emir detayını çeker (fill, status, fee).
        OrderEngine recovery ve fill takibi için.
        """
        if self._ex is None:
            return None
        try:
            result = await self._ex.fetch_order(order_id, symbol)
            get_rate_limit_storm_tracker().on_success()
            return result
        except Exception as exc:
            if is_ratelimit_error(exc):
                get_rate_limit_storm_tracker().on_ratelimit()
            log.warning("fetch_order hata | order_id=%s symbol=%s err=%s", order_id, symbol, exc)
            return None

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
            log.warning(
                "get_order_status hata | order_id=%s symbol=%s err=%s", order_id, symbol, exc
            )
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
            log.warning("cancel_order hata | order_id=%s symbol=%s err=%s", order_id, symbol, exc)
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
        _ex = getattr(self, "_ex", None)
        if _ex is not None and _CCXT_AVAILABLE and _use_aiohttp_default_resolver():
            try:
                await _install_aiohttp_default_resolver_session(_ex)
            except Exception as exc:
                log.warning("aiohttp DefaultResolver kurulumu atlandi: %s", exc)

        # Binance imzali istekler: yerel saat sunucudan ilerideyse -1021; ccxt timeDifference ile düzelt.
        if _ex is not None and self.exchange_id == "binance":
            try:
                await _ex.load_time_difference()
                skew_ms = _ex.options.get("timeDifference")
                log.info("Binance load_time_difference | skew_ms=%s", skew_ms)
                if skew_ms is not None:
                    try:
                        from super_otonom.ops_metrics import record_clock_skew

                        record_clock_skew(self.exchange_id, int(skew_ms))
                    except Exception:
                        pass
            except Exception as exc:
                log.warning("Binance load_time_difference atlandi: %s", exc)

        # Binance demo URL'leri doğrulamak için erken exchangeInfo (diğer venue'lerde ccxt lazy yükler).
        if (
            _ex is not None
            and self.exchange_id == "binance"
            and self.testnet
            and _binance_testnet_env_enabled()
        ):
            try:
                await _ex.load_markets()
                log.info(
                    "Binance testnet load_markets tamam | markets=%d",
                    len(getattr(_ex, "markets", {}) or {}),
                )
            except Exception as exc:
                log.error("Binance testnet load_markets hatasi: %s", exc)
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
        candles.append(
            {
                "timestamp": float(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
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
