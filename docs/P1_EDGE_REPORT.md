# P-1 — Edge Kanıtı Raporu (DÜRÜST, ACI)

> **Tarih:** 2026-06-07 · **Veri:** Binance kamu OHLCV (gerçek) · **Aparat:** `super_otonom.signals.edge_evidence`
> (gerçek `BotEngine.tick` + fee + slippage + WFA).
>
> ⚠️ Bu, P-1'in "bitti" raporu DEĞİLDİR. P-1 aylar + canlı zaman ister. Bu, **bugün gerçek
> veriyle yapılabilen ilk dürüst ölçüm** ve sonucu acıdır.

## TL;DR — VERDİKT
**Sistemin pozitif beklentisi GÖSTERİLEMEDİ. Kabul kriteri gereği: sistem "KAZANAN" DEĞİLDİR.**
Daha da kötüsü: varsayılan config ile **bot gerçek veride HİÇ işlem açmadı (0 trade, %100 HOLD).**
Edge ölçülemez bile — çünkü ölçülecek işlem yok.

## Ölçüm (gerçek veri, fee=10 bps/taraf, slippage 2–12 bps)

| Test | Bar | İşlem | Getiri % | Sharpe | MDD % | HOLD % |
|------|-----|-------|----------|--------|-------|--------|
| BTC/USDT 1d (~16 ay) | 465 | **0** | 0.00 | 0.00 | 0.00 | 100% |
| BTC/USDT 4h (~83 gün) | 465 | **0** | 0.00 | 0.00 | 0.00 | 100% |
| SOL/USDT 4h (~83 gün) | 465 | **0** | 0.00 | 0.00 | 0.00 | 100% |
| Canlı testnet (BTC/ETH/BNB/SOL) | 4 tick | **0** | — | — | — | 100% |

Tüm final sinyaller: `{"HOLD": ...}`. Tek bir giriş bile yok.

