"""
Hard safety sözleşmesi — AI / strateji bu katmanı gevşetemez veya atlayamaz.

Uygulama noktaları (tek yönlü, konfig + piyasa/sermaye ölçüleri):
  - ``pre_trade_gate``: global trade disable, BUY slot, same-bar, giriş cooldown,
    kaldıraç tavanı (notional), spread / OB / fat-finger
  - ``pipelines.risk_pipeline`` + ``run_system_gate_phase``: kill, spike
  - ``RiskManager.check_risk``: drawdown, günlük/haftalık kayıp, exposure, vol spike
  - ``HardLimitTracker``: emir hızı, fiyat sıçraması

Bu modüldeki sabitler yalnızca dokümantasyon içindir; gerçek eşikler ``config.RISK`` ve env
değişkenlerinden okunur. AILayer veya sinyal skorları bu dosyayı import ederek limit
değiştirmemelidir.

Zincir veya gate değişince PR checklist: ``docs/GOVERNANCE_CHECKLIST_TR.md`` — bölüm
**Güncelleme kuralı (PR)**.
"""

from __future__ import annotations

# Dokümantasyon amaçlı — gerçek değerler config.RISK üzerinden
HARD_SAFETY_CONFIG_NAMESPACE = "RISK"
HARD_SAFETY_ENV_KEYS = (
    "MAX_LEVERAGE",
    "MIN_ENTRY_COOLDOWN_SEC",
    "GLOBAL_TRADE_DISABLE",
    "MAX_POSITION_PCT",
    "MAX_EXPOSURE_PCT",
    "MAX_NOTIONAL_PER_ORDER",
)
