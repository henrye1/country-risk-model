# Country Risk Model — Application Design

**Status:** Draft for approval
**Date:** 2026-04-19
**Owner:** Henry (Anchor Point Risk)
**Prototype source:** `prototype/Country Prototype Original HDI with Ridge.xlsx`

---

## 1. Purpose and scope

Convert the existing Excel country-risk prototype into a production web application that:

1. Produces **published, versioned country risk scores** that feed Anchor Point Risk's global **PD (Probability of Default)** and **LGD (Loss Given Default)** rating models via a stable REST API.
2. Lets a small **internal analyst team** upload data, compute draft scores, review them, and publish.
3. Lets **external client organisations** explore published scores, maintain watchlists, receive in-app alerts when scores change, and run personal "what-if" simulations that never affect published results.

The Excel Ridge-regression logic is **re-implemented in Python** (scikit-learn) rather than ported cell-for-cell. The technical owner retrains offline; analysts do not retrain through the UI.

### 1.1 In scope for v1
- Ingest raw driver data (manual upload for licensed EIU; API ingestion for World Bank and Worldwide Governance Indicators).
- Store full append-only history of raw observations.
- Offline model training (endpoint exists but only `internal_owner` can call it).
- Draft → review → publish lifecycle with permanent audit history.
- Public read API with per-country, per-date, per-snapshot score retrieval.
- Client features: watchlists, in-app notifications (3 triggers), what-if simulator.
- Supabase-managed auth (email/password + optional TOTP MFA); RLS on all tenant-scoped tables.

### 1.2 Explicitly out of scope for v1
- PDF/Excel export of scores (deferred).
- Email alerts (in-app only for v1).
- Client self-service billing / subscriptions (clients are provisioned by internal admins).
- Forced MFA for client users (opt-in only; internal users must enable).
- Retrain UI beyond the single `internal_owner` endpoint.

---

## 2. Users, roles, and permissions

Four roles, all recorded on `memberships.role`. Every user belongs to exactly one organisation.

| Role | Org type | Capabilities |
|---|---|---|
| `internal_owner` | internal | Everything, incl. model training and score publishing |
| `internal_analyst` | internal | Upload data, run API ingestion, compute/preview draft snapshots, view everything. Cannot train or publish. |
| `client_admin` | client | Manage own org's watchlists, alert preferences, invite colleagues |
| `client_user` | client | Use watchlists, run simulations, read published scores |
| `service_reader` | system | Read-only consumer of `/v1/*` endpoints — used by PD/LGD pipeline |

### 2.1 Permissions matrix (summary)
| Capability | owner | analyst | client_admin | client_user | service_reader |
|---|:-:|:-:|:-:|:-:|:-:|
| Read published scores (any country) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Read draft scores | ✅ | ✅ | ❌ | ❌ | ❌ |
| Upload / ingest raw data | ✅ | ✅ | ❌ | ❌ | ❌ |
| Create / compute draft snapshot | ✅ | ✅ | ❌ | ❌ | ❌ |
| Publish snapshot | ✅ | ❌ | ❌ | ❌ | ❌ |
| Train model version | ✅ | ❌ | ❌ | ❌ | ❌ |
| Manage own org's watchlists / alerts | n/a | n/a | ✅ | read-only | ❌ |
| Run /simulate | ✅ | ✅ | ✅ | ✅ | ❌ |
| Invite colleagues to org | ✅ (internal) | ❌ | ✅ (client) | ❌ | ❌ |

---

## 3. Architecture

**Approach 1 — simple monolith, chosen during brainstorming:**
- One FastAPI service exposes all three API surfaces (public, client, admin).
- One React SPA covers all user-facing UI; routes and features are role-gated.
- Retraining is a synchronous job inside FastAPI (Ridge on ~161 rows — finishes in seconds).
- Supabase provides Postgres, Auth, Storage, RLS.
- Deployed: FastAPI on Render (Docker), React on Vercel, Supabase hosted.

