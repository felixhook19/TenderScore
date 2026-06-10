# Milestone exit-criteria checklist

Tracks M0–M10 per `docs/architecture.md` Part I. A milestone is marked
done only when every exit criterion has passing evidence (tests or a
demonstrated run) and the founder has confirmed the stop-and-report.

## M0 — Scaffold ✓ (confirmed 2026-06-10)

- [x] `make dev` boots db, minio, api, worker, web
- [x] `make test` green (backend pytest, frontend vitest + axe-core)
- [x] Health endpoint returns
- [x] CI workflow present (runs on PR)
- [x] ADR-001 (stack) recorded

## M1 — Tenancy, auth, audit spine ✓ (awaiting confirmation)

- [x] Audit-completeness test passes (walks every mutating route, asserts
      events, fails on uncovered routes) — `test_audit_completeness.py`
- [x] UPDATE/DELETE on `audit_events` rejected at the database level
      (revoked privileges and trigger proven independently) —
      `test_audit_immutability.py`
- [x] Chain verifier detects a tampered chain (rewritten event and forged
      insertion) — `test_audit_chain.py`
- [x] Schema-per-tenant provisioning, audited — `test_tenancy.py`,
      bootstrap CLI
- [x] Dev IdentityProvider (email + password + TOTP) behind the interface
- [x] RBAC default-deny + distinct anonymisation-map privilege —
      `test_rbac.py`
- [x] `app/audit` coverage ≥ 85% (CI-enforced)

## M2 — Ingestion (not started)
## M3 — Framework service (not started)
## M4 — LLM gateway + prompt registry (not started)
## M5 — Scoring engine (not started)
## M6 — Compliance + anonymisation (not started)
## M7 — Moderation workflow + UI (not started)
## M8 — Document generation (not started)
## M9 — Red-team + regression hardening (not started)
## M10 — Pre-pilot hardening (not started)
