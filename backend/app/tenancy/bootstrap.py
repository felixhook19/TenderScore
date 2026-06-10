"""Bootstrap CLI: provision a tenant with its first administrator.

Tenant provisioning is a platform operation with no public endpoint in v1.
Run inside the api container or a local environment with database access:

    uv run python -m app.tenancy.bootstrap \\
        --tenant-name "Sandford District Council" \\
        --admin-email admin@example.org \\
        --admin-name "A. Administrator"

The administrator password may be supplied with --admin-password or via the
TENDERSCORE_BOOTSTRAP_PASSWORD environment variable; otherwise a random one
is generated and printed once.
"""

import argparse
import os
import secrets
import sys

from app.audit.recorder import AuditRecorder
from app.auth.roles import Role
from app.auth.service import UserManagementError, create_user, grant_role
from app.core.db import get_session_factory
from app.tenancy.service import TenantProvisioningError, create_tenant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision a tenant and its first admin.")
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-name", required=True)
    parser.add_argument("--admin-password", default=None)
    args = parser.parse_args(argv)

    password: str | None = args.admin_password or os.environ.get(
        "TENDERSCORE_BOOTSTRAP_PASSWORD"
    )
    generated = password is None
    if password is None:
        password = secrets.token_urlsafe(18)

    session = get_session_factory()()
    try:
        recorder = AuditRecorder(session, tenant_id=None, actor_id=None, actor_type="system")
        tenant = create_tenant(session, recorder, args.tenant_name)
        admin = create_user(
            session,
            recorder,
            tenant_id=tenant.id,
            email=args.admin_email,
            display_name=args.admin_name,
            password=password,
        )
        grant_role(session, recorder, user=admin, role=Role.ADMIN)
        session.commit()
    except (TenantProvisioningError, UserManagementError) as error:
        session.rollback()
        print(f"Provisioning failed: {error}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print(f"Tenant provisioned: {tenant.name} (id {tenant.id}, schema {tenant.schema_name})")
    print(f"Administrator: {admin.email} (id {admin.id})")
    if generated:
        print(f"Generated password (shown once): {password}")
    print(f"TOTP secret (shown once): {admin.totp_secret}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
