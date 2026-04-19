# Country Risk Model

Web application that converts Anchor Point Risk's Excel country-risk prototype into a versioned, auditable scoring system. Scores feed the firm's PD and LGD rating models via a REST API.

See `docs/superpowers/specs/2026-04-19-country-risk-app-design.md` for the design.
See `docs/superpowers/plans/` for implementation plans.

## Stack
- Backend: FastAPI + Python 3.11+
- Frontend: React + Vite + TypeScript
- Database / Auth: Supabase (Postgres + RLS)

## Local setup
1. Install Python 3.11+, Node 20+, and Supabase CLI.
2. Create two Supabase cloud projects (`country-risk-dev`, `country-risk-prod`).
3. Copy `.env.example` to `.env` and fill in the `dev` project's values.
4. `cd backend && pip install -e ".[dev]" && pytest`
5. `cd frontend && npm install && npm test`
6. `supabase link --project-ref=<dev-ref>` then `supabase db push` to apply migrations to the dev project.

## Structure
- `prototype/` — original Excel file (regression-test source of truth)
- `backend/` — FastAPI service
- `frontend/` — React SPA
- `supabase/migrations/` — SQL migrations, one file per logical change
- `docs/superpowers/` — specs and implementation plans
