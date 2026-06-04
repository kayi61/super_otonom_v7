# GitHub Developer Activity Tracker (PROMPT-5.3)

`super_otonom/signals/developer_activity_tracker.py` — kripto proje geliştirici
aktivitesini takip eder; `alternative_data_engine` (Faz 27) developer bölümünü
zenginleştirir.

Kaynak: GitHub API (ücretsiz, 5000 req/saat; `GITHUB_TOKEN` ile, injectable
`http_get`). Analiz fonksiyonları saftır; testler ağsız
(`tests/test_developer_activity_tracker_p53.py`).

## 1. GitHub metrikleri (`analyze_github_metrics`)

- Commit frekansı (30/90g) → **momentum** (`(c30 − c90/3) / (c90/3)`, −1..1).
- Unique contributor sayısı, PR merge hızı (`merged/opened`), issue kapanma oranı
  (`closed/opened`), star/fork growth.
- `activity_score` (0..1) ağırlıklı bileşim.

## 2. Red flag tespiti (`detect_red_flags`)

| Flag | Risk |
|------|------|
| Commit 0 / > 60g commit yok → terkedilmiş | 0.8 |
| Bus factor = 1 (tek geliştirici) | 0.5 |
| Sadece version bump (şüpheli pattern) | 0.4 |
| README-only (marketing, gerçek dev yok) | 0.42 |

## 3. Pozitif sinyal (`detect_positive_signals`)

- Mainnet/upgrade branch → yaklaşan upgrade (+0.30).
- Büyük refactoring → olgunlaşma (+0.18).
- Yeni developer onboarding (≥3) (+0.20).
- Audit firma commit'leri → security audit yaklaşıyor (+0.24).

## 4. Karşılaştırmalı analiz (`comparative_analysis`)

- `relative_rank` — peer projelerin aktivitesine göre yüzdelik.
- **`dev_per_fdv`** = `commits_30d / (FDV / $1M)` — yüksek → **undervalued** proje
  (dev/FDV ≥ 1 + aktivite ≥ 0.45 → `undervalued = True`).

## Birleşik sinyal (`analyze_developer_activity` → `DeveloperSignal`)

- `health = activity × (1 − 0.6×risk)`.
- `alpha_bias = pozitif_sinyal + 0.25×momentum − 0.5×risk (+0.15 undervalued)`.
- `risk_score` = red flag riski.

## Faz 27 entegrasyonu (`alternative_data_engine`)

`developer` alt dict'inde **genişletilmiş** GitHub metrikleri varsa:
- `activity_score` temel developer skoruyla harmanlanır (`0.5/0.5`).
- `risk_score` = `max(risk, developer_risk_score)` (red flag → risk).
- `alpha_score` += `0.10 × developer_alpha_bias` (pozitif sinyal/undervalued → alpha).
- `alternative_data.developer_deep` bloğu eklenir.

**Geriye uyumluluk**: yalın `commits_30d`/`pr_count` (temel) → yeni modül
**tetiklenmez** (eski `_developer_scores` davranışı korunur); yalnız genişletilmiş
metrikler (`commits_90d`, `unique_contributors`, `bus_factor`, `upgrade_branch`,
`fdv_usd` vb.) geldiğinde aktive olur. Hata Faz 27'yi asla bozmaz.
