from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

from super_otonom import __version__

load_dotenv()


def _env_trim(val: str | None) -> str:
    """PowerShell / .env kopyasında sık görülen baş-son boşluk ve çift tırnak sarmalamasını kaldırır."""
    if val is None:
        return ""
    s = str(val).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def _env_pick(*keys: str, default: str = "") -> str:
    for k in keys:
        v = _env_trim(os.getenv(k, ""))
        if v:
            return v
    return default


def _env_truthy(name: str, default: str = "false") -> bool:
    return _env_trim(os.getenv(name, default)).lower() in ("1", "true", "yes", "on")


_VAULT_BRIDGE: Any = None


def _vault_bridge() -> Any:
    """Tek VaultBridge örneği — EXCHANGES yüklenirken tekrarlı health check olmasın."""
    global _VAULT_BRIDGE
    if _VAULT_BRIDGE is None:
        from super_otonom.infra.vault_bridge import VaultBridge

        _VAULT_BRIDGE = VaultBridge()
    return _VAULT_BRIDGE


def _exchange_cfg(exchange_id: str, **non_api: Any) -> dict[str, Any]:
    """
    api_* alanları Vault + .env birleşiminden (Vault doluysa üstün);
    testnet vb. non_api yalnızca ortamdan.
    """
    merged = _vault_bridge().get_all_secrets(exchange_id)
    out: dict[str, Any] = dict(non_api)
    for k, v in merged.items():
        if not k.startswith("api_"):
            continue
        t = _env_trim(str(v)) if v is not None else ""
        if t:
            out[k] = t
    return out


# DRY_RUN=true → simülasyon: gerçek emir gönderilmez; paper zorlanır (runbook ilk aşama).
# Canlı spot limit emirleri için: DRY_RUN=false, PAPER_MODE=false, LIVE_CONFIRM=YES, geçerli API anahtarları.
_dry = os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on")
_paper = os.getenv("PAPER_MODE", "true").lower() == "true"
_effective_paper = True if _dry else _paper

# Varsayılan üretim yolu: Binance (testnet/canlı). Diğer anahtarlar deneysel — ccxt + exchange_async
# ile tam doğrulanmadan canlı kullanılmamalıdır (minimum lot, rate limit, hata kodları farklıdır).

GENERAL = {
    "version": __version__,
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "paper_mode": _effective_paper,
    "dry_run": _dry,
    # Mutabakat: spot → bakiye bazlı miktar; future/swap → fetch_positions sembol listesi
    "recon_market": os.getenv("RECON_MARKET", "spot").strip().lower(),
    "default_exchange": os.getenv("DEFAULT_EXCHANGE", "binance"),
    "log_dir": "logs",
    "live_confirm": os.getenv("LIVE_CONFIRM", "").strip().upper(),
    "max_orders_per_min": int(os.getenv("MAX_ORDERS_PER_MIN", "2")),
    "live_sync_mode": os.getenv("LIVE_SYNC_MODE", "HALT").strip().upper(),
    "live_sync_min_base_qty": float(os.getenv("LIVE_SYNC_MIN_BASE_QTY", "0.000001")),
    # Dış ML servis (Neural Link) — ml_client.MLClient
    "ml_service_url": os.getenv("ML_SERVICE_URL", os.getenv("OMEGA_ML_SERVICE_URL", "")),
    "ml_service_timeout": float(os.getenv("ML_SERVICE_TIMEOUT", "2.0")),
    "ml_service_enabled": os.getenv("ML_SERVICE_ENABLED", "false").lower()
    in ("1", "true", "yes", "on"),
}

EXCHANGES = {
    "binance": _exchange_cfg(
        "binance",
        testnet=_env_truthy("BINANCE_TESTNET", "false"),
    ),
    "bybit": _exchange_cfg(
        "bybit",
        testnet=os.getenv("BYBIT_TESTNET", "true").lower() == "true",
    ),
    "kucoin": _exchange_cfg("kucoin"),
    "okx": _exchange_cfg("okx"),
    "coinbase": _exchange_cfg("coinbase"),
    "gateio": _exchange_cfg("gateio"),
}

PAIRS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

