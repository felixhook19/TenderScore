# Runbook: backup and restore

**Scope:** development/pilot single-instance deployment (Docker Compose).
Cloud-managed equivalents replace this at P4 once the provider decision
lands.

## What must be backed up

| Asset | Where | Why |
|---|---|---|
| PostgreSQL (all schemas) | `db` service volume | All evaluation state and the append-only audit chain |
| Object storage bucket | `minio` volume / S3 bucket | Submission originals and generated packs (hash-verified against the DB) |
| Prompt artefacts | `backend/prompts/` (in git) | Already versioned; no separate backup needed |

## Backup

```sh
# Database: full logical dump, all schemas (platform + tenant_*)
docker compose exec db pg_dump -U tenderscore -d tenderscore -F c \
    -f /tmp/tenderscore.dump
docker compose cp db:/tmp/tenderscore.dump ./backups/tenderscore-$(date -u +%Y%m%dT%H%M%SZ).dump

# Object storage: mirror the bucket
docker compose exec minio mc mirror /data/tenderscore-dev /tmp/bucket-backup
```

Schedule: nightly at minimum; before every migration, always.

## Restore

```sh
docker compose exec -T db pg_restore -U tenderscore -d tenderscore --clean --if-exists /tmp/tenderscore.dump
```

## Verify after restore — non-negotiable

1. `uv run alembic current` shows the expected head.
2. **Verify every audit chain:** call `GET /audit/verify` per tenant (or run
   `verify_all` from a shell). A restore that breaks a chain must be
   escalated, not patched: the chain is the evidential record.
3. Spot-check a submission: fetch the original from object storage and
   compare its hash with `submissions.content_hash`.

## Notes

- `audit_events` is append-only with revoked UPDATE/DELETE; restores must
  use roles that respect this (the dump includes the trigger and grants).
- Never restore real data into a development environment (synthetic-only
  rule holds until the DPIA and legal gates pass).
