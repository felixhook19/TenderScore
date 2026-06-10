"""M10: rate limiting, account lockout, session revocation, log scrubbing."""

import logging
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.hardening import ScrubbingFilter
from tests.conftest import TenantFactory, bearer, login


@pytest.fixture
def strict_rate_limit_client(migrated_database: None) -> Iterator[TestClient]:
    os.environ["TENDERSCORE_AUTH_RATE_LIMIT_ATTEMPTS"] = "3"
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    del os.environ["TENDERSCORE_AUTH_RATE_LIMIT_ATTEMPTS"]
    get_settings.cache_clear()


def test_auth_endpoints_are_rate_limited(strict_rate_limit_client: TestClient) -> None:
    payload = {"email": "nobody@example.org", "password": "irrelevant-password"}
    statuses = [
        strict_rate_limit_client.post("/auth/login", json=payload).status_code
        for _ in range(4)
    ]
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429


def test_account_locks_after_repeated_failures(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    for _ in range(get_settings().lockout_failed_attempts):
        response = client.post(
            "/auth/login",
            json={"email": provisioned.admin.email, "password": "wrong-password-123"},
        )
        assert response.status_code == 401

    locked = client.post(
        "/auth/login",
        json={
            "email": provisioned.admin.email,
            "password": provisioned.admin_password,  # even the correct password
        },
    )
    assert locked.status_code == 423
    assert "temporarily locked" in locked.json()["detail"]


def test_logout_revokes_the_session(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)
    assert client.get("/me", headers=bearer(token)).status_code == 200

    response = client.post("/auth/logout", headers=bearer(token))
    assert response.status_code == 200
    assert client.get("/me", headers=bearer(token)).status_code == 401


def test_log_scrubbing_redacts_secrets() -> None:
    scrubber = ScrubbingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=(
            "Authorization: Bearer abc123def456abc123def456abc123def456 sent by "
            "felix@example.org"
        ),
        args=(),
        exc_info=None,
    )
    assert scrubber.filter(record)
    message = record.getMessage()
    assert "abc123def456" not in message
    assert "felix@example.org" not in message
    assert "[email redacted]" in message
