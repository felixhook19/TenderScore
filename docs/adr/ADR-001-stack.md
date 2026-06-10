# ADR-001: Stack and scaffold decisions

**Status:** Accepted
**Date:** 2026-06-10
**Phase:** P3 (M0)

## Context

M0 scaffolds the monorepo for the Evaluate tier per `docs/architecture.md`
Parts B and C. The stack is largely fixed by the handover; this ADR records
it as implemented, plus the scaffold-level choices M0 had to make. Two
infrastructure decisions are deliberately open (cloud provider — Open
Decision #4; SSO tenant) and must not be pre-empted.

## Decision

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (typed, declarative),
  Alembic, Pydantic v2 + pydantic-settings. Dependency and interpreter
  management with **uv** (lockfile `backend/uv.lock` committed; CI installs
  with `--frozen`). `ruff` (with bugbear, bandit, pyupgrade, isort rule
  sets) and `mypy --strict` over `app` and `tests`.
- **Frontend:** React 18 + TypeScript strict (including
  `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes`) + Vite 6.
  Tests with vitest + Testing Library; accessibility asserted with
  **axe-core directly** in jsdom (colour contrast excluded there as jsdom
  performs no layout — it is covered by browser-based checks from M7).
- **Data:** PostgreSQL 16 (schema-per-tenant from M1); MinIO as the
  S3-compatible store in dev `[[ASSUMED — provider open]]`; Postgres-backed
  job queue `[[ASSUMED — revisit at P4]]`.
- **LLM:** Anthropic API behind `llm_gateway` only (M4). No provider SDK is
  a dependency at M0 — it arrives with the gateway, never elsewhere.
- **Local infrastructure:** Docker Compose only (`db`, `minio`, `api`,
  `worker`, `web`). No Terraform, no cloud-provider configuration.
- **CI:** GitHub Actions — backend job (ruff, mypy --strict, pytest) and
  frontend job (tsc --noEmit, vitest including axe-core). The regression
  and red-team Make targets exist as loud-failing stubs and join CI as
  blocking gates when their suites land (M5/M2+).
- **Configuration:** environment variables with the `TENDERSCORE_` prefix
  via pydantic-settings; `.env` git-ignored; `.env.example` documents every
  variable with development-only defaults.

## Consequences

- A clone boots with `make dev` and verifies with `make test` / `make lint`
  — no machine-specific setup beyond Docker, uv and Node 22.
- uv pins the interpreter to 3.12 regardless of the system Python, keeping
  dev, CI and the container images identical.
- Storage, queue, identity and KMS remain behind interfaces/config so the
  open infrastructure decisions stay open.
- Module packages for M1–M8 exist as empty, documented packages; no
  business logic shipped at M0.

## Open decisions touched (handover Part 6 ref)

- Cloud provider (AWS vs Azure) — untouched; Compose is the only
  infrastructure.
- SSO tenant (Entra ID) — untouched; `IdentityProvider` interface arrives
  in M1 with a dev provider only.
- Pinned model version string and UK/EEA residency — not needed at M0; will
  be a clearly-labelled placeholder constant in one config location at M4.
