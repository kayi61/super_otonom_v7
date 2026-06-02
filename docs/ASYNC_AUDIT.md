# Async Critical Path Audit (PROMPT-10)

Tick döngüsündeki senkron (bloke eden) I/O noktalarının envanteri, etkisi ve
alınan/önerilen aksiyonlar. Amaç: asyncio event loop'unu disk/ağ I/O ile bloke
etmemek — yüksek frekanslı tick'lerde gecikme (latency) ve ölçekleme bariyerini
azaltmak.

## Yöntem

- `scripts/profile_tick.py --dry-run` ile tick sıcak yolu cProfile altında ölçüldü.
- `scripts/memory_check.py` ile sabit-durum bellek büyümesi tracemalloc ile izlendi.
- Kaynak taraması: `open(...)`, `.write(...)`, `json.dump`, `time.sleep`, senkron
  HTTP çağrıları.

## Bulgular

| # | Konum | Tür | Frekans | Etki | Durum |
|---|-------|-----|---------|------|-------|
| A1 | `core/bot_engine.py` · `TradeLogger.log_trade` | `open(a)+write` | İşlem başına | Event loop'u disk yazımı süresince bloke eder | ✅ **Çözüldü** — opt-in `AsyncWriteBuffer` |
| A2 | `engine_managers.py` · `StateManager.save` | atomik `fdopen`+`json.dump` | Periyodik (state kaydı) | Düşük frekans; atomik yazım (tmp+rename) | 🟡 Düşük öncelik — periyodik, tick dışı |
| A3 | `trading/order_engine.py:492` · order log append | `open(a)+write` | Emir başına | Emir gönderim yolu zaten I/O-bound (borsa) | 🟡 Önerilen — aynı buffer deseni |
| A4 | `trading/order_engine.py:519` · pending kaydı | `json.dump` | Emir başına | Küçük dosya; emir yolu | 🟡 Önerilen |

> **Not:** Tick döngüsünün asıl maliyeti (profil çıktısı) BUY/SELL tick'lerinde
> risk motoru + sinyal füzyonudur (CPU-bound), HOLD tick'leri ~5 ms. Disk I/O
> ataklarının asenkronlaştırılması, yazımın event loop'u durdurmasını engeller.

## Çözüm: `AsyncWriteBuffer` (`super_otonom/async_io.py`)

Bloke etmeyen, thread destekli, append-only satır yazıcı:

- `write(line)` — yalnızca sınırlı kuyruğa ekler (mikro-saniye); disk beklemez.
- Arka plan **daemon thread** satırları toplu (batched) olarak `a` modunda yazar.
- Kuyruk dolarsa **drop-oldest** (en eskiyi düşür) + `dropped` sayacı → sınırlı bellek.
- `flush()` / `close()` — temiz kapanışta kalan satırları drain eder.
- I/O hatası **üreticiyi bozmaz** (savunmacı `try/except`).

### TradeLogger entegrasyonu (A1)

`TradeLogger` artık opt-in async tampon destekler — **varsayılan davranış senkron
kalır** (geriye uyumluluk; mevcut testler değişmez):

```python
# Senkron (varsayılan, değişiklik yok)
tl = TradeLogger("data/trades.log")

# Async tampon — env veya parametre ile
#   TRADE_LOG_ASYNC=1   (ortam değişkeni)
tl = TradeLogger("data/trades.log", async_buffer=True)
tl.log_trade({...})   # bloke etmez — kuyruğa alır
tl.flush()            # diske boşalt
tl.close()            # kapanışta drain (BotEngine.shutdown() çağırır)
```

`BotEngine.shutdown()` → `trade_logger.close()` ile kalan satırlar güvenle yazılır.

## Profiling / Bellek Altyapısı

| Araç | Komut | Amaç |
|------|-------|------|
| Tick profili | `python scripts/profile_tick.py --dry-run` | cProfile sıcak yol tablosu + latency |
| Bellek kontrolü | `python scripts/memory_check.py --ticks 500` | tracemalloc sabit-durum büyüme kapısı |
| Koşullu profil | `@profile_method` + `ENABLE_PROFILING=1` | Üretimde belirli fonksiyon profili |
| Prometheus | `bot_memory_rss_bytes`, `bot_tick_latency_ms` | Canlı RSS + p95 tick gecikmesi (her 60 tick) |

### py-spy (opsiyonel, ayrı kurulum)

Üretimde örnekleme tabanlı profil (kod değişikliği gerektirmez):

```bash
py-spy record -o tick.svg --pid <bot_pid>
py-spy top --pid <bot_pid>
```

## Sonraki Adımlar (önerilen, bu PR kapsamı dışı)

- A3/A4: `order_engine.py` log/pending yazımlarını `AsyncWriteBuffer`'a taşı.
- Canlı ortamda `bot_tick_latency_ms` için Grafana paneli + p95 > eşik uyarısı.
- `memory_check.py`'yi nightly CI'a sızıntı kapısı olarak ekle (uygun warmup ile).
