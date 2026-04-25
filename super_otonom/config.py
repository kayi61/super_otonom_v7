from __future__ import annotations

import os

from dotenv import load_dotenv

from . import __version__

load_dotenv()

# DRY_RUN=true simülasyon: gerçek emir gönderilmez; paper zorunlu (runbook: ilk aşama)
_dry = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
_paper = os.getenv("PAPER_MODE", "true").lower() == "true"
_effective_paper = True if _dry else _paper

GENERAL = {
    "version": __version__,
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "paper_mode": _effective_paper,
    "dry_run": _dry,
    "default_exchange": os.getenv("DEFAULT_EXCHANGE", "binance"),
    "log_dir": "logs",
    "live_confirm": os.getenv("LIVE_CONFIRM", "").strip().upper(),
    "max_orders_per_min": int(os.getenv("MAX_ORDERS_PER_MIN", "2")),
    "live_sync_mode": os.getenv("LIVE_SYNC_MODE", "HALT").strip().upper(),
    "live_sync_min_base_qty": float(os.getenv("LIVE_SYNC_MIN_BASE_QTY", "0.000001")),
    # Dış ML servis (Neural Link) — ml_client.MLClient
    "ml_service_url":     os.getenv("ML_SERVICE_URL", os.getenv("OMEGA_ML_SERVICE_URL", "")),
    "ml_service_timeout": float(os.getenv("ML_SERVICE_TIMEOUT", "2.0")),
    "ml_service_enabled": os.getenv("ML_SERVICE_ENABLED", "false").lower() in (
        "1", "true", "yes", "on"
    ),
}

EXCHANGES = {
    "binance": {
        "api_key": os.getenv("BINANCE_API_KEY", ""),
        "api_secret": os.getenv("BINANCE_API_SECRET", ""),
        "testnet": os.getenv("BINANCE_TESTNET", "true").lower() == "true",
    },
    "bybit": {
        "api_key": os.getenv("BYBIT_API_KEY", ""),
        "api_secret": os.getenv("BYBIT_API_SECRET", ""),
        "testnet": os.getenv("BYBIT_TESTNET", "true").lower() == "true",
    },
    "kucoin": {
        "api_key": os.getenv("KUCOIN_API_KEY", ""),
        "api_secret": os.getenv("KUCOIN_API_SECRET", ""),
        "api_passphrase": os.getenv("KUCOIN_API_PASSPHRASE", ""),
    },
    "okx": {
        "api_key": os.getenv("OKX_API_KEY", ""),
        "api_secret": os.getenv("OKX_API_SECRET", ""),
        "api_password": os.getenv("OKX_API_PASSWORD", ""),
    },
    "coinbase": {
        "api_key": os.getenv("COINBASE_API_KEY", ""),
        "api_secret": os.getenv("COINBASE_API_SECRET", ""),
    },
    "gateio": {
        "api_key": os.getenv("GATEIO_API_KEY", ""),
        "api_secret": os.getenv("GATEIO_API_SECRET", ""),
    },
}

PAIRS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

RISK = {
    # Pozisyon yonetimi — env ile calisma aninda degistirilebilir
    "max_position_pct":     float(os.getenv("MAX_POSITION_PCT",    "0.05")),
    "max_open_positions":   int(
        os.getenv("MAX_OPEN_POSITIONS", os.getenv("MAX_POSITION_COUNT", "1"))
    ),
    "min_notional":         float(os.getenv("MIN_NOTIONAL",        "10.0")),
    # Kar/zarar seviyeleri
    "take_profit_pct":      float(os.getenv("TAKE_PROFIT_PCT",     "0.03")),
    "stop_loss_pct":        float(os.getenv("STOP_LOSS_PCT",       "0.015")),
    "trailing_stop_pct":    float(os.getenv("TRAILING_STOP_PCT",   "0.015")),
    # Kayip/drawdown limitleri
    "max_daily_loss_pct":   float(os.getenv("MAX_DAILY_LOSS_PCT",  "0.05")),
    "max_weekly_loss_pct":  float(os.getenv("MAX_WEEKLY_LOSS_PCT", "0.10")),
    "max_total_drawdown":   float(os.getenv("MAX_TOTAL_DRAWDOWN",  "0.20")),
    "max_exposure_pct":     float(os.getenv("MAX_EXPOSURE_PCT",    "0.30")),
    # Kill-switch: limit üstü exposure acil durdurur (true = risk.trigger_emergency)
    "exposure_breach_emergency": os.getenv("EXPOSURE_BREACH_EMERGENCY", "false").lower() in (
        "1", "true", "yes", "on"
    ),
    # Istatistiksel
    "var_confidence":       float(os.getenv("VAR_CONFIDENCE",      "0.95")),
    "entry_min_confidence": float(os.getenv("ENTRY_MIN_CONFIDENCE","0.55")),
    # Elite: sinyal kalite puanı — altındaki BUY reddi (SIGNAL_QUALITY_MIN)
    "signal_quality_min": int(os.getenv("SIGNAL_QUALITY_MIN", "40")),
}

STRATEGY = {
    "candle_limit": int(os.getenv("CANDLE_LIMIT", "150")),
    "timeframe":    os.getenv("TIMEFRAME", "5m"),
}

AI = {
    "lstm_enabled":  os.getenv("LSTM_ENABLED", "false").lower() == "true",
    "lstm_seq_len":  30,
    "lstm_features": 8,
    "lstm_hidden":   64,
}

METRICS = {
    "prometheus_port": int(os.getenv("METRICS_PORT", "8000")),
    "namespace":       os.getenv("METRICS_NAMESPACE", "bot"),
    "update_interval": int(os.getenv("METRICS_INTERVAL", "0")),
}

WFA = {
    "window_size":   int(os.getenv("WFA_WINDOW",      "1000")),
    "step_size":     int(os.getenv("WFA_STEP",         "200")),
    "train_ratio":   float(os.getenv("WFA_TRAIN_RATIO","0.70")),
    "min_test_rows": int(os.getenv("WFA_MIN_TEST_ROWS", "10")),
}

ASYNC_EXCHANGE = {
    "timeframe":   os.getenv("EXCHANGE_TIMEFRAME", "5m"),
    "limit":       int(os.getenv("EXCHANGE_LIMIT", "150")),
    "max_retries": int(os.getenv("EXCHANGE_RETRIES", "3")),
    "retry_delay": float(os.getenv("EXCHANGE_RETRY_DELAY", "1.0")),
    "ob_limit":    int(os.getenv("EXCHANGE_OB_LIMIT", "20")),
}

# FIX: 4H MTF konfigürasyonu merkezi olarak buradan yönetilir
MTF = {
    "timeframe":    os.getenv("MTF_TIMEFRAME", "4h"),
    "candle_limit": int(os.getenv("CANDLE_LIMIT_4H", "50")),
    "enabled":      os.getenv("MTF_ENABLED", "true").lower() == "true",
}
