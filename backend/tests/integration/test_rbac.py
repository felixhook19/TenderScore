"""RBAC: default-deny routes, admin-only management, distinct privileges."""

import uuid

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth.roles import PRIVILEGE_ANONYMISATION_MAP_READ
from tests.integration.conftest import TenantFactory, bearer, login

# Routes that are reachable without authentication, and nothing else.
UNAUTHENTICATED_ALLOWLIST = {
    ("GET", "/health"),
    ("POST", "/auth/login"),
    ("POST", "/auth/totp"),
}

_PATH_PARAM_SUBSTITUTES = {
    "user_id": str(uuid.uuid4()),
    "role": "admin",
    "privilege": "anonymisation_map.read",
}


def test_every_route_denies_unauthenticated_access_by_default(client: TestClient) -> None:
    """Default-deny: any route not on the explicit allowlist requires auth."""
    app = client.app
    routes = [route for route in app.routes if isinstance(route, APIRoute)]  # type: ignore[attr-defined]
    assert routes, "No routes found to walk."

    for route in routes:
        path = route.path
        for name, value in _PATH_PARAM_SUBSTITUTES.items():
            path = path.replace("{" + name + "}", value)
        for method in route.methods or set():
            if (method, route.path) in UNAUTHENTICATED_ALLOWLIST:
                continue
            response = client.request(method, path)
            assert response.status_code == 401, (
                f"{method} {route.path} responded {response.status_code} without "
                "authentication; every route must default-deny."
            )


def test_non_admins_cannot_manage_users(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    admin_token = login(client, provisioned.admin, provisioned.admin_password)

    created = client.post(
        "/users",
        headers=bearer(admin_token),
        json={
            "email": f"evaluator-{uuid.uuid4().hex[:8]}@example.org",
            "display_name": "An Evaluator",
            "password": "evaluator-password-123",
        },
    )
    assert created.status_code == 201
    evaluator_id = created.json()["id"]

    granted = client.post(
        f"/users/{evaluator_id}/roles",
        headers=bearer(admin_token),
        json={"role": "evaluator"},
    )
    assert granted.status_code == 204

    from app.auth.models import User
    from app.core.db import get_session_factory

    session = get_session_factory()()
    try:
        evaluator = session.get(User, uuid.UUID(evaluator_id))
        assert evaluator is not None
    finally:
        session.close()
    evaluator_token = login(client, evaluator, "evaluator-password-123")

    refused = client.post(
        "/users",
        headers=bearer(evaluator_token),
        json={
            "email": "intruder@example.org",
            "display_name": "Intruder",
            "password": "intruder-password-123",
        },
    )
    assert refused.status_code == 403


def test_anonymisation_privilege_is_not_implied_by_admin(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    """The anonymisation-map privilege is a distinct grant: even an admin
    holds it only after it is explicitly granted."""
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)

    me = client.get("/me", headers=bearer(token)).json()
    assert me["roles"] == ["admin"]
    assert PRIVILEGE_ANONYMISATION_MAP_READ not in me["privileges"]

    granted = client.post(
        f"/users/{provisioned.admin.id}/privileges",
        headers=bearer(token),
        json={"privilege": PRIVILEGE_ANONYMISATION_MAP_READ},
    )
    assert granted.status_code == 204

    me = client.get("/me", headers=bearer(token)).json()
    assert me["privileges"] == [PRIVILEGE_ANONYMISATION_MAP_READ]

    revoked = client.delete(
        f"/users/{provisioned.admin.id}/privileges/{PRIVILEGE_ANONYMISATION_MAP_READ}",
        headers=bearer(token),
    )
    assert revoked.status_code == 204
    me = client.get("/me", headers=bearer(token)).json()
    assert me["privileges"] == []


def test_unknown_privileges_are_rejected(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)
    refused = client.post(
        f"/users/{provisioned.admin.id}/privileges",
        headers=bearer(token),
        json={"privilege": "made_up.privilege"},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "This privilege is not recognised."


def test_admins_cannot_reach_other_tenants_users(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    tenant_one = make_tenant_with_admin()
    tenant_two = make_tenant_with_admin()
    token_one = login(client, tenant_one.admin, tenant_one.admin_password)

    response = client.post(
        f"/users/{tenant_two.admin.id}/roles",
        headers=bearer(token_one),
        json={"role": "evaluator"},
    )
    assert response.status_code == 404
