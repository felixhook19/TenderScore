# ADR-003: Tenant-schema DDL and the scoring engine's seams

**Status:** Accepted
**Date:** 2026-06-10
**Phase:** P3 (M2–M8)

## Context

Schema-per-tenant isolation (CLAUDE.md rule 3) needs a migration story:
tenant tables exist once per tenant schema, and tenants are provisioned
continuously. Alembic has no first-class multi-schema support.

## Decision

1. **Tenant tables on a separate `TenantBase`** declared without a schema.
   At runtime, sessions translate unqualified names to the current tenant's
   schema via `schema_translate_map` (`tenant_session()` in `core/db.py`).
   Platform tables carry an explicit `platform` schema and are unaffected.
2. **Single-head invariant:** every tenant schema is always at the global
   alembic head. Migrations that change tenant tables loop over all
   existing tenant schemas inside the migration (see migration 0002);
   provisioning creates a new schema directly at head with
   `create_tenant_tables`. No per-schema version table is needed.
3. **The deterministic adapter seam** (`scoring/jobs.py: set_adapter`) and
   the object-storage override (`ingestion/storage.py: set_object_storage`)
   exist so the regression and red-team suites run the full pipeline with
   bit-identical outputs and no network. Production resolves the Anthropic
   adapter and S3 storage; nothing outside the gateway touches a provider
   SDK.
4. **Failed-pass protocol:** a pass failing deterministic validation is
   rejected and rerun once; a second failure is recorded and flagged
   (`scoring.pass_flagged`), never silently dropped.
5. **Gate sequencing:** gate-criterion runs are scheduled marginally ahead
   of other runs so a gate failure blocks the bidder's remaining queued
   runs (`scoring.run_blocked_gate`, audited). Runs that completed before
   the gate outcome stand and are visible to moderation alongside the gate
   failure.

## Consequences

- Adding a tenant-table migration means writing the per-schema loop by
  hand; the invariant keeps it mechanical.
- A downgrade drops tenant tables in every schema (reversible, with data
  loss as any down-migration implies).
- The single-head invariant must hold during deploys: run migrations
  before provisioning new tenants.

## Open decisions touched (handover Part 6 ref, if any)

None.
