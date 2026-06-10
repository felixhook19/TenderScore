"""M6 exit criteria: anonymised text is clean; map access is privileged
and audited."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anonymisation.service import anonymise_text, assign_tokens, token_for_index
from app.audit.models import AuditEvent
from app.audit.recorder import AuditRecorder
from app.core.db import tenant_session
from tests.conftest import TenantFactory, bearer, login
from tests.support.synthetic import SyntheticTender, build_synthetic_tender

SEEDED_IDENTIFIERS = [
    "Greenhollow",
    "Fenwick",
    "Marsh",
    "Bramblefield",
    "Thistlewood",
    "09876543",
    "08765432",
    "07654321",
    "06543210",
]


@pytest.fixture
def anonymised_setup(
    make_tenant_with_admin: TenantFactory,
) -> Iterator[tuple[Session, SyntheticTender, uuid.UUID, object]]:
    provisioned = make_tenant_with_admin()
    from app.core.db import get_session_factory
    from app.tenancy.models import Tenant

    lookup = get_session_factory()()
    try:
        tenant = lookup.get(Tenant, provisioned.tenant.id)
        assert tenant is not None
        schema = tenant.schema_name
    finally:
        lookup.close()
    session = tenant_session(schema)
    recorder = AuditRecorder(
        session, tenant_id=provisioned.tenant.id, actor_id=None, actor_type="system"
    )
    tender = build_synthetic_tender(session, recorder, tenant_schema=schema, lock=False)
    assign_tokens(session, recorder, tender.procurement.id)
    session.commit()
    try:
        yield session, tender, provisioned.tenant.id, provisioned
    finally:
        session.rollback()
        session.close()


def test_tokens_are_sequential_bidder_letters() -> None:
    assert token_for_index(0) == "Bidder A"
    assert token_for_index(25) == "Bidder Z"
    assert token_for_index(26) == "Bidder AA"


def test_anonymised_text_contains_no_seeded_identifiers(
    anonymised_setup: tuple[Session, SyntheticTender, uuid.UUID, object],
) -> None:
    session, tender, _, _ = anonymised_setup
    sample = (
        "Greenhollow Grounds Limited (company number 09876543) will partner with "
        "Fenwick & Marsh Landscapes Limited. Contact mowing@greenhollow.example.org "
        "or call 01632 960123. Registered at 1 Meadow Way, EX4 4MP. "
        "See www.greenhollow.example.org for details."
    )
    for bidder in tender.bidders_by_key.values():
        cleaned = anonymise_text(
            session,
            procurement_id=tender.procurement.id,
            bidder_id=bidder.id,
            text=sample,
        )
        for identifier in SEEDED_IDENTIFIERS:
            assert identifier not in cleaned, f"'{identifier}' leaked: {cleaned}"
        assert "@" not in cleaned
        assert "01632" not in cleaned
        assert "EX4 4MP" not in cleaned


def test_reveal_requires_the_distinct_privilege(
    client: "object",
    anonymised_setup: tuple[Session, SyntheticTender, uuid.UUID, object],
) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    _, tender, _, provisioned = anonymised_setup
    token = login(client, provisioned.admin, provisioned.admin_password)  # type: ignore[attr-defined]

    refused = client.post(
        f"/procurements/{tender.procurement.id}/anonymisation/reveal",
        headers=bearer(token),
    )
    assert refused.status_code == 403

    granted = client.post(
        f"/users/{provisioned.admin.id}/privileges",  # type: ignore[attr-defined]
        headers=bearer(token),
        json={"privilege": "anonymisation_map.read"},
    )
    assert granted.status_code == 204

    revealed = client.post(
        f"/procurements/{tender.procurement.id}/anonymisation/reveal",
        headers=bearer(token),
    )
    assert revealed.status_code == 200
    names = {entry["legal_name"] for entry in revealed.json()}
    assert "Greenhollow Grounds Limited" in names


def test_every_map_access_is_audited(
    client: "object",
    anonymised_setup: tuple[Session, SyntheticTender, uuid.UUID, object],
    db_session: Session,
) -> None:
    from fastapi.testclient import TestClient

    assert isinstance(client, TestClient)
    _, tender, tenant_id, provisioned = anonymised_setup
    token = login(client, provisioned.admin, provisioned.admin_password)  # type: ignore[attr-defined]
    client.post(
        f"/users/{provisioned.admin.id}/privileges",  # type: ignore[attr-defined]
        headers=bearer(token),
        json={"privilege": "anonymisation_map.read"},
    )

    def access_count() -> int:
        db_session.expire_all()
        count = db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "anonymisation_map.read",
                AuditEvent.tenant_id == tenant_id,
            )
        )
        assert count is not None
        return count

    before = access_count()
    for _ in range(3):
        response = client.post(
            f"/procurements/{tender.procurement.id}/anonymisation/reveal",
            headers=bearer(token),
        )
        assert response.status_code == 200
    assert access_count() == before + 3, "Each access must be individually audited."
