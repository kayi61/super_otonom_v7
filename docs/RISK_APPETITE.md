# Risk Appetite Statement + Escalation Matrix (VR-25)

## 1. Risk Appetite Per Category

### 1.1 Market Risk
Bot, kripto varlıklarda yönlü pozisyon taşıyan bir algoritmik strateji çalıştırır.
Piyasa riski, portföy VaR/CVaR metrikleri üzerinden ölçülür ve limitlenir.

| Metric | GREEN | AMBER | RED | CRITICAL |
|--------|-------|-------|-----|----------|
| Portfolio VaR 99% (1d) | ≤ 4% NAV | 4–6% NAV | > 6% NAV | > 10% NAV |
| Portfolio CVaR 97.5% | ≤ 7% NAV | 7–10% NAV | > 10% NAV | > 15% NAV |
| Stressed VaR | ≤ 10% NAV | 10–15% NAV | > 15% NAV | > 2× VaR 99% |
| Model Dispersion | ≤ 30% | 30–50% | > 50% | > 80% |
| Component VaR Concentration | ≤ 25% | 25–40% | > 40% | > 60% |

### 1.2 Liquidity Risk
Likidite riski, pozisyon büyüklüğünün günlük işlem hacmine oranı ve
bid-ask spread genişliği ile ölçülür.

| Metric | GREEN | AMBER | RED | CRITICAL |
|--------|-------|-------|-----|----------|
| LVaR / NAV | ≤ 5% | 5–8% | > 8% | > 12% |
| Position / ADV | ≤ 5% | 5–10% | > 10% | > 20% |
| Spread Widening | ≤ 2× normal | 2–5× normal | > 5× normal | > 10× normal |

### 1.3 Operational Risk
Operasyonel risk, sistem kesintileri, veri kalitesi sorunları ve
süreç hataları ile ilgilidir.

| Metric | GREEN | AMBER | RED | CRITICAL |
|--------|-------|-------|-----|----------|
| Unexplained PnL | ≤ 5 bps | 5–10 bps | > 10 bps | > 25 bps |
| Kupiec p-value | > 0.10 | 0.05–0.10 | < 0.05 | < 0.01 |
| Basel Traffic Light | GREEN | YELLOW (5–9) | RED (≥ 10) | RED + trending |
| System Uptime | > 99.5% | 99–99.5% | < 99% | < 95% |

### 1.4 Counterparty Risk
Karşı taraf riski, borsa ve likidite sağlayıcı bazında izlenir.

| Metric | GREEN | AMBER | RED | CRITICAL |
|--------|-------|-------|-----|----------|
| Exchange Concentration | ≤ 50% NAV | 50–70% NAV | > 70% NAV | > 90% NAV |
| Withdrawal Delay | < 1h | 1–4h | > 4h | > 24h |
| API Error Rate | < 1% | 1–5% | > 5% | > 15% |

## 2. Tolerance Levels

| Zone | Renk | Anlam | Otomatik Aksiyon |
|------|------|-------|-----------------|
| **GREEN** | 🟢 | Normal operasyon, tüm metrikler limit içinde | Yok — bot tam kapasite |
| **AMBER** | 🟡 | Uyarı eşiği aşıldı, yakın izleme gerekli | On-call bildirim; bot devam eder |
| **RED** | 🔴 | Limit ihlali, defansif mod | Pozisyon %50 küçültme, yeni pair ekleme yok |
| **CRITICAL** | ⚫ | Ciddi ihlal, sistem durdurma | `emergency_stop`, tüm pozisyon kapatma, post-mortem 24h zorunlu |

## 3. Specific Limits (VaR Limits Cross-Reference)

`config/var_limits.yaml` ve `super_otonom/risk/var_limits.py` ile uyumlu:

| Limit | VaRLimits Field | Default | Appetite Zone |
|-------|----------------|---------|---------------|
| Strategy VaR 99% | `max_var_per_strategy_pct` | 2% | GREEN ≤ 1.5%, AMBER ≤ 2%, RED > 2% |
| Strategy CVaR 97.5% | `max_cvar_per_strategy_pct` | 3% | GREEN ≤ 2%, AMBER ≤ 3%, RED > 3% |
| Portfolio VaR 99% | `max_var_total_pct` | 6% | GREEN ≤ 4%, AMBER ≤ 6%, RED > 6% |
| Portfolio CVaR 97.5% | `max_cvar_total_pct` | 10% | GREEN ≤ 7%, AMBER ≤ 10%, RED > 10% |
| Stressed VaR | `max_stressed_var_total_pct` | 15% | GREEN ≤ 10%, AMBER ≤ 15%, RED > 15% |
| Marginal VaR per Trade | `max_marginal_var_per_trade_pct` | 0.5% | GREEN ≤ 0.3%, AMBER ≤ 0.5%, RED > 0.5% |
| Component VaR Concentration | `max_component_var_per_position_pct` | 40% | GREEN ≤ 25%, AMBER ≤ 40%, RED > 40% |
| LVaR / NAV | `max_lvar_to_nav` | 8% | GREEN ≤ 5%, AMBER ≤ 8%, RED > 8% |