RISK = {
    # Pozisyon yonetimi — env ile calisma aninda degistirilebilir
    "max_position_pct": float(os.getenv("MAX_POSITION_PCT", "0.12")),
    "max_open_positions": int(
        os.getenv("MAX_OPEN_POSITIONS", os.getenv("MAX_POSITION_COUNT", "1"))
    ),
    "min_notional": float(os.getenv("MIN_NOTIONAL", "10.0")),
    # Tek emir üst notional (USDT) — fat finger; pre_trade_gate.fat_finger_check
    "max_notional_per_order": max(
        10.0,
        min(float(os.getenv("MAX_NOTIONAL_PER_ORDER", "50000")), 50_000_000.0),
    ),
    # Kar/zarar seviyeleri (geriye uyum + kademeli çıkış üst sınırı)
    "take_profit_pct": float(os.getenv("TAKE_PROFIT_PCT", "0.30")),
    "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", "0.04")),
    "trailing_stop_pct": float(os.getenv("TRAILING_STOP_PCT", "0.035")),
    "trailing_stop_pct_strong": float(os.getenv("TRAILING_STOP_PCT_STRONG", "0.055")),
    "trailing_stop_pct_weak": float(os.getenv("TRAILING_STOP_PCT_WEAK", "0.025")),
    # Kayip/drawdown limitleri
    "max_daily_loss_pct": float(os.getenv("MAX_DAILY_LOSS_PCT", "0.05")),
    "max_weekly_loss_pct": float(os.getenv("MAX_WEEKLY_LOSS_PCT", "0.10")),
    "max_total_drawdown": float(os.getenv("MAX_TOTAL_DRAWDOWN", "0.20")),
    "max_exposure_pct": float(os.getenv("MAX_EXPOSURE_PCT", "0.12")),
    # Kill-switch: limit üstü exposure acil durdurur (true = risk.trigger_emergency)
    "exposure_breach_emergency": os.getenv("EXPOSURE_BREACH_EMERGENCY", "false").lower()
    in ("1", "true", "yes", "on"),
    # VR-19: VaR/CVaR breach kill-switch limitleri
    "max_var_99_pct": float(os.getenv("MAX_VAR_99_PCT", "0.06")),
    "max_cvar_975_pct": float(os.getenv("MAX_CVAR_975_PCT", "0.10")),
    "max_model_dispersion_pct": float(os.getenv("MAX_MODEL_DISPERSION_PCT", "0.50")),
    # Istatistiksel
    "var_confidence": float(os.getenv("VAR_CONFIDENCE", "0.95")),
    "entry_min_confidence": float(os.getenv("ENTRY_MIN_CONFIDENCE", "0.62")),
    # Elite: sinyal kalite puanı — altındaki BUY reddi (SIGNAL_QUALITY_MIN)
    "signal_quality_min": int(os.getenv("SIGNAL_QUALITY_MIN", "62")),
    # Kaldıraç tavanı (PositionSizer + açık notional denetimi). Borsa margin ile uyum için env ile ayarlayın.
    "max_leverage": max(
        0.01,
        min(float(os.getenv("MAX_LEVERAGE", "1.0")), 50.0),
    ),
    # Son başarılı girişten sonra minimum bekleme (s); 0 = kapalı (geriye uyum)
    "min_entry_cooldown_sec": max(
        0.0,
        min(float(os.getenv("MIN_ENTRY_COOLDOWN_SEC", "0.0")), 86_400.0),
    ),
}

STAGED_EXIT = {
    "take_profit_1": float(os.getenv("TAKE_PROFIT_1", "0.15")),
    "take_profit_2": float(os.getenv("TAKE_PROFIT_2", "0.23")),
    "take_profit_3": float(os.getenv("TAKE_PROFIT_3", "0.30")),
    "partial_exit_1": float(os.getenv("PARTIAL_EXIT_1", "0.20")),
    "partial_exit_2": float(os.getenv("PARTIAL_EXIT_2", "0.30")),
    "partial_exit_3": float(os.getenv("PARTIAL_EXIT_3", "0.50")),
    "tp_atr_blend": float(os.getenv("TP_ATR_BLEND", "0.35")),
    "tp_atr_mult_1": float(os.getenv("TP_ATR_MULT_1", "2.0")),
    "tp_atr_mult_2": float(os.getenv("TP_ATR_MULT_2", "3.5")),
    "tp_atr_mult_3": float(os.getenv("TP_ATR_MULT_3", "5.0")),
    "tp_min_pct": float(os.getenv("TP_MIN_PCT", "0.12")),
    "tp_max_pct": float(os.getenv("TP_MAX_PCT", "0.40")),
    "stop_hard_mult": float(os.getenv("STOP_HARD_MULT", "0.96")),
    "breakeven_after_stage": int(os.getenv("BREAKEVEN_AFTER_STAGE", "1")),
    "breakeven_buffer_pct": float(os.getenv("BREAKEVEN_BUFFER_PCT", "0.003")),
    "stage_defer_enabled": os.getenv("STAGE_DEFER_ENABLED", "true").lower()
    in ("1", "true", "yes", "on"),
    "stage_defer_min_adj_quality": int(os.getenv("STAGE_DEFER_MIN_ADJ_QUALITY", "72")),
    "stage_defer_regimes": os.getenv("STAGE_DEFER_REGIMES", "TRENDING"),
    "stage_defer_max_bars": int(os.getenv("STAGE_DEFER_MAX_BARS", "6")),
    "stage_defer_decay_block": os.getenv("STAGE_DEFER_DECAY_BLOCK", "true").lower()
    in ("1", "true", "yes", "on"),
}

