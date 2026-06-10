"""Integration test fixtures: a real PostgreSQL database, migrated to head.

These tests are part of the M1 exit criteria and must run against a real
database (the append-only enforcement lives in PostgreSQL itself). They
fail — never skip — if the database is unreachable: run `make dev` or
`docker compose up -d db` first.
"""

import os
import uuid
from collections.abc import Callable, Iterator

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


@pytest.fixture(scope="session")
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
def db_session(migrated_database: None) -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(migrated_database: None) -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def make_tenant_with_admin(migrated_database: None) -> Iterator[
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


@pytest.fixture
def memory_storage() -> "Iterator[object]":
    from app.ingestion.storage import MemoryObjectStorage, set_object_storage

    storage = MemoryObjectStorage()
    set_object_storage(storage)
    yield storage
    set_object_storage(None)


@pytest.fixture
def use_fake_llm() -> Iterator["FakeLLMInstaller"]:
    installer = FakeLLMInstaller()
    yield installer
    installer.uninstall()


class FakeLLMInstaller:
    """Installs a deterministic fake adapter behind the gateway seam."""

    def __init__(self) -> None:
        self.adapter: object | None = None

    def install(self, respond: object) -> "object":

        from app.llm_gateway.adapters import DeterministicFakeAdapter
        from app.scoring import jobs as scoring_jobs

        assert callable(respond) or respond is None
        adapter = DeterministicFakeAdapter(
            respond if respond is None else self._as_callable(respond)
        )
        scoring_jobs.set_adapter(adapter)
        self.adapter = adapter
        return adapter

    @staticmethod
    def _as_callable(respond: object) -> Callable[[str, str], str]:
        def call(system: str, user_content: str) -> str:
            return str(respond(system, user_content))  # type: ignore[operator]

        return call

    def uninstall(self) -> None:
        from app.scoring import jobs as scoring_jobs

        scoring_jobs.set_adapter(None)


def run_all_jobs(max_seconds: float = 15.0) -> int:
    """Drain the job queue synchronously; returns the number of jobs run."""
    import time

    from app.jobs.runner import run_one
    from app.jobs.worker import register_all_handlers

    register_all_handlers()
    executed = 0
    deadline = time.monotonic() + max_seconds
    idle_cycles = 0
    while time.monotonic() < deadline:
        if run_one("test-worker"):
            executed += 1
            idle_cycles = 0
            continue
        idle_cycles += 1
        if idle_cycles > 5:
            break
        time.sleep(0.1)
    return executed


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
