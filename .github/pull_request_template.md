## Özet

<!-- Bu PR ne yapıyor? (birkaç cümle) -->

<!-- İsteğe bağlı tek satır — otomatik: python scripts/governance_pr_items.py [--gate]
     veya el ile: docs/GOVERNANCE_PR_FILE_TO_ITEM_MAP_TR.md → "PR gövdesine yapıştır — şablon"
GOVERNANCE maddeleri (main…HEAD): … — python -m pytest -m release_gate: …

**CI (merge oncesi):** `ci-quick` (fastrun) + **`pytest-full`** (tam suite) + `coverage` yesil.
-->

## Tetiklenen iç kontrol / doküman

PR’daki dosya yollarına göre hangi **1–13** numaralarının düşündürüldüğü: `docs/GOVERNANCE_PR_FILE_TO_ITEM_MAP_TR.md`.

İlgili olanların **hepsini** işaretleyin; yoksa ilk kutuyu seçin.

- [ ] **Yok** — davranış/risk/limit/env değiştirmeyen düzenleme (yorum, typo, saf dokümantasyon *tabi ki risk yoksa*)
- [ ] **`docs/GOVERNANCE_CHECKLIST_TR.md`** — Güncelleme kuralı (PROMPT-A1): execution zinciri, hard safety, `RISK` / env, kill, gate sırası
- [ ] **`super_otonom/decision_context.py`** + **§0.1** — `BotEngine.tick` / `_tick_impl` **faz sırası** veya erken çıkış mantığı anlamlı şekilde değişti (A1 ile aynı PR’da docstring + checklist)
- [ ] **`docs/POLICY_CHAIN_A2.md`** — policy zinciri / emir yüzeyi
- [ ] **`docs/HARD_SAFETY_INVENTORY_A3.md`**
- [ ] **`docs/INSTITUTIONAL_CONTROL_CHECKLIST_TR.md`** — §1 limit, §8 takvim, §9 kara-beyaz, §10 imza *(hangi alt bölüm: PR açıklamasında yazın)*
- [ ] **`docs/RUNBOOK.md`** — tatbikat matrisi veya operasyon prosedürü
- [ ] **Diğer doküman:** <!-- dosya yolu -->

## Üretim / risk etkisi

- [ ] **`RISK`, `.env`, canlı tick veya execution davranışını** etkiliyor (veya etkileyebilir)
- [ ] **Hayır** — üretim davranışı aynı kalır *(test / dokümantasyon / refactor)*

## Kill / emergency sonrası yeniden açma *(yalnız ilgili PR’larda)*

- [ ] **Uygulanmıyor** — bu PR acil kill/disable sonrası yeniden açma veya olay kapanışı değil
- [ ] **Uygulanıyor** — `RUNBOOK` [Senaryo 2](docs/RUNBOOK.md#tatbikat-s2) (sebep + `.env` + yazılı RCO onayı + tek paragraf kapanış); özeti PR gövdesinde veya `data/audit/` referansı verildi

## Test

**Riskli kod:** `GOVERNANCE_CHECKLIST_TR.md` **Güncelleme kuralı** veya aşağıda **üretim/risk** kutusu tetiklendiyse **`pytest -m release_gate` zorunlu** (`docs/RELEASE_GATE_A12.md`). **Doğrulama:** Bu PR’da merge öncesi gate koşuldu — aşağıda işaret + mümkünse **CI run linki** (*lint-test* içinde `release_gate` PASS) veya yerel komut özeti.

- [ ] `pytest -m release_gate` *(veya `scripts/release_gate.ps1` / `release_gate.sh`)* çalıştırıldı ve yeşil
- [ ] Gerekmedi / uygun değil *(kısa gerekçe yorumda — yalnızca davranış/risk/env dokunmayan PR’lar)*

## Onay (PROMPT 8 — çok kişili yapı)

Mevcut varsayılan: **solo RCO** (`INSTITUTIONAL` §10.1). İkinci onaycı tanımlıysa:

- [ ] Solo RCO onayı yeterli (bu PR için)
- [ ] İkinci onay alındı *(kim: …)* — `docs/MULTI_PERSON_GOVERNANCE_AND_FOUR_EYES_BRIDGE_TR.md` ile uyumlu
