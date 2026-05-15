# PR merge — zorunlu CI check'leri

Workflow: [`.github/workflows/ci.yml`](workflows/ci.yml)

| Check | Job | Açıklama |
|-------|-----|----------|
| `kanon-drift` | kanon-drift | Faz/kanon uyumu |
| `ci-quick` | ci-quick | **Hızlı gate:** ruff, release_gate, **fastrun**, testnet_ci |
| `pytest-full` | pytest-full | **Tam pytest suite** (`tests/`, `-n auto`) |
| `coverage` | coverage | Tam suite + `--cov-fail-under=90` (3.10 + 3.12) |
| `dependency-security` | dependency-security | pip-audit + SBOM; **critical/high CVE = fail** (workflow: `security.yml`) |

## GitHub ayarı (bir kez)

1. **Settings** → **Branches** → `main` (veya `master`) → **Add rule** / düzenle
2. **Require status checks to pass before merging** ✓
3. **Require branches to be up to date before merging** ✓
4. Ara: `ci-quick`, `pytest-full`, `coverage`, `kanon-drift` → hepsini işaretle

Otomatik (token gerekir):

```powershell
$env:GITHUB_TOKEN = "ghp_..."   # repo admin
powershell -File scripts/setup_branch_protection.ps1 -Branch main
```

`gh` kuruluysa: `gh auth login` sonra aynı script.
