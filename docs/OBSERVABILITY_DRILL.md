# Observability drill (PROMPT 3 — Bant 4)

**Son drill:** 2026-05-16 15:10:15 UTC | **Makine:** `DESKTOP-98LUGLH` | **Sonuc:** **PASS**

## URL / portlar (yerel, docker-compose.dev.yml)

| Bileşen | URL |
|---------|-----|
| Prometheus | `http://127.0.0.1:9090` |
| Prometheus alerts UI | `http://127.0.0.1:9090/alerts` |
| Alertmanager | `http://127.0.0.1:9093` |
| Bot metrics | `http://127.0.0.1:8000/metrics` |
| Telegram köprüsü | `http://127.0.0.1:8081/health` , POST `http://127.0.0.1:8081/alert` |
| Grafana Ops | `http://127.0.0.1:3000/d/super-otonom-ops` |

## Hizli calistirma

```powershell
Set-Location -LiteralPath '<repo_koku>'
.\scripts\fastrun_observability.cmd
# yalnizca dogrulama (stack zaten ayaktaysa):
python -m super_otonom.observability_drill
```

**Onkosul:** Docker; istege bagli `data\local\telegram.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID).

## Drill adimlari (otomatik)

| Adim | Sonuc | Not |
|------|--------|-----|
| Prometheus saglik | **PASS** | HTTP 200 |
| Prometheus alert kurallari | **PASS** | groups=1 |
| Bot /metrics (Prometheus scrape hedefi) | **PASS** | HTTP 200; eksik: yok |
| alert_telegram /health | **PASS** | HTTP 200 |
| Alarm teslimi: kasitli test -> Telegram koprusu | **PASS** | Telegram gonderimi OK (HTTP 200) |
| Alertmanager saglik (referans) | **PASS** | HTTP 200 |

## Kabul kriteri

- Stack ayakta **yetmez**; **kasitli test alert** Telegram koprusunden **HTTP 200** donmeli.
- Bot metrikleri `8000/metrics` uzerinde gorunur olmali.
- Prometheus'ta en az bir alert rule grubu yuklu olmali.

## Elle tam zincir (Alertmanager uzerinden, yavas)

1. Prometheus'ta kural tetiklenmesini bekle veya metrikleri kontrol et.
2. `http://127.0.0.1:9093/#/alerts` — alert gorunur mu?
3. Telegram'da mesaj geldi mi?

Hizli yol: drill scripti dogrudan `POST /alert` ile kopruyu test eder.

