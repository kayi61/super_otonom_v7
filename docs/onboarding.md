# Developer Onboarding

Step-by-step guide for new contributors.

## 1. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.10 – 3.12 | Runtime (3.12 recommended) |
| Git | 2.40+ | Version control |
| Docker & Compose | 24+ / v2 | Local stack (Postgres, Redis, Vault, Prometheus, Grafana) |
| pyenv (optional) | latest | Python version management |

## 2. Clone & Environment Setup

```bash
git clone https://github.com/kayi61/super_otonom_v7.git
cd super_otonom_v7

# Create virtual environment
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Install with dev extras
pip install -e ".[dev]"
```

!!! tip "pyenv workflow"
    ```bash
    pyenv install 3.12.4
    pyenv local 3.12.4
    python -m venv .venv
    ```

## 3. Docker Stack

```bash
# Copy env template (never commit .env)
cp .env.template .env        # fill API keys, DB passwords

# Start core services
docker compose up -d          # bot, postgres, redis, vault, prometheus, grafana

# Dev overlay (exposes Grafana/Prometheus ports locally)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# TLS (production)
# scripts/gen_internal_tls.ps1   # generate certs first
# docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

### Service Endpoints (dev overlay)

| Service | URL | Notes |
|---|---|---|
| Prometheus | `http://localhost:9090` | Metrics |
| Grafana | `http://localhost:3000` | Dashboards (admin/admin) |
| Vault | `http://localhost:8200` | Secrets (dev root token in .env) |
| Postgres | `localhost:5432` | TimescaleDB |

## 4. Running Tests

```bash
# Quick smoke (< 2 min)
pytest -m "not hypothesis" -q

# Full suite (all 1000+ tests)
pytest

# Risk engine tests only
pytest tests/risk/ -q

# Single VR module
pytest tests/risk/test_var_models_vr02.py -v

# Property-based (Hypothesis) tests
pytest -m hypothesis --hypothesis-seed=0

# Mutation testing (local, single module)
pip install "mutmut>=2.4,<3"
mutmut run --paths-to-mutate super_otonom/risk/var_models.py \
  --runner "python -m pytest tests/risk/test_var_models_vr02.py -x -q --tb=no"
```

!!! warning "numpy/scipy for mutation testing"
    mutmut re-imports modules per mutant. numpy 2.x C extensions refuse
    re-import. Pin compatible versions:
    ```bash
    pip install "numpy>=1.24,<2" "scipy>=1.11,<1.14"
    ```

## 5. Lint & Format

```bash
# Check
ruff check super_otonom/ tests/

# Auto-fix
ruff check --fix super_otonom/ tests/
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`.

## 6. Branch & PR Workflow

```text
main (protected — 7 required checks)
 └── feat/vr-XX-short-description   (feature)
 └── fix/issue-NNN-description      (bugfix)
 └── docs/prompt-NN-description     (documentation)
```

### Step by Step

1. **Branch off main:**
   ```bash
   git checkout main && git pull origin main
   git checkout -b feat/vr-XX-my-feature
   ```

2. **Develop → lint → test → commit:**
   ```bash
   ruff check --fix .
   pytest tests/risk/ -q
   git add -A && git commit -m "feat(risk): VR-XX short description"
   ```

3. **Push & create PR:**
   ```bash
   git push -u origin feat/vr-XX-my-feature
   gh pr create --title "feat(risk): VR-XX short description" --body "..."
   ```

4. **CI must pass** (7 required checks):
   - `ci-quick` — ruff + fast tests
   - `pytest-full` — full suite
   - `coverage (3.10)` / `coverage (3.12)` — branch coverage gate
   - `integration-test` — Docker smoke
   - `go-build` — Go bridge compilation
   - `kanon-drift` — manifest drift check
   - `release-gate (windows)` — Windows smoke

5. **Merge** after review + green CI.

### Commit Convention

```
type(scope): short description

# Types: feat, fix, test, ci, docs, refactor, chore
# Scopes: risk, ci, prompt-NN, vr-XX, test, docker
```

Release Please auto-generates CHANGELOG from conventional commits.

## 7. Module Map (Where Things Live)

```text
super_otonom/
├── core/            # BotEngine, MainLoop, Config, StateMachine
├── trading/         # OrderEngine, PositionSizer, StagedExit
├── risk/            # VaR/CVaR suite (18 modules, VR-01 → VR-27)
├── execution/       # TWAP, VWAP algo engines
├── signals/         # Alpha signals, sentiment, edge evidence
├── ha/              # HA coordinator, leader election, health check
├── infra/           # Redis, Vault, TimescaleDB, WebSocket, logging
├── analysis/        # Analyzer, CorrelationManager, RiskOntology
├── monitoring/      # AlertManager, Prometheus, deploy checks
├── audit/           # Package/VaR topology, bot engine audit
└── pipelines/       # Data pipeline modules
```

See [Architecture](architecture.md) for data flow diagrams.
