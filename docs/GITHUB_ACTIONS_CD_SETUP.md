# GitHub Actions — CD + Release Please kurulum

## CD workflow yeşil değilse

1. **Geçersiz tag filtresi:** `tags: ["v*.*.*"]` GitHub'da geçersizdir → `tags: ["v*"]` kullanın.
2. **Docker build:** `Dockerfile` içinde `COPY _setup_build.py` olmalı (`pyproject.toml` build hook).
3. **Staging:** GHCR login + `BOT_IMAGE_REPO=owner/repo` (lowercase, `ghcr.io` prefix compose'da).

## Release Please kırmızıysa (PR oluşturamıyor)

Hata: `GitHub Actions is not permitted to create or approve pull requests`

**Çözüm (repo sahibi, bir kez):**

1. GitHub → **Settings** → **Actions** → **General**
2. **Workflow permissions** → **Read and write permissions**
3. **Allow GitHub Actions to create and approve pull requests** kutusunu işaretle
4. Save

**Alternatif:** `RELEASE_PLEASE_TOKEN` secret (PAT, `contents` + `pull_requests` scope).

## Manuel tetikleme

```bash
gh workflow run "CD (Docker Build + GHCR Push + Staging Deploy)" --ref main
gh workflow run "Release Please (Conventional Commits)" --ref main
```
