"""Integration test fixtures: a real PostgreSQL database, migrated to head.

These tests are part of the M1 exit criteria and must run against a real
database (the append-only enforcement lives in PostgreSQL itself). They
fail — never skip — if the database is unreachable: run `make dev` or
`docker compose up -d db` first.
"""

import os
import uuid
from collections.abc import Iterator

import pyotp
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.audit.recorder import AuditRecorder
from app.auth.models import User
from app.auth.roles import Role
from app.auth.service import create_user, grant_role
from app.core.config import get_settings
from app.core.db import get_session_factory, reset_engine
from app.tenancy.models import Tenant
from app.tenancy.service import create_tenant

TEST_DATABASE = "tenderscore_test"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Create a dedicated test database and migrate it to head."""
    base_url = make_url(get_settings().database_url)
    admin_engine = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.execute(
                text(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")
            )
            connection.execute(text(f"CREATE DATABASE {TEST_DATABASE}"))
    except Exception as error:
        pytest.fail(
            "Integration tests need PostgreSQL (run `docker compose up -d db`). "
            f"Could not prepare the test database: {error}"
        )
    finally:
        admin_engine.dispose()

    test_url = base_url.set(database=TEST_DATABASE)
    os.environ["TENDERSCORE_DATABASE_URL"] = test_url.render_as_string(hide_password=False)
    os.environ["TENDERSCORE_BCRYPT_ROUNDS"] = "4"  # dev-grade speed for tests only
    get_settings.cache_clear()
    reset_engine()

    command.upgrade(Config("alembic.ini"), "head")
    yield
    reset_engine()


@pytest.fixture
def db_session() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def make_tenant_with_admin() -> Iterator[
    "TenantFactory"
]:
    factory = TenantFactory()
    yield factory
    factory.close()


ADMIN_PASSWORD = "a-dev-test-password-1234"


class ProvisionedTenant:
    def __init__(self, tenant: Tenant, admin: User) -> None:
        self.tenant = tenant
        self.admin = admin
        self.admin_password = ADMIN_PASSWORD


class TenantFactory:
    """Provisions uniquely named tenants with an admin user, audited."""

    def __init__(self) -> None:
        self._session = get_session_factory()()

    def __call__(self) -> ProvisionedTenant:
        recorder = AuditRecorder(
            self._session, tenant_id=None, actor_id=None, actor_type="system"
        )
        suffix = uuid.uuid4().hex[:12]
        tenant = create_tenant(self._session, recorder, f"Test Council {suffix}")
        admin = create_user(
            self._session,
            recorder,
            tenant_id=tenant.id,
            email=f"admin-{suffix}@example.org",
            display_name="Test Administrator",
            password=ADMIN_PASSWORD,
        )
        grant_role(self._session, recorder, user=admin, role=Role.ADMIN)
        self._session.commit()
        return ProvisionedTenant(tenant, admin)

    def close(self) -> None:
        self._session.close()


def login(client: TestClient, user: User, password: str) -> str:
    """Complete the full two-factor flow and return a session token."""
    response = client.post(
        "/auth/login", json={"email": user.email, "password": password}
    )
    assert response.status_code == 200, response.text
    challenge_token = response.json()["challenge_token"]

    code = pyotp.TOTP(user.totp_secret).now()
    response = client.post(
        "/auth/totp", json={"challenge_token": challenge_token, "code": code}
    )
    assert response.status_code == 200, response.text
    token = response.json()["session_token"]
    assert isinstance(token, str)
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