No background worker, no queue in v1. If training time or ingestion volume grow, add Celery/RQ later (Approach 2 in the brainstorm).

### 3.1 Repository layout
```
country-risk-model/
├── prototype/                          # archive original xlsx as source of truth for regression tests
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI entry + CORS + routers
│   │   ├── api/
│   │   │   ├── public.py               # /v1/...   — PD/LGD consumers + read path
│   │   │   ├── admin.py                # /admin/...— internal only
│   │   │   ├── client.py               # /client/..— client-scoped
│   │   │   └── health.py
│   │   ├── core/                       # settings, supabase client, auth deps, logging
│   │   ├── domain/                     # pure Python — no FastAPI, no DB drivers
│   │   │   ├── scoring.py
│   │   │   ├── segmentation.py
│   │   │   ├── standardisation.py
│   │   │   └── training.py
│   │   ├── repositories/               # Supabase access (swappable in tests)
│   │   ├── services/                   # orchestrate domain + repos
│   │   ├── ingestion/
│   │   │   ├── csv_loader.py
│   │   │   ├── world_bank.py
│   │   │   └── wgi.py
│   │   └── schemas/                    # Pydantic request/response models
│   ├── tests/
│   ├── migrations/                     # reviewable SQL migrations in git
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── api/                        # typed client, JWT fetcher
│   │   ├── features/
│   │   │   ├── countries/
│   │   │   ├── watchlist/
│   │   │   ├── simulate/
│   │   │   ├── admin/
│   │   │   └── auth/
│   │   ├── components/                 # shared UI (shadcn/ui primitives)
│   │   ├── lib/
│   │   └── routes.tsx
│   ├── tests/
│   └── package.json
├── docs/
│   └── superpowers/specs/              # this doc
├── .env.example
└── README.md
```

### 3.2 Design principles
- **Domain logic is framework-free.** `domain/*` has no FastAPI, no Supabase imports. Auditors can read it in isolation.
- **Repositories wrap Supabase.** Tests can swap them for in-memory fakes.
- **Single scoring pipeline.** Both snapshot computation and `/simulate` call the same `domain/scoring.py` — no second implementation to drift.
- **Small, well-bounded files.** When a file grows past ~300 lines that is a signal to split by responsibility.

---

## 4. Data model (Supabase / Postgres)

All tables have `id uuid primary key default gen_random_uuid()` unless noted, plus `created_at timestamptz default now()`. RLS is enabled on every table.

### 4.1 Identity and tenancy
- **`organisations`**: `id`, `name`, `status` (`internal` | `client` | `system`), `created_at`.
- **`memberships`**: `user_id` (FK `auth.users`), `organisation_id`, `role` (`internal_owner` | `internal_analyst` | `client_admin` | `client_user` | `service_reader`). One user has exactly one membership in v1.

### 4.2 Reference data
- **`countries`**: `iso3` PK, `name`, `region`.
- **`country_segments`**: `iso3`, `as_of_year`, `hdi_value`, `segment` (`HIGH` | `LOW` | `NODATA`). PK `(iso3, as_of_year)`. Captures that HDI-based segmentation can move a country between groups over years.
- **`variables`**: `code` PK (e.g. `dcpi_5_adj`), `name`, `category` (`Economic` | `Currency` | `Political` | `Business Risk` | `Risk` | `Finance`), `direction` (`higher_better` | `higher_worse`), `is_quantitative` boolean, `description`.

### 4.3 Raw inputs (append-only)
- **`data_uploads`**: `id`, `uploaded_by`, `source` (`EIU` | `WB` | `WGI` | `OTHER`), `file_name`, `row_count`, `notes`, `uploaded_at`. `EIU` is the expected manual-upload source; `OTHER` is the catch-all for any future manual source not yet formalised.
- **`raw_observations`**: `id`, `iso3`, `variable_code`, `year`, `value numeric`, `source` (same enum as above), `upload_id` (nullable FK — populated when source originated from a manual upload), `ingested_at`, `ingested_by`. **Append-only** — corrections add new rows with later `ingested_at`; nothing is ever UPDATEd.

