# Model Validation Report Template (VR-24)

## 1. Model Identification

| Field | Value |
|-------|-------|
| **Model ID** | MR-XXX |
| **Model Name** | |
| **VR Reference** | VR-XX |
| **Module** | `risk/xxx.py` |
| **Version** | |
| **Validation Date** | YYYY-MM-DD |
| **Next Due** | YYYY-MM-DD |

## 2. Personnel

| Role | Name | Sign-off Date |
|------|------|--------------|
| **Model Developer** | | |
| **Model Validator** | | |
| **Risk Committee Reviewer** | | |

> **KURAL:** Model developer ≠ Model validator. Aynı kişi hem geliştirici hem doğrulayıcı olamaz.

## 3. Model Description

### 3.1 Purpose
<!-- Modelin amacı ve kullanım alanı -->

### 3.2 Methodology
<!-- Matematiksel formülasyon, varsayımlar, referans akademik makaleler -->

### 3.3 Inputs / Outputs

| Direction | Name | Type | Description |
|-----------|------|------|-------------|
| Input | | | |
| Output | | | |

### 3.4 Assumptions & Limitations
<!-- İstatistiksel varsayımlar, bilinen sınırlamalar, edge-case davranışları -->

## 4. Implementation Review

### 4.1 Code Quality
- [ ] Ruff lint temiz (sıfır hata)
- [ ] Type hint'ler eksiksiz
- [ ] Docstring'ler güncel
- [ ] Güvenlik açığı yok (OWASP kontrol)

### 4.2 Test Coverage
- [ ] Birim testler mevcut (`tests/risk/test_*_vrXX.py`)
- [ ] Edge case'ler test edilmiş
- [ ] Regresyon testleri mevcut
- [ ] Test sayısı: ___

### 4.3 Configuration
- [ ] `RiskConfig` parametreleri doğru tanımlı
- [ ] Varsayılan değerler Basel/FRTB uyumlu
- [ ] Override mekanizması (env > YAML > default) çalışıyor

## 5. Statistical Validation

### 5.1 Backtesting
<!-- Kupiec POF, Christoffersen CC, Basel traffic light sonuçları -->

| Test | p-value | Result | Threshold |
|------|---------|--------|-----------|
| Kupiec POF | | PASS/FAIL | > 0.05 |
| Christoffersen CC | | PASS/FAIL | > 0.05 |
| Basel Traffic Light | | GREEN/YELLOW/RED | GREEN |

### 5.2 Benchmark Comparison
<!-- Alternatif model veya referans değerlerle karşılaştırma -->

| Metric | This Model | Benchmark | Deviation |
|--------|-----------|-----------|-----------|
| VaR 99% | | | |
| CVaR 97.5% | | | |

### 5.3 Sensitivity Analysis
<!-- Parametre değişikliklerine model hassasiyeti -->

### 5.4 Stress Testing
<!-- Stres senaryolarında model performansı -->

## 6. Data Quality

- [ ] Veri kaynağı doğrulanmış
- [ ] Minimum gözlem sayısı kontrol edilmiş
- [ ] Eksik veri işleme mekanizması mevcut
- [ ] Aykırı değer (outlier) kontrolü yapılmış

## 7. Operational Integration

- [ ] Prometheus metrik entegrasyonu aktif
- [ ] Grafana dashboard paneli mevcut
- [ ] Alert kuralları tanımlı
- [ ] Kill-switch entegrasyonu (varsa)
- [ ] Günlük risk raporunda yer alıyor

## 8. Findings & Recommendations

### 8.1 Findings

| # | Severity | Finding | Recommendation |
|---|----------|---------|---------------|
| 1 | | | |

### 8.2 Overall Assessment

- [ ] **APPROVED** — Model production kullanımına uygun
- [ ] **CONDITIONAL** — Belirtilen düzeltmeler yapıldıktan sonra tekrar değerlendirilecek
- [ ] **REJECTED** — Model production kullanımına uygun değil

## 9. Sign-off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Model Validator | | | |
| Risk Committee | | | |
