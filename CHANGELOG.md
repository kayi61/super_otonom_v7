# CHANGELOG — super_otonom

## v7.0.0 (2026-04-25) — Sürüm tekilleştirme

- **`__version__` tek kaynak:** `super_otonom/__init__.py` → `"7.0.0"`.
- **`GENERAL["version"]`:** aynı değer `from . import __version__` ile bağlandı; drift riski giderildi.
- **`pyproject.toml` / `[project] version`:** `7.0.0` ile hizalı (paket yayımlama).
- **`main_loop`:** log satırındaki yedek sürüm `__version__` ile uyumlu.

### Kurumsal Risk Yol Haritası (VR-01 → VR-27)
- VR-01 Unified RiskEngine
- VR-02 VaR modelleri (Hist/Param/MC)
- VR-03 Cornish-Fisher VaR genişlemesi
- VR-04 CVaR / Expected Shortfall
- VR-05 RiskConfig Basel uyumu
- VR-06 EVT (POT Peaks Over Threshold)
- VR-07 FHS (GARCH(1,1) Filtreli Tarihsel Sim)
- VR-08 LVaR (BDSS + Time-To-Liquidate)
- VR-09 VaR ayrıştırma (Component/Marginal/Incremental)
- VR-10 Regime-Conditional VaR (koşullu VaR)
- VR-11 Stressed VaR (Basel 2.5 rescaling)
- VR-12 Stress Senaryo Kütüphanesi + Reverse Stress
- VR-13 Kupiec POF backtest
- VR-14 Christoffersen Independence + Conditional Coverage
- VR-15 Basel Traffic Light backtest
- VR-16 P&L Attribution + Unexplained PnL Drift
- VR-17 Pre-trade Marginal VaR gate
- VR-18 VaR-aware Position Sizing (Kelly + VaR Cap)
- VR-19 Kill-switch (VaR/CVaR breach tetikleyici)
- VR-20 VaR Limit Hierarchy (Strategy/Portfolio/Firm)
- VR-21 Prometheus VaR/CVaR/Stressed suite
- VR-22 Günlük Risk Raporu (otomatik üretim)
- VR-23 Grafana Risk Dashboard
- VR-24 Model Envanteri + Validasyon yönetişimi
- VR-25 Risk Appetite + Escalation Matrisi
- VR-26 Property-based VaR/CVaR invariants (Hypothesis)
- VR-27 Regime Detection Engine (statistical)

### Faz A → Faz D (Entegrasyon)
- Faz A: Acil düzeltmeler + tracker/exports/polish stub’lar
- Faz B: BotEngine ↔ RiskEngine tam entegrasyon (risk wiring)
- Faz C: Basel 10-day VaR + CI workflows + model governance
- Faz D: Polish & dokümantasyon iyileştirmeleri

---

## v6.1.0 (2026-04-24) — Hata Düzeltmeleri + Eksik Tamamlama

### Düzeltilen Hatalar

#### main_loop.py ← TAM YENİDEN YAZILDI
- **[DÜZELTME]** `analyze()` yerine `analyze_v5_1()` kullanılıyor — 4H çoklu zaman dilimi filtresi artık aktif
- **[DÜZELTME]** `calculate_with_slippage()` yerine `validate_and_calculate()` kullanılıyor — 3 katmanlı güvenlik filtresi (zaman senkronizasyonu + imbalance + fractional Kelly) artık aktif
- **[DÜZELTME]** v6 tick çıktıları (`sentiment_status`, `corr_multiplier`) artık loglanıyor
- **[DÜZELTME]** `corr_tracked_symbols` durum özetine eklendi
- **[İYİLEŞTİRME]** 4H veri çekimi paralel yapıldı (ayrı `fetch_all_ohlcv` çağrısı)
- **[İYİLEŞTİRME]** MTF log satırı `high_tf_trend` ve `mtf_filtered` bilgisini içeriyor

#### exchange_async.py
- **[EKSİK]** `get_order_status(order_id, symbol)` metodu eklendi — `OrderTracker` tarafından kullanılıyor
- **[EKSİK]** `cancel_order(order_id, symbol)` metodu eklendi — `OrderTracker` tarafından kullanılıyor

#### risk_manager.py
- **[HATA]** `log.critical()` ve `log.debug()` içindeki `%%%.2f` format string hatası düzeltildi → `%%.2f%%`

#### bot_engine.py
- **[HATA]** `_open_exposure()`: `pos["entry"]` ve `pos["qty"]` sözlük erişimi `.get()` ile koruma altına alındı — `KeyError` önlendi

#### config.py
- **[DÜZELTME]** `version` değeri `4.0.0` → `6.1.0` olarak güncellendi

#### ai_layer.py
- **[DÜZELTME]** Docstring sürümü `v5` → `v6.1` olarak güncellendi

### Yeni Dosyalar
- `super_otonom/__init__.py` — `__version__ = "6.1.0"` tanımı
- `requirements.txt` — Bağımlılık listesi
- `README.md` — Kurulum ve kullanım kılavuzu

---

## v6.0.0 (2026-04-24) — Korelasyon + Sentiment Katmanı

### Yeni Dosyalar
- `correlation_manager.py` — Portföy korelasyon risk yöneticisi
- `sentiment_layer.py` — Fear & Greed / haber duyarlılığı filtresi

### Değişen Dosyalar
- `bot_engine.py` — Sentiment veto + korelasyon çarpanı + tick akışı güncellemesi

---

## v5.1.0 (2026-04-24)
- `position_sizer.py`: `validate_and_calculate()` — 3 katmanlı güvenlik filtresi
- `risk_manager.py`: `check_dynamic_risk()` — volatiliteye duyarlı günlük limit
- `analyzer.py`: `analyze_v5_1()` — 4H trend uyum kontrolü

## v5.0.0 (2026-04-23)
- Hurst exponent rejim tespiti
- CircuitBreaker (exchange hata yönetimi)
- Prometheus: slippage, regime, circuit_breaker metrikleri
- AI karar gerekçesi: `get_decision_reason()`, `validate_signal()` üçlüsü