Query for "latest known value of variable V for country C in year Y" = row with max `ingested_at` matching `(iso3, variable_code, year)`.

### 4.4 Model versions (frozen after training)
- **`model_versions`**: `id`, `segment` (`HIGH` | `LOW` | `NODATA`), `trained_at`, `trained_by`, `training_notes`, `training_data_hash` (sha256 of ordered tuple of `raw_observations.id`s used), `fit_metrics_json` (R², MAE, etc.), `status` (`active` | `retired`).
- **`model_coefficients`**: `model_version_id`, `variable_code` (nullable for intercept row), `coefficient numeric`, `is_intercept` boolean.
- **`model_standardisation`**: `model_version_id`, `variable_code`, `mean numeric`, `std numeric`.
- **`model_buckets`**: `model_version_id`, `variable_code`, `bucket_order int`, `lower_bound numeric`, `upper_bound numeric`, `score numeric`.

The `NODATA` segment uses a flat rule set: stored as a `model_version` with `segment='NODATA'` whose coefficients represent the fallback score mapping.

### 4.5 Scores (the audit-critical tables)
- **`score_snapshots`**: `id`, `name` (e.g. `"2025-Q4"`), `as_of_date date`, `status` (`draft` | `published` | `archived`), `model_version_high`, `model_version_low`, `model_version_nodata` (FKs to `model_versions`), `created_by`, `created_at`, `published_by` (nullable), `published_at` (nullable), `published_notes`.
- **`country_scores`**: `snapshot_id`, `iso3`, `segment`, `final_score numeric`, `quant_score numeric`, `qual_score numeric`, `bucket_band text`. PK `(snapshot_id, iso3)`.
- **`driver_scores`**: `snapshot_id`, `iso3`, `variable_code`, `raw_value numeric`, `standardised_value numeric`, `bucket_score numeric`, `contribution numeric`. PK `(snapshot_id, iso3, variable_code)`.

### 4.6 Client features
- **`watchlists`**: `id`, `organisation_id`, `name`, `created_by`.
- **`watchlist_countries`**: `watchlist_id`, `iso3`. PK `(watchlist_id, iso3)`.
- **`alert_preferences`**: `organisation_id` PK, `threshold_points numeric` (default 5), `on_new_publish boolean`, `on_threshold_move boolean`, `on_bucket_change boolean`.
- **`notifications`**: `id`, `organisation_id`, `user_id` (nullable — NULL = broadcast to whole org), `snapshot_id`, `iso3` (nullable), `type` (`new_publish` | `threshold_move` | `bucket_change`), `message`, `read_at` (nullable).
- **`simulation_runs`**: `id`, `user_id`, `iso3`, `inputs_json jsonb`, `result_json jsonb`, `created_at`. Visible only within owner's org.

### 4.7 Audit
- **`audit_log`**: `id`, `actor_user_id`, `action`, `entity_type`, `entity_id`, `before_json jsonb`, `after_json jsonb`, `at timestamptz default now()`. Written by DB triggers on sensitive tables (`score_snapshots`, `model_versions`, `data_uploads`, `memberships`).

### 4.8 Immutability and transition guards
Two Postgres triggers, each defined in a migration and reviewable in git:

1. On `country_scores` and `driver_scores`: reject `UPDATE` and `DELETE` when the parent `score_snapshots.status = 'published'`.
2. On `score_snapshots`: reject any `status` transition other than `draft → published` and `published → archived`.

These are the regulatory-grade guarantees — they do not depend on application-level correctness.

