# Karar Önceliği Mimarisi (P-2)

> **Durum:** Temel atıldı (arbiter + test matrisi, merged). **Wiring (mevcut 20 fazı
> arbiter'dan geçirme) YAPILMADI** — riskli, çok-oturumluk; aşağıdaki yol haritasında.
> Bu belge tek gerçek kaynaktır; değişmez öncelik merdivenini ve gerekçesini tanımlar.

## 1) Değişmez öncelik merdiveni

Küçük numara = yüksek öncelik. **Düşük öncelikli katman, yüksek önceliklinin kararını
ASLA ezemez.**

| # | Katman | Anlamı | Gerçek kaynak (mevcut kod) |
|---|--------|--------|----------------------------|
| 1 | `EMERGENCY_STOP` | Tüm sistemi durdur | `RiskManager.emergency_stop` → phase50 |
| 2 | `FORCE_CLOSE` | Pozisyonları kapat, yeni giriş yok | `risk_pipeline.force_all_close_requested()` → phase68 / signal_pipeline `CLOSE_ALL` |
| 3 | `HARD_LIMIT` | Emir hızı / fiyat sıçraması kill | `kill_switch.HardLimitTracker` / risk_pipeline |
| 4 | `PRE_TRADE_GATE` | Likidite + pre-trade kapıları | `pre_trade_gate` + phase39 |
| 5 | `SIGNAL_QUALITY` | Sinyal kalitesi tabanı | phase64 + `ai.validate_signal` |
| 6 | `EXECUTION_POLICY` | Nihai aktuatör (ENTER/WAIT/HEDGE/EXIT) | FAZ80 `decide_autonomously` |

**Katman tipleri:** 1–5 **gate**'tir (yalnızca kısıtlar). 6 **aktuatör**'dür ve yalnızca
1–5 tümü `ALLOW` ise karar üretir.

## 2) Çözüm sözleşmesi (`arbitrate`)

Katmanlar öncelik sırasında taranır; **ilk bloklayan (ALLOW olmayan) gate kazanır ve
tarama durur.** Tüm gate'ler `ALLOW` ise execution-policy kararı geçerli olur.

**Kanıt — low-cannot-override-high:** ilk blokta `return` edilir; daha düşük öncelikli
katmanlar bu kararı göremez bile, dolayısıyla ezemez. Execution-policy'ye yalnızca tüm
gate'ler `ALLOW` iken ulaşılır → en düşük katman hiçbir gate'i gevşetemez.
`tests/test_decision_arbiter.py` bunu **240 kombinasyonun tamamında** doğrular.

Her karar tek bir izlenebilir çıktı üretir:
`final_action`, `winning_layer`, `decision_reason`, `decision_context` (her katmanın
action/reason/detail + `won` bayrağı).

## 3) Audit bulguları — mevcut sistemdeki kök sorunlar

cProfile/okuma ile doğrulanan, bu mimarinin çözdüğü gerçek kusurlar:

1. **Öncelik emergent.** Karar, çağrı sırası + dağınık guard'larla oluşuyor:
   `execution_pipeline._p0_preserved` (string-tag yaması), `signal_pipeline`
   force_all_close re-check, `autonomous_decision_core` `block_reason` elif zinciri.
2. **Yanlış atıf.** `autonomous_decision_core.py` `block_reason` zinciri phase50 → 73 →
   70 → 69 → **68 (force_close)** sırasında; force_close, manipulation (phase73)'ten
   sonra kontrol edildiğinden ikisi birden HALT iken force_close `override:phase73`
   olarak **yanlış raporlanıyor**.
3. **Tek izlenebilir karar yok.** `decision_reason` üç yere dağılmış (block_reason /
   `out["decision_reason"]` / dctx trace).

> Güvenli yön bozuk değil: `_combine_trade_permission` herhangi bir HALT'ı HALT yapar,
> yani P0 HALT sinyal fazlarınca gevşetilmiyor. Kusur **atıf + izlenebilirlik + kırılgan
> yamalar**dadır — arbiter bunları tek sözleşmeyle değiştirir.

## 4) Wiring yol haritası (KALAN İŞ — riskli, çok-oturumluk)

Arbiter additive'dir; mevcut davranışı değiştirmez. Canlı yola **kademeli** bağlanmalı:

1. **Shadow modu (düşük risk):** `execution_pipeline`'da mevcut faz/bayraklardan
   `arbitrate_from_phases(...)` çağır, sonucu yalnızca `out["decision_context"]` +
   `dctx`'e yaz. Davranış değişmez; canlı veride doğrulanır.
2. **Atıf birleştirme:** `decision_reason`'ı arbiter'ın tek çıktısından üret; `_p0_preserved`
   yamasını ve `block_reason` elif zincirini emekliye ayır.
3. **Enforcement (yüksek risk):** `final_signal`/`final_action`'ı arbiter kararından türet;
   her adımda tam suite (6460 test) + bu matris yeşil kalmalı.

⚠️ **Dürüst uyarı:** Adım 3 haftalar sürer ve aceleye gelirse yeni bug üretir. Her adım
ayrı PR + yeşil CI ile yapılmalı.
