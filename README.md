# Country Risk Model

Web application that converts Anchor Point Risk's Excel country-risk prototype into a versioned, auditable scoring system. Scores feed the firm's PD and LGD rating models via a REST API.

## What's built

| Layer | Status |
|---|---|
| FastAPI backend (Python 3.12) | ✅ |
| React + TypeScript SPA (Vite) | ✅ |
| Supabase Postgres (auth, RLS, 8 migrations) | ✅ |
| World Bank ingestion (5 indicators, 1960–2024, ~24k rows) | ✅ |
| Scoring engine: standardisation + buckets + Ridge + blending Ridge | ✅ |
| Snapshot lifecycle: draft → publish (immutable, audit-gated) | ✅ |
| Model lifecycle: pending_review → approved → active → retired | ✅ |
| Public read API (`/v1/*`) for PD/LGD consumers | ✅ |
| Country list + detail pages with driver/history/peer charts | ✅ |
| Admin model-management UI with diagnostics CSV/Excel export | ✅ |

## Stack
- **Backend:** FastAPI + Python 3.12 (`backend/`)
- **Frontend:** React + Vite + TypeScript + TanStack Query + Recharts (`frontend/`)
- **DB / Auth:** Supabase Postgres with Row-Level Security (`supabase/`)

## Repo layout

```
country-risk-model/
├── prototype/                  # original Excel file (regression-test source of truth)
├── backend/
│   ├── app/
│   │   ├── domain/            # pure-Python scoring engine (framework-free)
│   │   ├── services/          # orchestration: training, ingestion, snapshots, peer analysis
│   │   ├── repositories/      # Supabase CRUD wrappers
│   │   ├── api/               # FastAPI routers (public + admin)
│   │   ├── schemas/           # Pydantic request/response models
│   │   ├── core/              # settings, auth, logging, supabase clients
│   │   └── ingestion/         # World Bank API client + variable mapping
│   ├── scripts/               # CLI tools (training, ingestion, diagnostics)
│   └── tests/                 # pytest suite (54 unit + 4 integration)
├── frontend/
│   └── src/
│       ├── features/          # one folder per UI area (auth, countries, admin)
│       ├── lib/               # API client + Supabase client
│       └── components/        # shared UI (AppShell)
├── supabase/
│   ├── migrations/            # 8 SQL migrations (tenancy → snapshots → model lifecycle)
│   └── seeds/                 # CSVs derived from the Excel prototype
└── docs/
    └── superpowers/
        ├── specs/             # design spec
        ├── plans/             # one implementation plan per milestone (tagged)
        └── training-engine.md # how the Python training code works
```

## Local setup

**Preconditions:**
- Python 3.11–3.12, Node 20+, Supabase CLI installed
- Two Supabase cloud projects: `country-risk-dev` (used now) and `country-risk-prod` (Plan 7 deployment)
- A populated `.env` at the repo root with the `dev` project's URL + anon key + service-role key + JWT secret
- A populated `frontend/.env` with the `VITE_*` mirror of the same dev project

**Bring it up:**

```bash
# 1) Apply migrations to your linked Supabase dev project
supabase link --project-ref=<your-dev-ref>
supabase db push --linked

# 2) Install backend deps + run tests
cd backend
python -m venv .venv
source .venv/Scripts/activate          # bash; PowerShell: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                                 # 54 unit tests pass

# 3) Install frontend deps + run tests
cd ../frontend
npm install
npm test                               # 4 tests pass

# 4) Boot both services (in separate terminals)
cd backend && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev             # serves http://localhost:5173
```

**Provision a model + a published snapshot (one-time, after migrations):**

```bash
# Train two segment models from the prototype's 2011 training data
cd backend
python scripts/train_baseline.py --quant gdp_capita,cof,debt_service_ratio --qual rol,pr

# Then either via the Admin UI (Models → Approve → Activate per segment) OR via SQL:
# UPDATE model_versions SET status = 'approved' WHERE id = '...';
# UPDATE model_versions SET status = 'active'   WHERE id = '...';

# Pull WB data
python scripts/ingest_world_bank.py 1960-2024

# Create + compute + publish the first snapshot
python scripts/run_snapshot.py create --name "2022-FY" --as-of 2022-12-31
python scripts/run_snapshot.py compute <snapshot-uuid>
python scripts/run_snapshot.py publish <snapshot-uuid> --notes "first publish"
```

## Documentation

- **Design spec:** [`docs/superpowers/specs/2026-04-19-country-risk-app-design.md`](docs/superpowers/specs/2026-04-19-country-risk-app-design.md)
- **Implementation plans (one per milestone):** [`docs/superpowers/plans/`](docs/superpowers/plans/)
- **How the training code works:** [`docs/training-engine.md`](docs/training-engine.md) ⭐
- **Memory / project notes:** see CLAUDE memory under `~/.claude/projects/...`

## Tagged milestones

```
plan-1-foundation         # repo + auth + reference data
plan-2-scoring-engine     # pure-Python Ridge engine + training
plan-3-ingestion          # World Bank API → raw_observations
plan-4-snapshot-lifecycle # draft → publish + immutability triggers
plan-5-public-api-ui      # /v1/* endpoints + country detail UI
plan-model-lifecycle      # model approval workflow + diagnostics CSV/Excel
```

## What's next (not yet built)

- **Plan 6** — Client features: watchlists, what-if simulator, in-app alerts
- **Plan 7** — Deployment: Render (backend) + Vercel (frontend) + production Supabase + CI/CD
- **Calibration** — Multi-year aggregate features, target-variable upload UI, model tuning to lift R²
- **EIU CSV upload** — Manual ingestion path for the qualitative variables not on World Bank