## 4. Escalation Matrix

### 4.1 Escalation Levels

| Seviye | Tetikleyici | Aksiyon | Bildirim | Süre |
|--------|------------|--------|----------|------|
| **L1 — AMBER** | Herhangi bir metrik AMBER bölgesinde | Bot devam eder; on-call mühendis bilgilendirilir | Telegram/Slack alert | 15 dk içinde gözden geçirme |
| **L2 — RED (Tekil)** | Tek bir metrik RED bölgesinde | Bot defansif mod: pozisyon boyutu %50, yeni pair ekleme yok | On-call + Risk yöneticisi | 1 saat içinde aksiyon planı |
| **L3 — RED (Çoklu)** | 2+ metrik eşzamanlı RED | `emergency_stop` tetiklenir, tüm pozisyonlar kapatılır | On-call + Risk yöneticisi + CTO | 30 dk içinde müdahale |
| **L4 — CRITICAL** | 3σ olay + korelasyon artışı veya exchange riski | Tüm sistemler durdurulur, post-mortem 24h zorunlu | Tüm ekip + yönetim kurulu | Anında müdahale |

### 4.2 Otomatik Escalation Kuralları

```
IF any_metric IN AMBER:
    → notify(on_call, channel="telegram")
    → log_event(severity="warning")
    → bot_continues(full_capacity=True)

IF single_metric IN RED:
    → notify(on_call + risk_manager)
    → bot_defensive_mode(max_size_pct=50, no_new_pairs=True)
    → create_incident(severity="high")

IF count(RED_metrics) >= 2:
    → emergency_stop()
    → notify(on_call + risk_manager + cto)
    → create_incident(severity="critical")
    → require_manual_restart()

IF CRITICAL_event:
    → halt_all_systems()
    → notify(all_team + board)
    → require_postmortem(deadline_hours=24)
    → require_committee_approval_to_restart()
```

### 4.3 Defansif Mod Detayları

| Parametre | Normal | Defansif (RED Tekil) | Kapalı (RED Çoklu / CRITICAL) |
|-----------|--------|---------------------|-------------------------------|
| Pozisyon Boyutu | %100 | %50 | %0 (kapatma) |
| Yeni Pair Ekleme | Evet | Hayır | Hayır |
| Mevcut Pozisyon | Tutulur | Tutulur (küçültülmüş) | Kapatılır |
| VaR Limit Override | Normal | %75 normal | N/A |
| Yeni Strateji Deploy | İzinli | Beklemede | Engelli |

## 5. Approval Levels

| VaR Değişikliği | Onay Makamı | Süre | Gerekli Doküman |
|-----------------|------------|------|-----------------|
| < 2% NAV artış | Desk (Strateji sorumlusu) | Anlık | Slack mesajı yeterli |
| 2–5% NAV artış | Risk Manager | 24 saat | Risk değerlendirme notu |
| > 5% NAV artış | Risk Committee | 1 hafta | Tam risk raporu + senaryo analizi |
| Yeni model ekleme | Risk Committee + Model Validator | 2 hafta | MODEL_VALIDATION_TEMPLATE.md |
| Limit yapısı değişikliği | Risk Committee + Board | 1 ay | Board sunumu + backtest sonuçları |

## 6. Quarterly Review

Risk appetite ve escalation matrisi her çeyrekte gözden geçirilir:

### Review Süreci
1. **Veri toplama**: Son 90 günlük VaR/CVaR/Stress metrikleri
2. **Backtest değerlendirme**: Kupiec, Christoffersen CC, Basel traffic light sonuçları
3. **Limit uygunluğu**: Mevcut limitler vs gerçekleşen risk profili
4. **Piyasa koşulları**: Volatilite rejimi, likidite durumu, makro ortam
5. **Karar**: Limitler güncellenir / korunur / sıkılaştırılır

### Review Takvimi
| Çeyrek | Tarih | Sorumlular |
|--------|-------|-----------|
| Q1 | Ocak 15 | Risk Manager + Committee |
| Q2 | Nisan 15 | Risk Manager + Committee |
| Q3 | Temmuz 15 | Risk Manager + Committee |
| Q4 | Ekim 15 | Risk Manager + Committee + Board |

### Dokümantasyon
- Review sonuçları `docs/risk_reviews/` dizininde saklanır
- Her review `RISK_APPETITE.md` güncelleme gerektirir mi değerlendirilir
- Değişiklikler Change Log'a kaydedilir

## Change Log

| Date | Change | Approved By |
|------|--------|------------|
| 2026-04-01 | Initial risk appetite statement (VR-25) | risk-committee |
