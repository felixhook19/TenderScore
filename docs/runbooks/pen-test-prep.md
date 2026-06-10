# Pen-test preparation checklist (pre-pilot)

Status key: [x] in place · [ ] outstanding (human-owned or P4)

## Scope for the tester

- API: FastAPI service (`backend/`), all routes in the OpenAPI schema.
- Web: React SPA (`frontend/`).
- Out of scope: the LLM provider itself; Docker host hardening (P4 infra).

## Pre-engagement state

- [x] Default-deny authentication on every route (CI-enforced walk).
- [x] RBAC + distinct anonymisation-map privilege, individually audited.
- [x] Rate limiting on authentication endpoints; account lockout after
      repeated failures; revocable database-backed sessions; logout.
- [x] Append-only, hash-chained audit store enforced in the database.
- [x] Instruction/content separation with in-gateway taint refusal.
- [x] Injection corpus (54 variants) green in CI; scanner layers documented.
- [x] Log scrubbing for tokens and email addresses.
- [x] Lockfiles committed; `pip-audit`/`npm audit` advisable per release.
- [ ] TLS termination and HSTS (deploy-time, P4).
- [ ] Entra ID SSO (P4; dev provider is email+password+TOTP).
- [ ] Cloud KMS envelope encryption (provider decision open).

## Areas to direct attention

1. Tenant isolation: cross-tenant access attempts via IDs in URLs.
2. The audit chain: attempt unaudited state change in any flow.
3. Prompt injection: bidder-content paths into the instruction layer.
4. Session fixation/replay around the two-step TOTP flow.
5. File upload handling (PDF/DOCX parsing) — malformed and oversized files.

## Artefacts to hand the tester

- OpenAPI schema (`/openapi.json`), this checklist, ASVS self-assessment,
  a synthetic-data tenant with all four bidder profiles loaded.
