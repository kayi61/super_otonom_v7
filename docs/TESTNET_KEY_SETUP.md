# Binance Testnet Anahtar Kurulumu + Doğrulama (kök sebep: 1-char Vault key)

> **Neden bu belge:** Vault'taki mevcut anahtar **1 karakter** (geçersiz) → bot bakiyeyi
> çekemiyor. Sebep: `getpass` Windows PowerShell'de yapıştırmayı tam yakalayamıyor.
> Aşağıdaki yol bu bug'ı **tamamen atlar** ve sonucu **kesin doğrular**.

## 0) Ön koşul
- Docker + Vault ayakta ve **unsealed** (`docker compose up -d vault`, sonra unseal).
- Binance **Testnet** Spot anahtarı: https://testnet.binance.vision (Github ile giriş → "Generate HMAC_SHA256 Key"). Bu **gerçek hesap anahtarı DEĞİL** — testnet.

## 1) Anahtarı seed et — `--from-env` (getpass paste bug'ını atlar)

PowerShell'de (anahtarlar shell geçmişine düşmesin diye tek oturumda):

```powershell
$env:SEED_API_KEY    = '<testnet_api_key_buraya>'
$env:SEED_API_SECRET = '<testnet_api_secret_buraya>'
python scripts/seed_binance_to_vault.py --from-env
$env:SEED_API_KEY = $null; $env:SEED_API_SECRET = $null   # temizle
```

`seed_binance_to_vault.py` anahtar **<16 karakter** ise REDDEDER (1-char bug erken yakalanır).

## 2) DOĞRULA — gerçek kimlikli probe (kesin cevap)

```powershell
python -m super_otonom.infra.binance_testnet_preflight
```

Çıktı kesin verdiktir (sır maskelenir, asla yazılmaz):

| Sonuç | Anlamı | Aksiyon |
|-------|--------|---------|
| `[PASS] stage=probe ... USDT=...` | Anahtar testnet'te çalışıyor | Bot çalışmaya hazır |
| `[FAIL] stage=resolve` | Vault'ta anahtar yok | Adım 1'i yap |
| `[FAIL] stage=validate ... COK KISA` | 1-char bug tekrarı | Adım 1'i `--from-env` ile yap |
| `[FAIL] stage=probe ... -2014` | Anahtar formatı bozuk | Anahtarı yeniden üret + seed |
| `[FAIL] stage=probe ... -2015` | Geçersiz anahtar / IP / izin | Testnet anahtarı + IP whitelist kontrol |
| `[FAIL] stage=probe ... Ag` | Ağ/DNS/proxy | İnternet/erişim kontrol |

## 3) Notlar
- Canlı (mainnet) için: `SECRETS_VAULT_ONLY=true` ve **gerçek** anahtar; preflight yalnızca
  **testnet**'i doğrular (`set_sandbox_mode` → `testnet.binance.vision`).
- Anahtar `.env`'e veya shell geçmişine **yazılmaz** — yalnızca Vault KV'de durur.
- Preflight'in `_default_handler` / canlı-Vault / CLI yolları gerçek ağ gerektirdiğinden
  birim testte mock'lanmaz; doğrulama bu komutun **kendisini çalıştırmanla** tamamlanır.
