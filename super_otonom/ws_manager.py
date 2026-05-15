from __future__ import annotations

"""
WebSocketManager v1.0
─────────────────────────────────────────────────────────────────────────────
Gerçek zamanlı kline veri akışı — Binance / OKX WebSocket.

Hibrit mimari:
    1. Başlangıçta REST ile son N mum çekilir (seed)
    2. WebSocket ile canlı kline güncellemesi alınır (gerçek zamanlı stream)
    3. Mum kapandığında candle buffer güncellenir
    4. main_loop callback ile REST ile aynı prep → tick yolu tetiklenir

Kullanım:
    ws = WebSocketManager(symbols=["BTC/USDT", "ETH/USDT"])
    ws.on_candle_close = async_callback  # mum kapandığında çağrılır
    await ws.start()
    candles = ws.get_candles("BTC/USDT")  # son 150 mum

Desteklenen borsalar:
    - Binance (mainnet + testnet)
    - OKX (mainnet)

Docker'da Go bridge Redis üzerinden de besleyebilir (fallback).
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List, Optional

log = logging.getLogger("super_otonom.ws_manager")

try:
    import aiohttp

    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False
    log.warning("aiohttp kurulu değil — WebSocket devre dışı")

# ── Config ──────────────────────────────────────────────────────────────

_EXCHANGE = os.getenv("DEFAULT_EXCHANGE", "binance").lower()
_TESTNET = os.getenv("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")
_WS_TIMEFRAME = os.getenv("WS_TIMEFRAME", "1h")
_CANDLE_BUFFER_SIZE = int(os.getenv("WS_CANDLE_BUFFER", "150"))
_RECONNECT_DELAY = 5  # saniye
_MAX_RECONNECT_DELAY = 60

# Binance WebSocket URL'leri
_BINANCE_WS = "wss://stream.binance.com:9443/stream?streams={streams}"
_BINANCE_WS_TESTNET = "wss://testnet.binance.vision/stream?streams={streams}"

# OKX WebSocket URL
_OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"

# Sembol format dönüşümü
_SYMBOL_MAP = {
    "BTC/USDT": "btcusdt",
    "ETH/USDT": "ethusdt",
    "BNB/USDT": "bnbusdt",
    "SOL/USDT": "solusdt",
}
_REVERSE_MAP = {v.upper(): k for k, v in _SYMBOL_MAP.items()}


def _ccxt_to_ws(symbol: str) -> str:
    """BTC/USDT → btcusdt"""
    return _SYMBOL_MAP.get(symbol, symbol.replace("/", "").lower())


def _ws_to_ccxt(symbol: str) -> str:
    """BTCUSDT → BTC/USDT"""
    return _REVERSE_MAP.get(symbol.upper(), symbol)


# ── Candle Buffer ───────────────────────────────────────────────────────

class CandleBuffer:
    """
    Sembol başına mum tamponu.
    REST ile seed edilir, WebSocket ile güncellenir.
    """

    def __init__(self, max_size: int = _CANDLE_BUFFER_SIZE):
        self._max_size = max_size
        self._candles: List[Dict[str, float]] = []
        self._current: Optional[Dict[str, float]] = None
        self._last_update: float = 0

    def seed(self, candles: List[Dict[str, float]]) -> None:
        """REST'ten gelen tarihi mumları yükle."""
        self._candles = candles[-self._max_size:]
        self._last_update = time.time()
        log.debug("CandleBuffer seed: %d mum yüklendi", len(self._candles))

    def update_live(self, candle: Dict[str, float], is_closed: bool) -> bool:
        """
        WebSocket'ten gelen canlı mum güncellemesi.
        Dönüş: True → mum kapandı (yeni mum eklendi)
        """
        self._last_update = time.time()

        if is_closed:
            # Mum kapandı — buffer'a ekle
            self._candles.append(candle)
            if len(self._candles) > self._max_size:
                self._candles = self._candles[-self._max_size:]
            self._current = None
            return True
        else:
            # Açık mum — sadece current güncelle
            self._current = candle
            return False

    def get_candles(self) -> List[Dict[str, float]]:
        """Tam mum listesi (kapanmış + açık)."""
        result = list(self._candles)
        if self._current:
            result.append(self._current)
        return result

    @property
    def last_update(self) -> float:
        return self._last_update

    @property
    def size(self) -> int:
        return len(self._candles)


# ── WebSocket Manager ──────────────────────────────────────────────────

