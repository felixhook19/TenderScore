# `app/audit` — the audit spine

The audit trail is the product (CLAUDE.md rule 1). This module owns the
append-only, hash-chained audit store and its enforcement.

## Design (ADR-002)

- **Storage:** `platform.audit_events`, append-only. Immutability is
  enforced in the database, not by convention: UPDATE/DELETE/TRUNCATE are
  revoked from the application role *and* a trigger raises on any attempt,
  so even the table owner cannot rewrite history without first disabling
  the trigger — which chain verification then exposes.
- **Chains:** one hash chain per tenant, plus one platform chain for events
  with no tenant. `event_hash = sha256(prev_event_hash ||
  canonical_json(fields))` from a genesis constant. Chain extension is
  serialised with a transaction-scoped advisory lock per chain.
- **Recorder** (`recorder.py`): the only writer. Joins the caller's
  transaction, so state changes and their events commit or roll back
  together.
- **Verifier** (`verifier.py`): re-walks any chain from genesis and reports
  the first divergence. Exposed at `GET /audit/verify`.
- **Enforcement, three layers:**
  1. the database session dependency rolls back any mutating request that
     reaches commit with zero audit events (preventive);
  2. `AuditCompletenessMiddleware` refuses to report success for any
     mutating request that emitted none (backstop);
  3. the audit-completeness test in CI walks every mutating route and
     fails if one is not covered (regression guard).

## Endpoints

- `GET /audit/events` — tenant-scoped listing (admin or observer/auditor).
- `GET /audit/verify` — chain verification report for the caller's tenant.

## Tests

Unit: `tests/unit/test_hashing.py`. Integration:
`test_audit_immutability.py` (DB-level rejection), `test_audit_chain.py`
(tamper detection), `test_audit_completeness.py` (route walk + enforcement
layers), `test_audit_api.py`. Coverage floor 85% (CI-enforced); currently
above it.