### 4.9 RLS policy summary
Written per-table in migrations. Shape:
- `countries`, `variables`, `country_segments`: SELECT for any authenticated user.
- `raw_observations`, `data_uploads`, `model_*`, `audit_log`: ALL operations require internal-org membership.
- `score_snapshots`, `country_scores`, `driver_scores`: SELECT allowed for anyone when `status = 'published'`; only internal-org members see drafts. No DELETE. INSERT/UPDATE only via service-role (backend-only path).
- `watchlists`, `watchlist_countries`, `notifications`, `alert_preferences`, `simulation_runs`: ALL operations scoped to `memberships.organisation_id = row.organisation_id`.

---

## 5. API surface

All endpoints under `/v1` are stable; breaking changes require a new major version. Error envelope: `{ "error": { "code": "STRING", "message": "...", "details": {...} } }`. JWT required on all routes except `/v1/health`.

### 5.1 Public API (for PD/LGD consumers and authenticated clients)
```
GET  /v1/health
GET  /v1/countries                                     # list + latest-published summary
GET  /v1/countries/{iso3}                              # detail
GET  /v1/countries/{iso3}/score                        # latest published score
GET  /v1/countries/{iso3}/score?as_of=YYYY-MM-DD       # returns the score from the published snapshot with the greatest published_at <= given date
GET  /v1/countries/{iso3}/score?snapshot_id=uuid       # exact snapshot
GET  /v1/countries/{iso3}/history                      # all published scores for this country
GET  /v1/snapshots                                     # list published
GET  /v1/snapshots/{id}
GET  /v1/snapshots/{id}/scores                         # JSON or CSV (Accept header)
GET  /v1/variables                                     # driver catalogue
```
Every `/score` response body includes `snapshot_id`, `model_version_id` (per segment), `as_of_date`, `published_at`.

### 5.2 Client API
```
GET    /client/watchlists
POST   /client/watchlists
GET    /client/watchlists/{id}
PATCH  /client/watchlists/{id}
DELETE /client/watchlists/{id}
POST   /client/watchlists/{id}/countries               # {iso3}
DELETE /client/watchlists/{id}/countries/{iso3}

GET    /client/alerts/preferences
PUT    /client/alerts/preferences

GET    /client/notifications?unread=true&page=...
POST   /client/notifications/{id}/mark-read
POST   /client/notifications/mark-all-read

POST   /client/simulate                                # {iso3, overrides}
GET    /client/simulations                             # my history
```

### 5.3 Admin API
```
POST   /admin/uploads                                  # multipart CSV/XLSX
GET    /admin/uploads
GET    /admin/uploads/{id}/preview
POST   /admin/uploads/{id}/commit

POST   /admin/ingest/world-bank                        # {variables, years}
POST   /admin/ingest/wgi

GET    /admin/model-versions
POST   /admin/model-versions/train                     # owner-only
POST   /admin/model-versions/{id}/activate             # owner-only

GET    /admin/snapshots                                # list incl. drafts
POST   /admin/snapshots                                # create draft
POST   /admin/snapshots/{id}/compute
GET    /admin/snapshots/{id}/diff                      # vs previous published
POST   /admin/snapshots/{id}/publish                   # owner-only; Idempotency-Key header required
POST   /admin/snapshots/{id}/archive
```

### 5.4 Cross-cutting
- **Versioning:** only `/v1` is external; `/admin` and `/client` are internal to the app and may change without notice.
- **Idempotency:** `publish` and `compute` accept `Idempotency-Key`; repeated calls with the same key within 24h return the original result.
- **Rate limits:** per-user limit on `/client/simulate` (target: 60 req/min per user).
- **Observability:** request-ID middleware, structured JSON logs, Sentry for errors, `audit_log` writes for every admin action via DB trigger.

---

## 6. Data flows

### 6.1 Manual data ingest (EIU)
1. Analyst uploads CSV/XLSX → `POST /admin/uploads`.
2. Backend parses, validates (expected columns, ISO3/variable code matching, numeric values), returns preview.
3. Analyst reviews preview → `POST /admin/uploads/{id}/commit`.
4. Rows inserted into `raw_observations` in a single transaction with `source='EIU'` and `upload_id` back-reference.

