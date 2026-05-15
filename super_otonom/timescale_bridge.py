from __future__ import annotations

"""
TimescaleBridge v1.0
─────────────────────────────────────────────────────────────────────────────
TimescaleDB (PostgreSQL + hypertable) ile kline, trade ve sinyal verisi kayıt sistemi.

Özellikler:
    • Otomatik tablo oluşturma (hypertable)
    • Kline (OHLCV) kayıt — Go bridge veya exchange'den gelen veriler
    • Trade kayıt — bot'un açtığı/kapattığı işlemler
    • Capital journal (JSONL aynası) — ``CapitalEngine`` audit satırları hypertable'da
    • Sinyal kayıt — analyzer/signal_fusion çıktıları
    • Batch insert desteği
    • Bağlantı havuzu (connection pool)
    • Graceful fallback — DB yoksa bot durmaz

Kullanım:
    db = TimescaleBridge()
    db.insert_kline("BTCUSDT", "1h", open=100, high=105, low=99, close=103, volume=500)
    db.insert_trade("BTCUSDT", "BUY", price=100, qty=0.1, reason="signal_fusion")
    db.query_klines("BTCUSDT", "1h", limit=100)

Docker-compose / .env:
    TIMESCALE_HOST=timescaledb
    TIMESCALE_PORT=5432
    TIMESCALE_DB=trading
    TIMESCALE_USER=superotonom
    TIMESCALE_PASSWORD=<.env içinde; kodda varsayılan yok>
"""

import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

log = logging.getLogger("super_otonom.timescale_bridge")

try:
    import psycopg2
    import psycopg2.pool
    import psycopg2.extras

    _PG_AVAILABLE = True
except ImportError:
    _PG_AVAILABLE = False
    log.warning("psycopg2 kurulu değil — pip install psycopg2-binary")

# ── Konfigürasyon ──────────────────────────────────────────────────────

_HOST = os.getenv("TIMESCALE_HOST", "timescaledb")
_PORT = int(os.getenv("TIMESCALE_PORT", "5432"))
_DB = os.getenv("TIMESCALE_DB", "trading")
_USER = os.getenv("TIMESCALE_USER", "superotonom")
_PASS = os.getenv("TIMESCALE_PASSWORD", "")
_POOL_MIN = int(os.getenv("TIMESCALE_POOL_MIN", "2"))
_POOL_MAX = int(os.getenv("TIMESCALE_POOL_MAX", "10"))

# ── DDL ─────────────────────────────────────────────────────────────────