class WebSocketManager:
    """
    Multi-exchange WebSocket yöneticisi.

    Özellikler:
        • Otomatik yeniden bağlanma (exponential backoff)
        • Candle buffer (REST seed + WS live update)
        • Mum kapandığında callback (event-driven tick)
        • Binance + OKX desteği
        • Graceful shutdown
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        exchange: str = _EXCHANGE,
        timeframe: str = _WS_TIMEFRAME,
    ):
        self.symbols = symbols or ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]
        self.exchange = exchange.lower()
        self.timeframe = timeframe
        self._buffers: Dict[str, CandleBuffer] = {
            s: CandleBuffer() for s in self.symbols
        }
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._reconnect_delay = _RECONNECT_DELAY
        self._msg_count = 0
        self._connected = False
        self._last_msg_time: float = 0

        # Callback: mum kapandığında çağrılır
        # async def on_close(symbol: str, candles: List[Dict]) -> None
        self.on_candle_close: Optional[
            Callable[[str, List[Dict[str, float]]], Coroutine]
        ] = None
        # Her başarılı kline mesajında (açık mum güncellemesi dahil) — heartbeat / canlılık
        self.on_activity: Optional[Callable[[], None]] = None

        log.info(
            "WebSocketManager hazır | exchange=%s timeframe=%s symbols=%s",
            self.exchange, self.timeframe, self.symbols,
        )

    # ── Seed (REST) ─────────────────────────────────────────────────────

    async def seed_from_exchange(self, handler: Any) -> int:
        """
        REST ile tarihi mumları çek ve buffer'lara yükle.
        handler: AsyncExchangeHandler instance
        Dönüş: yüklenen toplam mum sayısı.
        """
        from super_otonom.exchange_async import ohlcv_to_candles

        total = 0
        raw = await handler.fetch_all_ohlcv(
            symbols=self.symbols,
            timeframe=self.timeframe,
            limit=_CANDLE_BUFFER_SIZE,
        )

        for symbol in self.symbols:
            ohlcv = raw.get(symbol, [])
            if not ohlcv:
                log.warning("Seed: %s için veri yok", symbol)
                continue
            candles = ohlcv_to_candles(ohlcv)
            self._buffers[symbol].seed(candles)
            total += len(candles)
            log.info("Seed: %s → %d mum yüklendi", symbol, len(candles))

        return total

    # ── WebSocket Connection ────────────────────────────────────────────

    def _build_ws_url(self) -> str:
        """Exchange'e göre WebSocket URL oluştur."""
        if self.exchange == "okx":
            return _OKX_WS

        # Binance
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
        ws_tf = tf_map.get(self.timeframe, "1h")

        streams = "/".join(
            f"{_ccxt_to_ws(s)}@kline_{ws_tf}" for s in self.symbols
        )

        if _TESTNET:
            return _BINANCE_WS_TESTNET.format(streams=streams)
        return _BINANCE_WS.format(streams=streams)

    async def _subscribe_okx(self) -> None:
        """OKX için kanal aboneliği gönder."""
        if self._ws is None:
            return

        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "1d": "1D"}
        okx_tf = tf_map.get(self.timeframe, "1H")

        args = []
        for symbol in self.symbols:
            # BTC/USDT → BTC-USDT
            inst_id = symbol.replace("/", "-")
            args.append({
                "channel": f"candle{okx_tf}",
                "instId": inst_id,
            })

        msg = json.dumps({"op": "subscribe", "args": args})
        await self._ws.send_str(msg)
        log.info("OKX subscribe gönderildi: %d kanal", len(args))

    # ── Message Parsing ─────────────────────────────────────────────────

    def _parse_binance(self, raw: str) -> Optional[Dict[str, Any]]:
        """Binance kline mesajını parse et."""
        try:
            msg = json.loads(raw)
            data = msg.get("data", {})
            k = data.get("k", {})
            if not k:
                return None

            symbol = _ws_to_ccxt(k.get("s", ""))
            return {
                "symbol": symbol,
                "timestamp": k.get("t", 0),
                "open": float(k.get("o", 0)),
                "high": float(k.get("h", 0)),
                "low": float(k.get("l", 0)),
                "close": float(k.get("c", 0)),
                "volume": float(k.get("v", 0)),
                "is_closed": k.get("x", False),
            }
        except Exception as exc:
            log.debug("Binance parse hatası: %s", exc)
            return None

    def _parse_okx(self, raw: str) -> Optional[Dict[str, Any]]:
        """OKX kline mesajını parse et."""
        try:
            msg = json.loads(raw)
            if "data" not in msg or "arg" not in msg:
                return None

            arg = msg["arg"]
            inst_id = arg.get("instId", "")
            symbol = inst_id.replace("-", "/")

            data = msg["data"]
            if not data:
                return None

            candle = data[0]  # [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            return {
                "symbol": symbol,
                "timestamp": int(candle[0]),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5]),
                "is_closed": candle[8] == "1" if len(candle) > 8 else False,
            }
        except Exception as exc:
            log.debug("OKX parse hatası: %s", exc)
            return None

    def _parse_message(self, raw: str) -> Optional[Dict[str, Any]]:
        """Exchange'e göre mesaj parse et."""
        if self.exchange == "okx":
            return self._parse_okx(raw)
        return self._parse_binance(raw)

    # ── Main Loop ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """WebSocket bağlantısını başlat (otomatik yeniden bağlanma ile)."""
        if not _AIOHTTP_AVAILABLE:
            log.error("aiohttp yok — WebSocket başlatılamadı")
            return

        self._running = True
        log.info("WebSocket başlatılıyor: %s", self.exchange)

        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                log.info("WebSocket iptal edildi")
                break
            except Exception as exc:
                log.error("WebSocket hatası: %s — %ds sonra yeniden bağlanılacak",
                          exc, self._reconnect_delay)

            if self._running:
                try:
                    from super_otonom.ops_metrics import inc_ws_reconnect

                    inc_ws_reconnect()
                except Exception:
                    pass
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, _MAX_RECONNECT_DELAY
                )

    async def _connect_and_listen(self) -> None:
        """Tek bir bağlantı oturumu."""
        url = self._build_ws_url()
        log.info("WebSocket bağlanıyor: %s", url[:80])

        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                url, heartbeat=30, timeout=aiohttp.ClientTimeout(total=None)
            )
            self._connected = True
            self._reconnect_delay = _RECONNECT_DELAY
            log.info("WebSocket bağlantısı kuruldu!")

            # OKX için subscribe gönder
            if self.exchange == "okx":
                await self._subscribe_okx()

            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.error("WebSocket hata: %s", self._ws.exception())
                    break
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
                    log.warning("WebSocket kapatıldı")
                    break

        finally:
            self._connected = False
            if self._ws and not self._ws.closed:
                await self._ws.close()
            if self._session and not self._session.closed:
                await self._session.close()

    async def _handle_message(self, raw: str) -> None:
        """Gelen mesajı işle."""
        self._msg_count += 1
        self._last_msg_time = time.time()

        parsed = self._parse_message(raw)
        if parsed is None:
            return

        if self.on_activity is not None:
            try:
                self.on_activity()
            except Exception:
                pass

        symbol = parsed["symbol"]
        if symbol not in self._buffers:
            return

        candle = {
            "timestamp": parsed["timestamp"],
            "open": parsed["open"],
            "high": parsed["high"],
            "low": parsed["low"],
            "close": parsed["close"],
            "volume": parsed["volume"],
        }

        is_closed = parsed["is_closed"]
        closed = self._buffers[symbol].update_live(candle, is_closed)

        if closed and self.on_candle_close:
            # Mum kapandı — callback tetikle
            candles = self._buffers[symbol].get_candles()
            try:
                await self.on_candle_close(symbol, candles)
            except Exception as exc:
                log.error("on_candle_close callback hatası (%s): %s", symbol, exc)

        if self._msg_count % 1000 == 0:
            log.info(
                "WebSocket stats: %d mesaj | son=%s | buffer=%s",
                self._msg_count,
                symbol,
                {s: b.size for s, b in self._buffers.items()},
            )

    # ── Public API ──────────────────────────────────────────────────────

    def get_candles(self, symbol: str) -> List[Dict[str, float]]:
        """Sembolün tüm mumlarını getir (kapanmış + açık)."""
        buf = self._buffers.get(symbol)
        if buf is None:
            return []
        return buf.get_candles()

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Son fiyatı getir."""
        candles = self.get_candles(symbol)
        if not candles:
            return None
        return candles[-1].get("close")

    def is_connected(self) -> bool:
        return self._connected

    def status(self) -> Dict[str, Any]:
        """Durum özeti."""
        return {
            "connected": self._connected,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "msg_count": self._msg_count,
            "last_msg_age": round(time.time() - self._last_msg_time, 1) if self._last_msg_time else None,
            "buffers": {
                s: {
                    "size": b.size,
                    "last_update": round(time.time() - b.last_update, 1) if b.last_update else None,
                }
                for s, b in self._buffers.items()
            },
        }

    async def stop(self) -> None:
        """Temiz kapatma."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        log.info("WebSocket kapatıldı | toplam mesaj: %d", self._msg_count)