STRATEGY = {
    "candle_limit": int(os.getenv("CANDLE_LIMIT", "120")),
    "timeframe": os.getenv("TIMEFRAME", "1h"),
}

AI = {
    "lstm_enabled": os.getenv("LSTM_ENABLED", "false").lower() == "true",
    "lstm_seq_len": 30,
    "lstm_features": 8,
    "lstm_hidden": 64,
}

METRICS = {
    "prometheus_port": int(os.getenv("METRICS_PORT", "8000")),
    "namespace": os.getenv("METRICS_NAMESPACE", "bot"),
    "update_interval": int(os.getenv("METRICS_INTERVAL", "0")),
}

CLOCK_SKEW = {
    "warn_ms": int(os.getenv("CLOCK_SKEW_WARN_MS", "500")),
    "crit_ms": int(os.getenv("CLOCK_SKEW_CRIT_MS", "2000")),
}

PACKAGE_TOPOLOGY = {
    "flat_production_ceiling": int(os.getenv("PACKAGE_FLAT_PROD_CEILING", "120")),
}

BOT_ENGINE_TOPOLOGY = {
    "file_line_ceiling": int(os.getenv("BOT_ENGINE_FILE_LINE_CEILING", "1450")),
    "class_line_ceiling": int(os.getenv("BOT_ENGINE_CLASS_LINE_CEILING", "1100")),
    "god_class_min_lines": int(os.getenv("BOT_ENGINE_GOD_CLASS_MIN_LINES", "800")),
}

TEST_LAYOUT = {
    "in_package_test_ceiling": int(os.getenv("IN_PACKAGE_TEST_MODULE_CEILING", "35")),
    "canonical_test_dir": "tests",
}

WFA = {
    "window_size": int(os.getenv("WFA_WINDOW", "1000")),
    "step_size": int(os.getenv("WFA_STEP", "200")),
    "train_ratio": float(os.getenv("WFA_TRAIN_RATIO", "0.70")),
    "min_test_rows": int(os.getenv("WFA_MIN_TEST_ROWS", "10")),
}

ASYNC_EXCHANGE = {
    "timeframe": os.getenv("EXCHANGE_TIMEFRAME", "1h"),
    "limit": int(os.getenv("EXCHANGE_LIMIT", "120")),
    "max_retries": int(os.getenv("EXCHANGE_RETRIES", "3")),
    "retry_delay": float(os.getenv("EXCHANGE_RETRY_DELAY", "1.0")),
    "ob_limit": int(os.getenv("EXCHANGE_OB_LIMIT", "20")),
}

# Alt zaman dilimi (5m gürültü / zamanlama filtresi)
ALT_TF = {
    "timeframe": os.getenv("ALT_TF_TIMEFRAME", "5m"),
    "candle_limit": int(os.getenv("ALT_TF_LIMIT", "60")),
    "enabled": os.getenv("ALT_TF_ENABLED", "true").lower() == "true",
    "veto": os.getenv("ALT_TF_VETO", "true").lower() == "true",
}

# FIX: 4H MTF konfigürasyonu merkezi olarak buradan yönetilir
MTF = {
    "timeframe": os.getenv("MTF_TIMEFRAME", "4h"),
    "candle_limit": int(os.getenv("CANDLE_LIMIT_4H", "50")),
    "enabled": os.getenv("MTF_ENABLED", "true").lower() == "true",
}


def _log_meta_advisory_env_at_import() -> None:
    """Canlı/paper ile A9 env uyumu — import anında tek sefer (runbook: META_ORCHESTRATOR_A9)."""
    mode = (os.getenv("META_REGIME_MODE") or "shadow").strip().lower()
    if mode != "advisory":
        return
    loose = (os.getenv("META_ADVISORY_LOOSE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    log = logging.getLogger("super_otonom.config")
    live_like = not _effective_paper
    if live_like and loose:
        log.warning(
            "META_ADVISORY_LOOSE etkin ve paper/dry-run kapalı — A9 ölçüm kilidi devre dışı. "
            "Üretimde kaldırın; geliştirici .env kopyalamayın. Bkz. docs/META_ORCHESTRATOR_A9.md"
        )
        return
    if not live_like:
        return
    from super_otonom.meta_regime_orchestrator import advisory_ack_path_for_gate

    path = advisory_ack_path_for_gate("advisory")
    if path is None:
        return
    try:
        ok = os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        ok = False
    if not ok:
        log.warning(
            "META_REGIME_MODE=advisory, ölçüm ACK yok veya boş (%s) — güven çarpanı uygulanmaz. "
            'python -m super_otonom.meta_regime_orchestrator --message "…" veya '
            "scripts/write_meta_advisory_ack.ps1",
            path,
        )
    else:
        log.info("META_REGIME_MODE=advisory, ölçüm ACK mevcut: %s", path)


_log_meta_advisory_env_at_import()
