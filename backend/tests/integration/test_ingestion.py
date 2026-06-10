"""M2 exit criteria: round-trip, stable hashes, seeded attacks flagged."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.core.db import tenant_session
from app.ingestion.service import ingest_submission
from app.ingestion.storage import MemoryObjectStorage
from tests.conftest import TenantFactory
from tests.support.synthetic import SyntheticTender, build_synthetic_tender


@pytest.fixture
def tenant_db(
    make_tenant_with_admin: TenantFactory,
) -> Iterator[tuple[Session, AuditRecorder, str, uuid.UUID]]:
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
    try:
        yield session, recorder, schema, provisioned.tenant.id
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def tender(
    tenant_db: tuple[Session, AuditRecorder, str, uuid.UUID],
) -> SyntheticTender:
    session, recorder, schema, _ = tenant_db
    built = build_synthetic_tender(session, recorder, tenant_schema=schema, lock=False)
    session.commit()
    return built


def test_submission_round_trips(
    tenant_db: tuple[Session, AuditRecorder, str, uuid.UUID], tender: SyntheticTender
) -> None:
    """Uploaded originals come back byte-identical and split correctly."""
    submission = tender.submissions_by_key["strong"]
    stored = tender.storage.get(submission.original_object_key)
    from tests.support.synthetic import FIXTURE_DIR

    assert stored == (FIXTURE_DIR / "submissions" / "strong.txt").read_bytes()
    refs = {
        ref for (key, ref) in tender.responses_by_key if key == "strong"
    }
    assert refs == {"Q1", "Q2.1", "Q2.2", "Q3.1", "Q3.2", "Q4", "Q5", "Q6"}


def test_hashes_are_stable_across_reingest(
    tenant_db: tuple[Session, AuditRecorder, str, uuid.UUID], tender: SyntheticTender
) -> None:
    session, recorder, _, _ = tenant_db
    submission = tender.submissions_by_key["mid"]
    first = {
        (response.criterion_ref): response.content_hash
        for (key, _), response in tender.responses_by_key.items()
        if key == "mid"
    }
    responses = ingest_submission(
        session, recorder, tender.storage, submission_id=submission.id
    )
    second = {response.criterion_ref: response.content_hash for response in responses}
    session.commit()
    assert first == second, "Content hashes must be stable across re-ingestion."


def test_seeded_injection_attempts_are_flagged(
    tenant_db: tuple[Session, AuditRecorder, str, uuid.UUID], tender: SyntheticTender
) -> None:
    """The gate-failer's five seeded attacks are all flagged at ingest."""
    seeded_refs = {"Q2.1", "Q2.2", "Q3.1", "Q3.2", "Q4"}
    flagged = {
        ref
        for (key, ref), response in tender.responses_by_key.items()
        if key == "gate_failer" and response.injection_scan.get("flagged")
    }
    assert seeded_refs <= flagged, f"Missed attacks in: {seeded_refs - flagged}"

    clean = {
        ref
        for (key, ref), response in tender.responses_by_key.items()
        if key == "strong" and response.injection_scan.get("flagged")
    }
    assert not clean, f"False positives on the clean bidder: {clean}"


def test_tampered_storage_is_detected(
    tenant_db: tuple[Session, AuditRecorder, str, uuid.UUID], tender: SyntheticTender
) -> None:
    """A stored original that no longer matches its hash refuses to ingest."""
    session, recorder, _, _ = tenant_db
    submission = tender.submissions_by_key["weak"]
    storage = MemoryObjectStorage()
    storage.objects[submission.original_object_key] = b"tampered bytes"
    from app.ingestion.service import IngestionError

    with pytest.raises(IngestionError, match="content hash"):
        ingest_submission(session, recorder, storage, submission_id=submission.id)
    session.commit()
