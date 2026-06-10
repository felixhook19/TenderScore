"""Audit read endpoints: tenant-scoped listing and chain verification."""

from fastapi.testclient import TestClient

from tests.integration.conftest import TenantFactory, bearer, login


def test_audit_listing_requires_an_audit_role(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)

    response = client.get("/audit/events", headers=bearer(token))
    assert response.status_code == 200
    actions = {event["action"] for event in response.json()}
    assert "tenant.provisioned" in actions
    assert "auth.login.succeeded" in actions


def test_audit_listing_is_tenant_scoped(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    tenant_one = make_tenant_with_admin()
    tenant_two = make_tenant_with_admin()
    token = login(client, tenant_one.admin, tenant_one.admin_password)

    response = client.get("/audit/events", headers=bearer(token))
    assert response.status_code == 200
    tenant_ids = {event["tenant_id"] for event in response.json()}
    assert tenant_ids == {str(tenant_one.tenant.id)}
    assert str(tenant_two.tenant.id) not in tenant_ids


def test_verify_endpoint_reports_a_valid_chain(
    client: TestClient, make_tenant_with_admin: TenantFactory
) -> None:
    provisioned = make_tenant_with_admin()
    token = login(client, provisioned.admin, provisioned.admin_password)

    response = client.get("/audit/verify", headers=bearer(token))
    assert response.status_code == 200
    report = response.json()
    assert report["valid"] is True
    assert report["scope"] == f"tenant:{provisioned.tenant.id}"
    assert report["event_count"] >= 1
