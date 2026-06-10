"""Authentication flow: password + TOTP, with audited failures."""

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from tests.integration.conftest import TenantFactory, bearer, login


def test_full_login_flow_and_me(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)

    response = client.get("/me", headers=bearer(token))
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == provisioned.admin.email
    assert body["roles"] == ["admin"]
    assert body["privileges"] == []


def test_wrong_password_is_rejected_and_audited(
    client: TestClient, make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    provisioned = make_tenant_with_admin()
    response = client.post(
        "/auth/login",
        json={"email": provisioned.admin.email, "password": "wrong-password-123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email address or password."

    failures = db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "auth.login.failed",
            AuditEvent.entity_id == str(provisioned.admin.id),
        )
    )
    assert failures == 1


def test_wrong_totp_code_is_rejected_and_audited(
    client: TestClient, make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    provisioned = make_tenant_with_admin()
    response = client.post(
        "/auth/login",
        json={"email": provisioned.admin.email, "password": provisioned.admin_password},
    )
    assert response.status_code == 200
    challenge_token = response.json()["challenge_token"]

    response = client.post(
        "/auth/totp", json={"challenge_token": challenge_token, "code": "000000"}
    )
    assert response.status_code == 401

    failures = db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == "auth.totp.failed",
            AuditEvent.entity_id == str(provisioned.admin.id),
        )
    )
    assert failures == 1


def test_unknown_email_is_rejected_without_leaking_existence(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.org", "password": "irrelevant-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email address or password."


def test_challenge_token_cannot_be_reused(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    import pyotp

    provisioned = make_tenant_with_admin()
    response = client.post(
        "/auth/login",
        json={"email": provisioned.admin.email, "password": provisioned.admin_password},
    )
    challenge_token = response.json()["challenge_token"]
    code = pyotp.TOTP(provisioned.admin.totp_secret).now()

    first = client.post(
        "/auth/totp", json={"challenge_token": challenge_token, "code": code}
    )
    assert first.status_code == 200
    second = client.post(
        "/auth/totp", json={"challenge_token": challenge_token, "code": code}
    )
    assert second.status_code == 401
