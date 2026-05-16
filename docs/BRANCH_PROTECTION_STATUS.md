# Branch protection durumu - kayi61/super_otonom_v7 @ main

**Son dogrulama:** 2026-05-16 13:13:04 UTC  
**Durum:** **AKTIF** - API ile dogrulandi  
**HEAD SHA:** `c2bd0e320c06f0c8496aa9466b7cb0ed8aa17ee4`

## API ozeti

| Ayar | Deger |
|------|--------|
| Require status checks | evet |
| Require branches up to date (strict) | True |
| Enforce admins | True |
| Required approving reviews | 0 |

## Zorunlu status check'ler (GitHub API)

- `kanon-drift`
- `ci-quick`
- `pytest-full`
- `coverage (3.10)`
- `coverage (3.12)`
- `dependency-security`
- `go-build`

## Beklenen liste (`.github/REQUIRED_CHECKS.md`)

- `kanon-drift`
- `ci-quick`
- `go-build`
- `pytest-full`
- `coverage (3.10)`
- `coverage (3.12)`
- `dependency-security`

## Son commit check-run'lari

| Check | Sonuc | Zorunlu listede |
|-------|--------|-----------------|
| `ci-quick` | success | evet |
| `coverage (3.10)` | success | evet |
| `coverage (3.12)` | success | evet |
| `dependency-security` | success | evet |
| `go-build` | success | evet |
| `kanon-drift` | success | evet |
| `pytest-full` | success | evet |
| `release-gate (windows)` | success | - |


## Yenileme

```powershell
scripts\report_branch_protection_status.cmd
```

Kurulum: `scripts\fastrun_faz1.cmd` veya `scripts\setup_branch_protection.ps1 -Branch main`

403 (ucretsiz private): `.github/REQUIRED_CHECKS.md` - elle Settings -> Branches.