### 6.2 API ingest (World Bank / WGI)
1. Analyst chooses variables + year range in UI.
2. `POST /admin/ingest/world-bank` (or `/wgi`) — synchronous call to public API.
3. Same validation + append to `raw_observations` with the appropriate `source`.

### 6.3 Training (owner only)
1. Owner calls `POST /admin/model-versions/train` with `{segment, training_year_range, notes}`.
2. Service pulls raw observations in scope, joins with historical ratings, filters to segment.
3. `domain/training.py` computes standardisation params, buckets quant drivers, fits `sklearn.linear_model.Ridge` on qualitative drivers, returns a `TrainedModel`.
4. Repository writes `model_versions` + coefficients + standardisation + buckets in a single transaction. `training_data_hash` stamped.
5. Response returns `model_version_id` and fit metrics.

### 6.4 Snapshot compute (draft)
1. Analyst creates draft via `POST /admin/snapshots` with `{name, as_of_date, model_version_ids}` (defaults to active per segment).
2. `POST /admin/snapshots/{id}/compute`:
   - For each country: resolve segment from `country_segments` as of `as_of_date`.
   - Pull latest `raw_observations` per variable as of `as_of_date`.
   - Apply matching model version via `domain/scoring.py`.
   - Write `country_scores` + `driver_scores` rows (draft).
3. Recompute wipes and rewrites draft rows within a transaction. Permitted only while status = draft.

### 6.5 Publish (audit gate)
1. Owner reviews draft + `GET /admin/snapshots/{id}/diff`.
2. `POST /admin/snapshots/{id}/publish` with Idempotency-Key.
3. Single transaction: flip status to `published`, stamp `published_by`/`published_at`. Immutability trigger activates.
4. Post-commit fan-out walks every org's watchlists. For each watched country, it evaluates alert preferences against the diff vs the previous published snapshot and inserts one `notifications` row per `(organisation_id, iso3, type)` combination that fired (so an org sees at most one notification per country per trigger type per publish, not one per user in the org).
5. Public API returns new snapshot as "latest".

### 6.6 What-if (simulate)
1. Frontend pre-fills raw values by calling `GET /v1/countries/{iso3}/score`.
2. User tweaks a driver → debounced (400ms) `POST /client/simulate`.
3. Backend fetches latest published snapshot's model versions, runs `domain/scoring.py` with overrides, returns score + breakdown.
4. `simulation_runs` row persisted. No score table touched.

### 6.7 PD/LGD consumer read path
1. Service authenticates with `service_reader` JWT.
2. Calls `GET /v1/countries/{iso3}/score` (optionally with `as_of` or `snapshot_id`).
3. Response embeds `snapshot_id`, `model_version_id`, `published_at`, `as_of_date` — consumer logs these alongside its own output.

---

## 7. Frontend structure

### 7.1 Stack
- Vite + React + TypeScript
- TanStack Query (server state, cache invalidation on publish)
- Supabase JS client (auth only — no direct PostgREST reads)
- React Router
- Tailwind + shadcn/ui primitives
- Recharts (driver breakdowns, history lines)
- Zod (API response validation)
- Vitest + React Testing Library + one Playwright smoke

### 7.2 Role-gated routes
| Route | Audience | Content |
|---|---|---|
| `/login` | public | Supabase auth UI |
| `/` | all | Role-aware landing (internal → admin dashboard; client → watchlist summary) |
| `/countries` | all | Country search table with latest score + band |
| `/countries/:iso3` | all | Detail: headline, driver breakdown chart, history chart, snapshot picker, drill-down table, "Simulate" button |
| `/simulate/:iso3` | client roles | What-if sandbox |
| `/watchlists` | client roles | List |
| `/watchlists/:id` | client roles | Detail with score deltas + recent alerts |
| `/notifications` | client roles | Inbox |
| `/settings` | client roles | Alert preferences |
| `/admin` | internal | Quick-access dashboard |
| `/admin/uploads` | internal | Upload → preview → commit |
| `/admin/ingest` | internal | API ingestion |
| `/admin/snapshots` | internal | List + new draft |
| `/admin/snapshots/:id` | internal | Draft review + Publish (owner-only, confirmation checklist) |
| `/admin/model-versions` | `internal_owner` | Train & activate |

