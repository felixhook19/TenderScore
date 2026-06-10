"""M1 exit criterion: the audit-completeness test.

Exercises every mutating route in the application, asserts each successful
state change emits at least one audit event, verifies the chain afterwards,
and fails if a mutating route exists that this suite does not cover — so
adding an endpoint without extending this test breaks CI by design.

Also proves both enforcement layers against an endpoint that "forgets" to
emit: the session dependency rolls the write back, and the middleware
refuses to report success.
"""

import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.verifier import verify_scope
from app.auth.deps import get_db
from app.auth.roles import PRIVILEGE_ANONYMISATION_MAP_READ
from app.main import create_app
from app.tenancy.models import Tenant
from tests.integration.conftest import TenantFactory, bearer, login


def _event_count(db_session: Session) -> int:
    count = db_session.scalar(select(func.count()).select_from(AuditEvent))
    assert count is not None
    return count


def _mutating_routes(app: FastAPI) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or set():
                if method in {"POST", "PUT", "PATCH", "DELETE"}:
                    routes.add((method, route.path))
    return routes


def test_every_mutating_route_emits_audit_events(
    client: TestClient, make_tenant_with_admin: TenantFactory, db_session: Session
) -> None:
    provisioned = make_tenant_with_admin()
    covered: set[tuple[str, str]] = set()

    def call_and_assert_audited(
        method: str, path: str, route_path: str, expected_status: int, **kwargs: object
    ) -> dict[str, object]:
        before = _event_count(db_session)
        response = client.request(method, path, **kwargs)  # type: ignore[arg-type]
        assert response.status_code == expected_status, (
            f"{method} {path}: {response.status_code} {response.text}"
        )
        db_session.expire_all()
        after = _event_count(db_session)
        assert after > before, (
            f"{method} {route_path} completed without emitting an audit event."
        )
        covered.add((method, route_path))
        return dict(response.json()) if response.content else {}

    # /auth/login and /auth/totp (the login helper exercises both, audited).
    before = _event_count(db_session)
    token = login(client, provisioned.admin, provisioned.admin_password)
    db_session.expire_all()
    assert _event_count(db_session) >= before + 2
    covered.add(("POST", "/auth/login"))
    covered.add(("POST", "/auth/totp"))

    headers = bearer(token)

    created = call_and_assert_audited(
        "POST",
        "/users",
        "/users",
        201,
        headers=headers,
        json={
            "email": f"completeness-{uuid.uuid4().hex[:8]}@example.org",
            "display_name": "Completeness Probe",
            "password": "a-valid-password-123",
        },
    )
    user_id = str(created["id"])

    call_and_assert_audited(
        "POST",
        f"/users/{user_id}/roles",
        "/users/{user_id}/roles",
        204,
        headers=headers,
        json={"role": "evaluator"},
    )
    call_and_assert_audited(
        "DELETE",
        f"/users/{user_id}/roles/evaluator",
        "/users/{user_id}/roles/{role}",
        204,
        headers=headers,
    )
    call_and_assert_audited(
        "POST",
        f"/users/{user_id}/privileges",
        "/users/{user_id}/privileges",
        204,
        headers=headers,
        json={"privilege": PRIVILEGE_ANONYMISATION_MAP_READ},
    )
    call_and_assert_audited(
        "DELETE",
        f"/users/{user_id}/privileges/{PRIVILEGE_ANONYMISATION_MAP_READ}",
        "/users/{user_id}/privileges/{privilege}",
        204,
        headers=headers,
    )

    # Coverage check: every mutating route in the app must be exercised here.
    app = client.app
    uncovered = _mutating_routes(app) - covered  # type: ignore[arg-type]
    assert not uncovered, (
        f"Mutating routes not covered by the audit-completeness test: {uncovered}. "
        "Extend this test when adding endpoints."
    )

    # And this tenant's chain must verify end to end after all of the above.
    # (Other chains in the shared test database are deliberately corrupted by
    # the tamper-detection tests, so verification is scoped to this tenant.)
    report = verify_scope(db_session, provisioned.tenant.id)
    assert report.valid, f"Chain {report.scope} failed verification: {report.detail}"


@pytest.fixture
def client_with_unaudited_routes() -> Iterator[TestClient]:
    """An app with deliberately defective endpoints for enforcement tests."""
    app = create_app()

    @app.post("/test-unaudited-write")
    def unaudited_write(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
        suffix = uuid.uuid4().hex[:8]
        db.add(Tenant(name=f"Rogue {suffix}", schema_name=f"rogue_{suffix}"))
        db.flush()
        return {"detail": "wrote state without an audit event"}

    @app.post("/test-unaudited-noop")
    def unaudited_noop() -> dict[str, str]:
        return {"detail": "claimed success without an audit event"}

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_unaudited_write_is_rolled_back_and_refused(
    client_with_unaudited_routes: TestClient, db_session: Session
) -> None:
    response = client_with_unaudited_routes.post("/test-unaudited-write")
    assert response.status_code == 500
    assert "audit" in response.json()["detail"].lower()

    rogue = db_session.scalar(select(Tenant).where(Tenant.name.like("Rogue %")))
    assert rogue is None, "The un-audited write must be rolled back, not committed."


def test_unaudited_success_is_refused_by_the_middleware(
    client_with_unaudited_routes: TestClient,
) -> None:
    response = client_with_unaudited_routes.post("/test-unaudited-noop")
    assert response.status_code == 500
    assert "audit" in response.json()["detail"].lower()