## Yeniden üretim (tek komut)
```bash
python -m super_otonom.signals.edge_evidence --source ccxt --symbol BTC/USDT \
  --timeframe 4h --limit 500 --fee-bps 10 --no-wfa --json
```
(1d için `--timeframe 1d`; WFA fold'lar için `--no-wfa` kaldır — ama 1000 bar + WFA yavaş.)

## Neden 0 işlem? (gözlemlenen + hipotez — gizlenmeden)
1. **Günlük (1d) barlarda:** `EMERGENCY_STOP | price_spike` tekrar tekrar tetiklendi. Botun
   fiyat-sıçrama guard'ı **intraday (1h/4h) için ayarlı**; günlük normal volatilite (%5–10) "spike"
   sanılıp her giriş engelleniyor → yanlış timeframe.
2. **4h'te:** spike guard tetiklenmiyor (0 emergency) ama **yine 0 işlem.** Canlı koşuda görülen
   sebep: `REGIME_BLOCKED_MEAN_REVERTING` — rejim filtresi + sinyal-kalitesi + güven eşikleri
   üst üste binince **hiçbir aday giriş geçemiyor.**
3. Filtreler o kadar muhafazakâr ki sistem pratikte **hiç oynamıyor.** Bu "para kaybetmek" değil;
   "masaya hiç oturmamak" — ve edge masada kanıtlanır.

## KÖK SEBEP TEŞHİSİ (ölçüldü — hipotez değil)

`scripts/edge_decision_diag.py` ile BTC 4h (365 tick) üzerinde ham sinyal vs nihai karar:

```
HAM SİNYAL (analyzer):  HOLD=364, SELL=1, BUY=0   (giriş oranı ≈ 0.003)
REJİM:                  MEAN_REVERTING=301, NOISY=44, TRENDING=20
NİHAİ SİNYAL:           HOLD=365
KARAR SEBEBİ:           REGIME_BLOCKED_MEAN_REVERTING=301, REGIME_BLOCKED_NOISY=40, ''=23
HAM=BUY/SELL iken öldüren: AI_MODEL_FALLBACK=1  (tek SELL adayı)
```

**Üç katmanlı kök sebep (hepsi gerçek):**
1. **Analizör neredeyse hiç giriş üretmiyor:** 365 barda 0 BUY, 1 SELL. Kapılar "iyi sinyali"
   öldürmüyor — ortada sinyal yok.
2. **Strateji trend-takip ama piyasa %93 trend DEĞİL:** MEAN_REVERTING+NOISY = %93, TRENDING %5.5.
   Trend botu choppy piyasada doğru olarak kenarda duruyor.
3. **Rejim filtresi trend-dışı her şeyi blokluyor** (`REGIME_BLOCKED_*`).

Yani 0-işlem = kısmen doğru davranış (trend botu chop'ta beklemeli) + kısmen test penceresi
trendsizdi + kısmen aparat geçmiş trend dönemini seçip çekemiyor. **Cevaplanmamış asıl soru:
trend OLAN bir dönemde bu bot fee sonrası kazanıyor mu?** — trendli geçmiş veriye erişim gerek.

Yeniden üretim: `python scripts/edge_decision_diag.py --symbol BTC/USDT --timeframe 4h --limit 400`

## BOĞA KOŞUSU TESTİ — en çarpıcı kanıt (sayfalamalı geçmiş veri)

`scripts/edge_window_backtest.py` ile bilinen güçlü trend: **BTC/USDT 4h, 2024-01-01 → 2024-04-01**
(fiyat 42.330 → 70.588, **buy&hold +66.75%**), gerçek `BotEngine.tick` + fee 10bps + slippage:

| Metrik | Değer |
|--------|-------|
| Buy & Hold | **+66.75%** |
| **BOT getirisi** | **0.0%** |
| **BOT işlem** | **0** |
| Rejim dağılımı | NOISY 188 / MEAN_REVERTING 276 / **TRENDING sadece 48 (%9)** |
| Ham BUY sinyali | 12 (bu kez üretildi) → hepsi öldürüldü |
| Öldüren sebepler | REGIME_BLOCKED_NOISY 182, REGIME_BLOCKED_MEAN_REVERTING 122, AI_CAUTION_HIGH_VOLATILITY 27, AI_MODEL_FALLBACK 5, LOW_QUALITY 2 |

**Bot, +66% net bir yükselişi tamamen kaçırdı (0 işlem, +0%), buy&hold +66.75% yaparken.**

### Somut kök sebepler (düzeltilebilir)
1. **Rejim dedektörü yanlış ayarlı:** %66 yükselen trendi %90 NOISY/MEAN_REVERTING, yalnızca %9
   TRENDING sınıflıyor → trend botu trendi göremiyor.
2. **Kapı yığını:** 12 BUY adayı `AI_CAUTION_HIGH_VOLATILITY` / `AI_MODEL_FALLBACK` / `LOW_QUALITY`
   ile öldürüldü. `AI_MODEL_FALLBACK` = LSTM modeli yüklü değil (eğitilmiş model yok → temkinli).
3. **Sonuç:** ideal koşulda (güçlü trend) bile sıfır işlem.

Yeniden üretim:
```bash
python scripts/edge_window_backtest.py --symbol BTC/USDT --timeframe 4h \
  --start 2024-01-01 --end 2024-04-01 --fee-bps 10
```

### Düzeltme sırası (sorumlu — işlem uydurmadan)
1. **Rejim dedektörünü kalibre et** (trendi trend olarak tanısın) — `regime_detector` eşikleri.
2. **Kapı yığınını gözden geçir** (AI fallback temkini, LOW_QUALITY eşiği) — bir trend girişinin
   geçebileceği gerçekçi bir yol bırak.
3. **LSTM modelini eğit** (`lstm_trainer`) veya AI fallback davranışını düzelt.
4. HER değişiklikten sonra bu backtest'i tekrar koş; işlem sayısı + fee sonrası net getiri ölç.

## Dürüst sınırlamalar (aparat + metodoloji)
- **12 ay yüksek-frekans yok:** `fetch_ccxt_candles` tek çağrı (≈1000 bar tavanı, sayfalama yok).
  → 1d ile 16 ay olur ama yanlış-TF; 4h ile yalnızca ~166 gün, 1h ile ~41 gün. **Gerçek 12 ay × 1h/4h
  için sayfalamalı veri çekici gerekli (aparat eksiği).**
- **Order book yok:** backtest yalnızca mum besliyor; OB-bağımlı kapılar (derinlik/spread) backtest'te
  default davranır. 0-işlem'in bir kısmı bu artefakt olabilir — **kesinleştirmek için HOLD-sebep
  dağılımı enstrümante edilmeli (bir sonraki adım).**
- **Survivorship:** point-in-time evren takvimi kullanılmadı (mekanik doğrulama).

## P-1 GERÇEKTE ne gerektiriyor (sıra)
1. **ÖNCE botu işlem açar hale getir:** 0-işlem kök sebebini teşhis et (rejim/kalite/güven eşikleri
   mi, yoksa OB-artefakt mı). Eşikleri **sorumlu şekilde** ayarla — sonucu uydurmadan.
2. **SONRA** sayfalamalı 12+ ay × 1h/4h veriyle out-of-sample walk-forward + fee/slippage → net
   beklenti + Sharpe + MDD + istatistiksel anlamlılık.
3. **SONRA** testnet'te min 30 gün kesintisiz canlı karar dağılımı.
4. Ancak fee+slippage sonrası **istatistiksel anlamlı pozitif beklenti** gösterilirse "kazanan" denir.

## Sonuç (acımasız)
Altyapı/güvenlik/araç sağlam ve kanıtlı. Ama **kârlılık iddiası SIFIR kanıtlıdır** — üstelik
sistem şu an **işlem bile açmıyor.** "Bot çalışıyor = para kazanıyor" çıkarımı **yanlıştır.**
P-1 buradan başlar ve aylar sürer; bu rapor başlangıç çizgisini dürüstçe işaretler.
