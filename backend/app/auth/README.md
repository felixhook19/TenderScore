# `app/auth` — identity, RBAC and sessions

Development-grade identity provider (email + password + TOTP) behind the
`IdentityProvider` interface (`provider.py`). Entra ID SSO is the
production target and arrives at P4 behind the same seam — the tenant
decision is open and human-owned.

## Pieces

- **Roles** (`roles.py`): admin, procurement_lead, evaluator, moderator,
  observer_auditor. Route guards are default-deny (`require_roles`).
- **Privileges:** distinct grants, never implied by any role. The only one
  defined so far is `anonymisation_map.read` (used from M6; every read of
  the map will be individually audited).
- **Sessions:** opaque database-backed tokens (revocable, expiring);
  two-step lifecycle pending_totp -> active.
- **Endpoints:** `POST /auth/login`, `POST /auth/totp`, `GET /me`, plus
  admin-only user/role/privilege management under `/users` (tenant-scoped).
- **Auditing:** successes are recorded in the request transaction; failed
  attempts are recorded in their own committed transaction so the 401 does
  not roll them away.

## Tests

`tests/unit/test_passwords.py`, `tests/integration/test_auth_flow.py`,
`tests/integration/test_rbac.py` (including the default-deny route walk
and the distinct-privilege assertions).
