# `app/jobs`

Postgres-backed queue (FOR UPDATE SKIP LOCKED), handler registry, worker entrypoint with registry reconcile and audited job lifecycle.

Tests: see `tests/` (unit, integration, regression and red-team suites cover this module; the audit-completeness walk exercises its endpoints).