_DDL_KLINES = """
CREATE TABLE IF NOT EXISTS klines (
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    timeframe   TEXT        NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    is_closed   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

_DDL_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    side        TEXT        NOT NULL,
    price       DOUBLE PRECISION,
    qty         DOUBLE PRECISION,
    notional    DOUBLE PRECISION,
    reason      TEXT,
    order_id    TEXT,
    confidence  DOUBLE PRECISION,
    regime      TEXT,
    pnl         DOUBLE PRECISION DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

_DDL_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    signal      TEXT        NOT NULL,
    confidence  DOUBLE PRECISION,
    source      TEXT,
    regime      TEXT,
    meta        JSONB,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

_DDL_EQUITY = """
CREATE TABLE IF NOT EXISTS equity_curve (
    ts          TIMESTAMPTZ NOT NULL,
    balance     DOUBLE PRECISION,
    equity      DOUBLE PRECISION,
    drawdown    DOUBLE PRECISION,
    open_positions INT DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

_DDL_CAPITAL_JOURNAL = """
CREATE TABLE IF NOT EXISTS capital_journal (
    ts           TIMESTAMPTZ NOT NULL,
    event        TEXT        NOT NULL,
    symbol       TEXT        NOT NULL,
    order_id     TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
"""

_HYPERTABLES = [
    ("klines", "ts"),
    ("trades", "ts"),
    ("signals", "ts"),
    ("equity_curve", "ts"),
    ("capital_journal", "ts"),
]

_LAST_AVAILABLE: bool = False


def timescale_last_available() -> bool:
    return _LAST_AVAILABLE


def probe_timescale_available() -> bool:
    """Hafif baglanti testi (havuz acmadan) — ops metrikleri icin."""
    global _LAST_AVAILABLE
    if not _PG_AVAILABLE or not _PASS:
        _LAST_AVAILABLE = False
        return False
    try:
        conn = psycopg2.connect(
            host=_HOST,
            port=_PORT,
            dbname=_DB,
            user=_USER,
            password=_PASS,
            connect_timeout=3,
        )
        conn.close()
        _LAST_AVAILABLE = True
        return True
    except Exception:
        _LAST_AVAILABLE = False
        return False


class TimescaleBridge:
    """
    TimescaleDB bağlantı köprüsü.

    Bağlantı havuzu kullanır, hypertable'ları otomatik oluşturur.
    DB yoksa veya bağlantı kurulamazsa bot durmaz — tüm yazma
    işlemleri sessizce atlanır, uyarı loglanır.
    """

    def __init__(self):
        self._pool: Any = None
        self._available = False
        self._write_count = 0
        self._error_count = 0

        if not _PG_AVAILABLE:
            log.warning("psycopg2 yok — TimescaleDB devre dışı")
            return

        try:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                _POOL_MIN,
                _POOL_MAX,
                host=_HOST,
                port=_PORT,
                dbname=_DB,
                user=_USER,
                password=_PASS,
                connect_timeout=5,
            )
            self._available = True
            log.info("TimescaleDB bağlantısı kuruldu (%s:%d/%s)", _HOST, _PORT, _DB)
            self._init_schema()
        except Exception as exc:
            log.warning("TimescaleDB bağlantı hatası: %s — devre dışı", exc)

        global _LAST_AVAILABLE
        _LAST_AVAILABLE = self._available
        try:
            from super_otonom.ops_metrics import set_dependency_up

            set_dependency_up("timescale", self._available)
        except Exception:
            pass

    @contextmanager
    def _conn(self) -> Generator:
        """Havuzdan bağlantı al, işlem bitince geri ver."""
        conn = None
        try:
            conn = self._pool.getconn()
            conn.autocommit = True
            yield conn
        finally:
            if conn:
                self._pool.putconn(conn)

    def _init_schema(self):
        """Tabloları ve hypertable'ları oluştur."""
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                # Tablolar
                for ddl in [_DDL_KLINES, _DDL_TRADES, _DDL_SIGNALS, _DDL_EQUITY, _DDL_CAPITAL_JOURNAL]:
                    cur.execute(ddl)

                # Hypertable dönüşümü
                for table, col in _HYPERTABLES:
                    try:
                        cur.execute(
                            f"SELECT create_hypertable('{table}', '{col}', "
                            f"if_not_exists => TRUE, migrate_data => TRUE);"
                        )
                    except Exception:
                        pass  # Zaten hypertable ise hata verir — sorun değil

                # İndeksler
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_klines_symbol_tf "
                    "ON klines (symbol, timeframe, ts DESC);"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_trades_symbol "
                    "ON trades (symbol, ts DESC);"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_signals_symbol "
                    "ON signals (symbol, ts DESC);"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_capital_journal_event_ts "
                    "ON capital_journal (event, ts DESC);"
                )
                cur.close()
                log.info("TimescaleDB şema hazır (5 hypertable)")
        except Exception as exc:
            log.error("Şema oluşturma hatası: %s", exc)

    # ── Status ──────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Bağlantı durum özeti."""
        return {
            "available": self._available,
            "host": f"{_HOST}:{_PORT}",
            "database": _DB,
            "writes": self._write_count,
            "errors": self._error_count,
        }

    # ── Kline ───────────────────────────────────────────────────────────

    def insert_kline(
        self,
        symbol: str,
        timeframe: str,
        *,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
        ts: Optional[datetime] = None,
        is_closed: bool = True,
    ) -> bool:
        """Tek kline kaydet."""
        if not self._available:
            return False
        ts = ts or datetime.now(timezone.utc)
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO klines (ts, symbol, timeframe, open, high, low, close, volume, is_closed) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (ts, symbol, timeframe, open, high, low, close, volume, is_closed),
                )
                cur.close()
                self._write_count += 1
                return True
        except Exception as exc:
            self._error_count += 1
            log.error("Kline yazma hatası (%s): %s", symbol, exc)
            return False

    def insert_klines_batch(
        self, rows: List[Tuple[datetime, str, str, float, float, float, float, float, bool]]
    ) -> int:
        """
        Toplu kline kaydet.
        Her satır: (ts, symbol, timeframe, open, high, low, close, volume, is_closed)
        Dönüş: yazılan satır sayısı.
        """
        if not self._available or not rows:
            return 0
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO klines (ts, symbol, timeframe, open, high, low, close, volume, is_closed) "
                    "VALUES %s",
                    rows,
                )
                cur.close()
                self._write_count += len(rows)
                return len(rows)
        except Exception as exc:
            self._error_count += 1
            log.error("Batch kline hatası: %s", exc)
            return 0

    # ── Trade ───────────────────────────────────────────────────────────

    def insert_trade(
        self,
        symbol: str,
        side: str,
        *,
        price: float,
        qty: float,
        reason: str = "",
        order_id: str = "",
        confidence: float = 0.0,
        regime: str = "",
        pnl: float = 0.0,
        ts: Optional[datetime] = None,
    ) -> bool:
        """Trade kaydı yaz."""
        if not self._available:
            return False
        ts = ts or datetime.now(timezone.utc)
        notional = price * qty
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO trades (ts, symbol, side, price, qty, notional, reason, order_id, confidence, regime, pnl) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (ts, symbol, side, price, qty, notional, reason, order_id, confidence, regime, pnl),
                )
                cur.close()
                self._write_count += 1
                log.info("Trade kaydedildi: %s %s %s @ %.2f", symbol, side, qty, price)
                return True
        except Exception as exc:
            self._error_count += 1
            log.error("Trade yazma hatası: %s", exc)
            return False

    def insert_capital_journal_event(self, row: Dict[str, Any]) -> bool:
        """``CapitalEngine`` journal satırı (``asdict(JournalEntry)``) — JSONL ile aynı içerik."""
        if not self._available:
            return False
        ts_raw = row.get("ts")
        if isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO capital_journal (ts, event, symbol, order_id, payload) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        ts,
                        str(row.get("event", "")),
                        str(row.get("symbol", "")),
                        str(row.get("order_id", "")),
                        psycopg2.extras.Json(row),
                    ),
                )
                cur.close()
                self._write_count += 1
                return True
        except Exception as exc:
            self._error_count += 1
            log.error("capital_journal yazma hatası: %s", exc)
            return False

    def make_capital_journal_sink(self):
        """``CapitalEngine(..., journal_sink=...)`` için callable (DB kapalıysa yazma atlanır)."""

        def _sink(entry_dict: Dict[str, Any]) -> None:
            self.insert_capital_journal_event(entry_dict)

        return _sink

    # ── Signal ──────────────────────────────────────────────────────────

    def insert_signal(
        self,
        symbol: str,
        signal: str,
        *,
        confidence: float = 0.0,
        source: str = "",
        regime: str = "",
        meta: Optional[Dict] = None,
        ts: Optional[datetime] = None,
    ) -> bool:
        """Sinyal kaydı yaz."""
        if not self._available:
            return False
        ts = ts or datetime.now(timezone.utc)
        try:
            import json as _json

            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO signals (ts, symbol, signal, confidence, source, regime, meta) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (ts, symbol, signal, confidence, source, regime,
                     _json.dumps(meta) if meta else None),
                )
                cur.close()
                self._write_count += 1
                return True
        except Exception as exc:
            self._error_count += 1
            log.error("Sinyal yazma hatası: %s", exc)
            return False

    # ── Equity Curve ────────────────────────────────────────────────────

    def insert_equity(
        self,
        balance: float,
        equity: float,
        drawdown: float = 0.0,
        open_positions: int = 0,
        ts: Optional[datetime] = None,
    ) -> bool:
        """Equity eğrisi noktası kaydet."""
        if not self._available:
            return False
        ts = ts or datetime.now(timezone.utc)
        try:
            with self._conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO equity_curve (ts, balance, equity, drawdown, open_positions) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (ts, balance, equity, drawdown, open_positions),
                )
                cur.close()
                self._write_count += 1
                return True
        except Exception as exc:
            self._error_count += 1
            log.error("Equity yazma hatası: %s", exc)
            return False

    # ── Query ───────────────────────────────────────────────────────────

    def query_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Son N kline'ı getir."""
        if not self._available:
            return []
        try:
            with self._conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                if since:
                    cur.execute(
                        "SELECT ts, open, high, low, close, volume, is_closed "
                        "FROM klines WHERE symbol=%s AND timeframe=%s AND ts >= %s "
                        "ORDER BY ts DESC LIMIT %s",
                        (symbol, timeframe, since, limit),
                    )
                else:
                    cur.execute(
                        "SELECT ts, open, high, low, close, volume, is_closed "
                        "FROM klines WHERE symbol=%s AND timeframe=%s "
                        "ORDER BY ts DESC LIMIT %s",
                        (symbol, timeframe, limit),
                    )
                rows = cur.fetchall()
                cur.close()
                return [dict(r) for r in rows]
        except Exception as exc:
            log.error("Kline sorgu hatası: %s", exc)
            return []

    def query_trades(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        side: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Son trade'leri getir."""
        if not self._available:
            return []
        try:
            with self._conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                clauses = []
                params: list = []
                if symbol:
                    clauses.append("symbol = %s")
                    params.append(symbol)
                if side:
                    clauses.append("side = %s")
                    params.append(side)
                where = "WHERE " + " AND ".join(clauses) if clauses else ""
                params.append(limit)
                cur.execute(
                    f"SELECT ts, symbol, side, price, qty, notional, reason, confidence, regime, pnl "
                    f"FROM trades {where} ORDER BY ts DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
                cur.close()
                return [dict(r) for r in rows]
        except Exception as exc:
            log.error("Trade sorgu hatası: %s", exc)
            return []

    def query_capital_journal(
        self,
        *,
        event: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Son capital journal satırları (payload JSON)."""
        if not self._available:
            return []
        try:
            with self._conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                clauses: List[str] = []
                params: List[Any] = []
                if event:
                    clauses.append("event = %s")
                    params.append(event)
                if symbol:
                    clauses.append("symbol = %s")
                    params.append(symbol)
                where = "WHERE " + " AND ".join(clauses) if clauses else ""
                params.append(limit)
                cur.execute(
                    f"SELECT ts, event, symbol, order_id, payload FROM capital_journal "
                    f"{where} ORDER BY ts DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
                cur.close()
                return [dict(r) for r in rows]
        except Exception as exc:
            log.error("capital_journal sorgu hatası: %s", exc)
            return []

    def query_equity(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Equity eğrisi getir."""
        if not self._available:
            return []
        try:
            with self._conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    "SELECT ts, balance, equity, drawdown, open_positions "
                    "FROM equity_curve ORDER BY ts DESC LIMIT %s",
                    (limit,),
                )
                rows = cur.fetchall()
                cur.close()
                return [dict(r) for r in rows]
        except Exception as exc:
            log.error("Equity sorgu hatası: %s", exc)
            return []

    # ── Aggregation ─────────────────────────────────────────────────────

    def daily_pnl_summary(self, days: int = 30) -> List[Dict[str, Any]]:
        """Günlük P&L özeti (TimescaleDB time_bucket)."""
        if not self._available:
            return []
        try:
            with self._conn() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(
                    """
                    SELECT
                        time_bucket('1 day', ts) AS day,
                        SUM(pnl) AS total_pnl,
                        COUNT(*) AS trade_count,
                        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses
                    FROM trades
                    WHERE ts >= NOW() - INTERVAL '%s days'
                    GROUP BY day
                    ORDER BY day DESC
                    """,
                    (days,),
                )
                rows = cur.fetchall()
                cur.close()
                return [dict(r) for r in rows]
        except Exception as exc:
            log.error("Günlük P&L sorgu hatası: %s", exc)
            return []

    # ── Cleanup ─────────────────────────────────────────────────────────

    def close(self):
        """Bağlantı havuzunu kapat."""
        if self._pool:
            self._pool.closeall()
            log.info("TimescaleDB bağlantıları kapatıldı")
