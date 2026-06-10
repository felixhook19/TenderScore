# ADR-002: Audit chain design and database access style

**Status:** Accepted
**Date:** 2026-06-10
**Phase:** P3 (M1)

## Context

CLAUDE.md rule 1 requires an append-only, hash-chained audit store enforced
at the database level, with no state change anywhere in the system that
does not emit an `AuditEvent`. The architecture (Part D) fixes the schema;
several design points were left to the implementation.

## Decision

1. **Chain scoping: one chain per tenant, plus one platform chain** for
   events with no tenant (e.g. failed logins against unknown accounts).
   Rationale: tenant isolation extends to the audit trail — a tenant's
   chain can be exported and verified standalone, and chains never
   interleave across tenants. The alternative (a single global chain) would
   make every tenant's verification depend on every other tenant's events.
2. **Canonical form:** `event_hash = sha256(prev_event_hash ||
   canonical_json(fields))`, where canonical JSON is sorted-key, no
   whitespace, ISO-8601 timestamps, stringified UUIDs, and includes a
   `chain_version` constant so the serialisation can evolve detectably.
   Genesis is sixty-four zeros.
3. **Concurrency:** chain extension takes a transaction-scoped PostgreSQL
   advisory lock derived from the chain key, then reads the chain head.
   Concurrent writers to one chain serialise; different chains do not
   contend.
4. **Immutability, two database layers:** UPDATE/DELETE/TRUNCATE revoked
   from PUBLIC and from the application role, and a BEFORE trigger that
   raises on every UPDATE/DELETE/TRUNCATE — so even the table owner cannot
   mutate history without disabling the trigger, which verification then
   exposes. Tests prove both layers independently.
5. **Completeness, three application layers:** (a) the request-session
   dependency rolls back any mutating request reaching commit with zero
   events; (b) middleware refuses to report success for any mutating
   request that emitted none; (c) the CI audit-completeness test walks
   every mutating route and fails on uncovered routes.
6. **Failed-attempt events** (wrong password, wrong TOTP code) are written
   in their own committed transaction, because the failing request's
   transaction rolls back by design.
7. **Synchronous SQLAlchemy** sessions throughout the backend. FastAPI
   runs sync handlers in its threadpool; the audit advisory-lock protocol
   and transactional semantics stay easy to reason about, which matters
   more here than async throughput. LLM calls (M4+) happen in worker jobs,
   not request handlers, so request-path async buys little. Revisit at P4
   under load testing if needed.

## Consequences

- A scoring run's full history will verify from genesis per tenant (M5
  replay builds on this).
- Adding any mutating endpoint without audit events fails in three places
  before it can reach a customer.
- The platform chain serialises platform-level events globally; volume
  there is tiny (provisioning, unknown-account failures).
- Tamper detection is evidential, not preventive, against a database
  superuser — that boundary is operational (managed Postgres, restricted
  roles) and is documented for the M10 hardening pass.

## Open decisions touched (handover Part 6 ref, if any)

None.