### 7.3 Cross-cutting
- `api/` layer: one typed function per endpoint; shared `fetcher` injects JWT, normalises errors, validates with Zod.
- Role guards: `<RequireRole role="internal_owner" />` wrappers, centralised in `routes.tsx`.
- Optimistic UI for low-risk actions only (mark-read, toggle watchlist membership). Never for publish.
- Per-feature skeleton/empty/error components — no naked spinners.
- Env: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE_URL`.

---

## 8. Authentication and secrets

- Supabase Auth (email+password; optional TOTP MFA; **required** for internal users).
- JWT verified by FastAPI against Supabase JWKS; dependency enriches request with `{user_id, organisation_id, role}`.
- Service account for PD/LGD lives in the `system` organisation with role `service_reader`; long-lived JWT stored in the consumer's secret manager and rotated manually.
- Backend env: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (backend only — triggers and fan-out), `SUPABASE_JWT_SECRET`, `WORLD_BANK_API_BASE`, `WGI_API_BASE`, `SENTRY_DSN`.
- Service-role key never reaches the frontend. Frontend uses only the anon key.

---

## 9. Testing strategy

- **Domain unit tests** (`backend/tests/domain/`): pure-Python, fastest. Include a **regression suite vs the Excel prototype** — for ≥10 sample countries spanning all segments, assert Python scores match spreadsheet output within tolerance. This is the key trust artefact.
- **Repository integration tests**: against a local Supabase (Docker) with migrations applied.
- **API tests** (FastAPI TestClient + seeded DB): cover auth, RLS, draft→publish lifecycle, immutability trigger rejections, idempotency, simulate-doesn't-mutate.
- **Frontend tests** (Vitest + RTL): component logic, simulate debounce, admin publish modal flow.
- **End-to-end smoke** (Playwright): single golden path per role.
- CI (GitHub Actions) runs lint + unit + integration + e2e on every PR.

---

## 10. Deployment and operations

| Component | Host | Notes |
|---|---|---|
| Postgres + Auth + Storage | Supabase cloud | Auto-backups; PITR enabled |
| FastAPI backend | Render (Docker) | Blue/green; env-scoped; single instance sufficient |
| React SPA | Vercel | Static hosting with atomic deploys |
| Migrations | Supabase CLI in GitHub Actions | `supabase db push` to target project on merge to `main` |
| Error tracking | Sentry | Frontend + backend |
| Logs | Render log drain | Structured JSON |

Environments: `local` (docker-compose brings up local Supabase) → `staging` → `production`. Promotion is merge-driven.

---

## 11. Open decisions (deferred, not blocking)
1. **Production domain / SSL:** e.g. `countryrisk.anchorpointrisk.co.za` — pick before launch.
2. **PDF/Excel export** — confirm whether clients need it in v1.1.
3. **Email alerts** — defer until after v1 adoption.
4. **Client self-service billing** — deferred; internal provisioning in v1.
5. **Background worker** (Celery/RQ + Redis) — add only if training time or ingestion volume justify it.

---

## 12. Summary

A small, auditable, single-deployable stack that matches the user's chosen technologies (FastAPI, React, Supabase), preserves the regulatory requirements of the downstream PD/LGD consumers (versioned model + immutable published snapshots + stable REST API), and keeps the client-facing features (watchlists, in-app alerts, what-if sandbox) isolated from the audit path. The Excel prototype remains in the repo as the regression-test source of truth during the Python port.
