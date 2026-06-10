# TenderScore backend

Python 3.12 · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2.
`ruff` and `mypy --strict` clean at all times.

## Layout

| Path | Purpose | Built in |
|---|---|---|
| `app/main.py` | FastAPI app factory + health endpoint | M0 ✓ |
| `app/core/` | Configuration, database engine/session | M0 ✓ |
| `app/audit/` | Event schema, middleware, hash chain, verifier | M1 ✓ |
| `app/auth/` | IdentityProvider interface, dev provider, RBAC | M1 ✓ |
| `app/tenancy/` | Tenant lifecycle, schema provisioning, bootstrap CLI | M1 ✓ |
| `app/ingestion/` | Upload, parse (PDF/DOCX), split, hash, injection scan | M2 ✓ |
| `app/framework/` | Procurements, lots, criteria tree, descriptors, lock | M3 ✓ |
| `app/llm_gateway/` | Provider abstraction, prompt registry, taint check | M4 ✓ |
| `app/scoring/` | Orchestrator, passes, citation validator, variance | M5 ✓ |
| `app/compliance/` | Limits, gates, caveats, attachment checks | M6 ✓ |
| `app/anonymisation/` | Rules + gazetteer, token mapping, privileged access | M6 ✓ |
| `app/moderation/` | Tiering, confirm/amend workflow | M7 ✓ |
| `app/documents/` | Pack generation (docx/pdf) from the record | M8 ✓ |
| `app/jobs/` | Postgres-backed queue, worker entrypoint | M2 ✓ |
| `prompts/` | Versioned, hashed YAML prompt artefacts | M4 ✓ |
| `alembic/` | Reversible migrations | M1+ ✓ |

## Running locally

From the repository root: `make dev` (Docker Compose) or, natively:

```sh
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Tests and checks: `uv run pytest`, `uv run ruff check .`, `uv run mypy`.
