"""The audit-completeness test (CI quality gate 5).

Walks the entire product through the API — framework set-up, ingestion,
calibration, scoring, moderation, pack generation, anonymisation reveal —
asserting that every mutating route emits at least one audit event, that no
mutating route exists outside this walk, and that the tenant's hash chain
verifies afterwards.

Also proves both enforcement layers against an endpoint that "forgets" to
emit: the session dependency rolls the write back, and the middleware
refuses to report success.
"""

import io
import uuid
from collections.abc import Iterator
from typing import Annotated

import pytest
from docx import Document
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
from tests.conftest import TenantFactory, bearer, login, run_all_jobs
from tests.support.fake_llm import OracleResponder

SUBMISSION_TEXT = """Question Q1
Our mobilisation plan names a lead for every workstream and completes
equipment commissioning within thirty days. Weekly reviews report progress
and exceptions to the council's contract manager throughout mobilisation.
"""


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
    client: TestClient,
    make_tenant_with_admin: TenantFactory,
    db_session: Session,
    memory_storage: object,
    use_fake_llm: object,
) -> None:
    use_fake_llm.install(OracleResponder(default_score=3))  # type: ignore[attr-defined]
    provisioned = make_tenant_with_admin()
    covered: set[tuple[str, str]] = set()

    def call(
        method: str, path: str, route_path: str, expected_status: int, **kwargs: object
    ) -> dict[str, object] | list[object]:
        before = _event_count(db_session)
        response = client.request(method, path, **kwargs)  # type: ignore[arg-type]
        assert response.status_code == expected_status, (
            f"{method} {path}: {response.status_code} {response.text}"
        )
        db_session.expire_all()
        assert _event_count(db_session) > before, (
            f"{method} {route_path} completed without emitting an audit event."
        )
        covered.add((method, route_path))
        if not response.content:
            return {}
        body = response.json()
        return body  # type: ignore[no-any-return]

    # --- Authentication ---------------------------------------------------
    before = _event_count(db_session)
    token = login(client, provisioned.admin, provisioned.admin_password)
    db_session.expire_all()
    assert _event_count(db_session) >= before + 2
    covered.add(("POST", "/auth/login"))
    covered.add(("POST", "/auth/totp"))
    headers = bearer(token)

    # --- User, role and privilege administration ---------------------------
    created_user = call(
        "POST",
        "/users",
        "/users",
        201,
        headers=headers,
        json={
            "email": f"walk-{uuid.uuid4().hex[:8]}@example.org",
            "display_name": "Walk Probe",
            "password": "a-valid-password-123",
        },
    )
    user_id = str(created_user["id"])  # type: ignore[call-overload]
    call(
        "POST", f"/users/{user_id}/roles", "/users/{user_id}/roles", 204,
        headers=headers, json={"role": "evaluator"},
    )
    call(
        "DELETE", f"/users/{user_id}/roles/evaluator", "/users/{user_id}/roles/{role}",
        204, headers=headers,
    )
    call(
        "POST", f"/users/{user_id}/privileges", "/users/{user_id}/privileges", 204,
        headers=headers, json={"privilege": PRIVILEGE_ANONYMISATION_MAP_READ},
    )
    call(
        "DELETE",
        f"/users/{user_id}/privileges/{PRIVILEGE_ANONYMISATION_MAP_READ}",
        "/users/{user_id}/privileges/{privilege}",
        204,
        headers=headers,
    )
    # The admin needs the reveal privilege later in the walk.
    client.post(
        f"/users/{provisioned.admin.id}/privileges",
        headers=headers,
        json={"privilege": PRIVILEGE_ANONYMISATION_MAP_READ},
    )

    # --- Framework ---------------------------------------------------------
    procurement = call(
        "POST",
        "/procurements",
        "/procurements",
        201,
        headers=headers,
        json={"title": "Completeness Walk", "reference": f"CW-{uuid.uuid4().hex[:8]}"},
    )
    pid = str(procurement["id"])  # type: ignore[call-overload]
    call(
        "POST", f"/procurements/{pid}/lots", "/procurements/{procurement_id}/lots",
        201, headers=headers, json={"lot_number": 1, "title": "Lot One"},
    )
    criterion = call(
        "POST",
        f"/procurements/{pid}/criteria",
        "/procurements/{procurement_id}/criteria",
        201,
        headers=headers,
        json={
            "ref": "Q1",
            "title": "Mobilisation",
            "weighting_pct": "60",
            "word_limit": 400,
            "descriptors": [
                {"band": 1, "label": "Poor", "descriptor_text": "Addresses little."},
                {"band": 3, "label": "Good", "descriptor_text": "Meets the requirement."},
                {"band": 5, "label": "Excellent", "descriptor_text": "Exceeds it."},
            ],
            "requirements": [{"ref": "R1", "text": "A mobilisation plan with named leads."}],
        },
    )
    criterion_id = str(criterion["id"])  # type: ignore[call-overload]
    call(
        "POST",
        f"/procurements/{pid}/framework/extract",
        "/procurements/{procurement_id}/framework/extract",
        200,
        headers=headers,
        json={"document_text": "Award criteria: quality 60 per cent, price 40."},
    )
    call(
        "POST",
        f"/procurements/{pid}/framework/lock",
        "/procurements/{procurement_id}/framework/lock",
        200,
        headers=headers,
    )

    # --- Bidder and submission ----------------------------------------------
    bidder = call(
        "POST",
        f"/procurements/{pid}/bidders",
        "/procurements/{procurement_id}/bidders",
        201,
        headers=headers,
        json={"legal_name": "Walkthrough Bidder Limited", "companies_house_no": "01234567"},
    )
    bidder_id = str(bidder["id"])  # type: ignore[call-overload]
    submission = call(
        "POST",
        f"/bidders/{bidder_id}/submissions",
        "/bidders/{bidder_id}/submissions",
        201,
        headers=headers,
        files={"file": ("answer.txt", io.BytesIO(SUBMISSION_TEXT.encode()), "text/plain")},
    )
    submission_id = str(submission["id"])  # type: ignore[call-overload]
    call(
        "POST",
        f"/submissions/{submission_id}/ingest",
        "/submissions/{submission_id}/ingest",
        202,
        headers=headers,
    )
    assert run_all_jobs() >= 1

    # --- Calibration ---------------------------------------------------------
    benchmark = call(
        "POST",
        f"/procurements/{pid}/calibration/benchmarks",
        "/procurements/{procurement_id}/calibration/benchmarks",
        201,
        headers=headers,
        json={
            "criterion_id": criterion_id,
            "title": "Benchmark one",
            "answer_text": "A thorough answer naming leads and timescales.",
            # Deliberately two bands from the engine's score of 3, so the
            # accept-divergence route is exercised meaningfully.
            "buyer_score": 1,
        },
    )
    benchmark_id = str(benchmark["id"])  # type: ignore[call-overload]
    call(
        "POST",
        f"/procurements/{pid}/calibration/run",
        "/procurements/{procurement_id}/calibration/run",
        200,
        headers=headers,
    )
    blocked = client.post(f"/procurements/{pid}/scoring/runs", headers=headers)
    assert blocked.status_code == 409, "Unreviewed divergence must block scoring."
    call(
        "POST",
        f"/procurements/{pid}/calibration/benchmarks/{benchmark_id}/accept-divergence",
        "/procurements/{procurement_id}/calibration/benchmarks/{benchmark_id}/accept-divergence",
        204,
        headers=headers,
        json={"rationale": "Reviewed: the benchmark answer was deliberately under-scored."},
    )

    # --- Scoring --------------------------------------------------------------
    call(
        "POST",
        f"/procurements/{pid}/scoring/runs",
        "/procurements/{procurement_id}/scoring/runs",
        202,
        headers=headers,
    )
    assert run_all_jobs() >= 1

    recommendations = client.get(
        f"/procurements/{pid}/recommendations", headers=headers
    ).json()
    assert len(recommendations) == 1, recommendations
    recommendation = recommendations[0]
    assert recommendation["score"] == 3
    assert recommendation["confidence_tier"] == "converged"

    # --- Moderation -------------------------------------------------------------
    call(
        "POST",
        f"/recommendations/{recommendation['id']}/moderate",
        "/recommendations/{recommendation_id}/moderate",
        201,
        headers=headers,
        json={
            "action": "amend",
            "final_score": 5,
            "rationale": "The panel agreed the evidence supports the higher band.",
        },
    )

    # --- Pack generation -----------------------------------------------------------
    call(
        "POST",
        f"/procurements/{pid}/packs/moderation",
        "/procurements/{procurement_id}/packs/moderation",
        202,
        headers=headers,
        json={"format": "docx"},
    )
    assert run_all_jobs() >= 1
    packs = client.get(f"/procurements/{pid}/packs/moderation", headers=headers).json()
    assert len(packs) == 1

    # The pack is provably derived from the record: every paragraph matches
    # a record-derived expectation (M8 exit criterion).
    pack_bytes = memory_storage.objects[packs[0]["object_key"]]  # type: ignore[attr-defined]
    paragraphs = [
        paragraph.text
        for paragraph in Document(io.BytesIO(pack_bytes)).paragraphs
        if paragraph.text.strip()
    ]
    assert any("Completeness Walk" in text for text in paragraphs)
    assert any("Recommended score: 3" in text for text in paragraphs)
    assert any("final score 5" in text for text in paragraphs)
    assert any(
        "The panel agreed the evidence supports the higher band." in text
        for text in paragraphs
    )
    allowed_markers = (
        "Moderation pack", "Procurement:", "Reference:", "Framework lock hash:",
        "Pinned model version:", "Generated at:", "Every entry below",
        "Q1 Mobilisation", "Recommended score:", "Moderation:",
        "Moderator's rationale:", "Recommendation justification:",
    )
    for text in paragraphs:
        assert any(text.startswith(marker) for marker in allowed_markers), (
            f"Pack contains un-recorded free text: '{text[:80]}'"
        )

    # --- Anonymisation reveal ---------------------------------------------------------
    call(
        "POST",
        f"/procurements/{pid}/anonymisation/reveal",
        "/procurements/{procurement_id}/anonymisation/reveal",
        200,
        headers=headers,
    )

    # --- Coverage and chain verification ------------------------------------------------
    uncovered = _mutating_routes(client.app) - covered  # type: ignore[arg-type]
    assert not uncovered, (
        f"Mutating routes not covered by the audit-completeness walk: {uncovered}. "
        "Extend this test when adding endpoints."
    )
    report = verify_scope(db_session, provisioned.tenant.id)
    assert report.valid, f"Chain {report.scope} failed verification: {report.detail}"


@pytest.fixture
def client_with_unaudited_routes(migrated_database: None) -> Iterator[TestClient]:
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
