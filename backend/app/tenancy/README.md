# `app/tenancy` — tenant lifecycle

Schema-per-tenant isolation in PostgreSQL (CLAUDE.md rule 3). Provisioning
creates the tenant record and its dedicated `tenant_<slug>` schema, audited
as the first event of the tenant's own chain.

There is deliberately no public endpoint for provisioning in v1: it is a
platform operation performed with the bootstrap CLI:

```sh
uv run python -m app.tenancy.bootstrap \
    --tenant-name "Sandford District Council" \
    --admin-email admin@example.org \
    --admin-name "A. Administrator"
```

The CLI provisions the tenant, creates the first administrator, grants the
admin role, and prints the generated password (if not supplied) and the
TOTP secret exactly once.

Tenant-schema tables arrive with the modules that own them (submissions in
M2, procurements in M3); at M1 the schema is provisioned empty.

## Tests

`tests/unit/test_tenancy_naming.py`, `tests/integration/test_tenancy.py`,
`tests/integration/test_bootstrap.py`.
