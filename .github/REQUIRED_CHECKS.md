# PR merge — zorunlu CI check'leri

## Faz 1 — otomasyon (senin makinen)

1. `gh auth login` (repo **admin** yetkisi)
2. Repo kökünde:

```powershell
scripts\fastrun_faz1.cmd
```

`setup_branch_protection.ps1` şu check adlarını API’ye yazar (matrix nedeniyle iki coverage):

| Check | Kaynak |
|-------|--------|
| `kanon-drift` | CI |
| `ci-quick` | CI |
| `go-build` | CI |
| `pytest-full` | CI |
| `coverage (3.10)` | CI matrix |
| `coverage (3.12)` | CI matrix |
| `dependency-security` | Security workflow |

**Uyumluluk:** GitHub arayüzündeki tam ad farklıysa (ör. `coverage (Python 3.10)`), bir kez Actions → başarılı koşuda check adını kopyala ve `scripts/setup_branch_protection.ps1` içindeki `$checks` dizisini güncelle.  
`setup_branch_protection.ps1` **`enforce_admins: true`** gönderir — yöneticiler de aynı check’lere tabi (doğrudan push atlaması kapanır); acil durumda geçici olarak kuralı gevşetin.

**Dependabot:** `.github/dependabot.yml` zaten tanımlı (pip + github-actions + docker); merge için `gh pr list --author app/dependabot` veya `fastrun_faz1.cmd`.

---

Workflow: [`.github/workflows/ci.yml`](workflows/ci.yml)

| Check | Job | Açıklama |
|-------|-----|----------|
| `kanon-drift` | kanon-drift | Faz/kanon uyumu |
| `ci-quick` | ci-quick | **Hızlı gate:** ruff, release_gate, **fastrun**, testnet_ci |
| `go-build` | go-build | **Go:** `go_service` + `go_redis_bridge` derlemesi |
| `pytest-full` | pytest-full | **Tam pytest suite** (`tests/`, `-n auto`) |
| `coverage (3.10)` / `coverage (3.12)` | coverage | Tam suite + `--cov-fail-under=90` (matrix) |
| `dependency-security` | dependency-security | pip-audit + SBOM; **critical/high CVE = fail** (workflow: `security.yml`) |

## GitHub ayarı (bir kez — elle veya fastrun_faz1)

### Ücretsiz PRIVATE repo uyarısı (403)

GitHub bazı hesaplarda **ücretsiz private** repository için **`repos/.../branches/.../protection`** REST API’sini kapalı tutar (`Upgrade to GitHub Pro or make this repository public`). Bu durumda `scripts/fastrun_faz1.cmd` **403** ile biter; hata senin scriptinden değil, **plan/repo görünürlüğü** limitinden kaynaklanır.

Ne yapabilirsin (birini seç):

- Repoyu **public** yapmak (API + klasik branch protection genelde açılır).
- **GitHub Pro** / kuruluşta uygun ücretli plan (**Team** vb.).
- API olmadan: **Settings → Branches** üzerinden aşağıdaki kuralları **elle** işaretlemek (UI bazen yine “zorunlu değil” uyarısı verebilir; yine de disiplin + CI ile sürdürülebilir).

---

1. **Settings** → **Branches** → `main` (veya `master`) → **Add rule** / düzenle
2. **Require status checks to pass before merging** ✓
3. **Require branches to be up to date before merging** ✓
4. Ara: `ci-quick`, `go-build`, `pytest-full`, `coverage (3.10)`, `coverage (3.12)`, `kanon-drift`, `dependency-security` → hepsini işaretle

Otomatik (token gerekir):

```powershell
$env:GITHUB_TOKEN = "ghp_..."   # repo admin
powershell -File scripts/setup_branch_protection.ps1 -Branch main
```

`gh` kuruluysa: `gh auth login` sonra aynı script.
