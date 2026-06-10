"""Loader for the synthetic_tender_01 fixture: builds the full procurement
in a tenant, ingests all four bidders, and exposes the pieces tests need."""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.framework.models import Criterion, Procurement
from app.framework.service import add_criterion, add_lot, create_procurement, lock_framework
from app.ingestion.models import Bidder, QuestionResponse, Submission
from app.ingestion.service import create_bidder, ingest_submission, store_submission
from app.ingestion.storage import MemoryObjectStorage

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "regression" / "fixtures" / (
    "synthetic_tender_01"
)


@dataclass
class SyntheticTender:
    procurement: Procurement
    criteria_by_ref: dict[str, Criterion]
    bidders_by_key: dict[str, Bidder]
    submissions_by_key: dict[str, Submission]
    responses_by_key: dict[tuple[str, str], QuestionResponse] = field(default_factory=dict)
    storage: MemoryObjectStorage = field(default_factory=MemoryObjectStorage)


def load_oracle() -> dict[str, dict[str, int | list[int]]]:
    data = yaml.safe_load((FIXTURE_DIR / "oracle.yaml").read_text())
    oracle: dict[str, dict[str, int | list[int]]] = {}
    for bidder_key, scores in data["oracle"].items():
        oracle[str(bidder_key)] = {str(ref): value for ref, value in scores.items()}
    return oracle


def build_synthetic_tender(
    session: Session,
    recorder: AuditRecorder,
    *,
    tenant_schema: str,
    storage: MemoryObjectStorage | None = None,
    lock: bool = True,
    reference_suffix: str = "",
) -> SyntheticTender:
    """Create the full fixture procurement, ingest every submission."""
    framework = yaml.safe_load((FIXTURE_DIR / "framework.yaml").read_text())
    bidder_spec = yaml.safe_load((FIXTURE_DIR / "bidders.yaml").read_text())
    object_storage = storage or MemoryObjectStorage()

    reference = framework["procurement"]["reference"] + (
        f"-{reference_suffix}" if reference_suffix else f"-{uuid.uuid4().hex[:8]}"
    )
    procurement = create_procurement(
        session,
        recorder,
        title=framework["procurement"]["title"],
        reference=reference,
        regime=framework["procurement"]["regime"],
    )
    for lot in framework["lots"]:
        add_lot(
            session,
            recorder,
            procurement=procurement,
            lot_number=lot["lot_number"],
            title=lot["title"],
        )

    criteria_by_ref: dict[str, Criterion] = {}
    for spec in framework["criteria"]:
        parent_ref = spec.get("parent_ref")
        criterion = add_criterion(
            session,
            recorder,
            procurement=procurement,
            ref=spec["ref"],
            title=spec["title"],
            weighting_pct=Decimal(str(spec["weighting_pct"])),
            parent_id=criteria_by_ref[parent_ref].id if parent_ref else None,
            is_gate=spec.get("is_gate", False),
            gate_rule=spec.get("gate_rule"),
            word_limit=spec.get("word_limit"),
            page_limit=spec.get("page_limit"),
            price_criterion=spec.get("price_criterion", False),
            descriptors=[
                (d["band"], d["label"], d["descriptor_text"])
                for d in spec.get("descriptors", [])
            ],
            requirements=[
                (r["ref"], r["text"]) for r in spec.get("requirements", [])
            ],
        )
        criteria_by_ref[spec["ref"]] = criterion

    bidders_by_key: dict[str, Bidder] = {}
    submissions_by_key: dict[str, Submission] = {}
    for spec in bidder_spec["bidders"]:
        bidder = create_bidder(
            session,
            recorder,
            procurement=procurement,
            legal_name=spec["legal_name"],
            companies_house_no=spec.get("companies_house_no"),
        )
        bidders_by_key[spec["key"]] = bidder
        data = (FIXTURE_DIR / "submissions" / f"{spec['key']}.txt").read_bytes()
        submission = store_submission(
            session,
            recorder,
            object_storage,
            tenant_schema=tenant_schema,
            bidder=bidder,
            lot_id=None,
            filename=f"{spec['key']}.txt",
            data=data,
            content_type="text/plain",
        )
        submissions_by_key[spec["key"]] = submission

    tender = SyntheticTender(
        procurement=procurement,
        criteria_by_ref=criteria_by_ref,
        bidders_by_key=bidders_by_key,
        submissions_by_key=submissions_by_key,
        storage=object_storage,
    )

    for key, submission in submissions_by_key.items():
        responses = ingest_submission(
            session, recorder, object_storage, submission_id=submission.id
        )
        for response in responses:
            tender.responses_by_key[(key, response.criterion_ref)] = response

    if lock:
        lock_framework(session, recorder, procurement=procurement, locked_by=None)

    session.flush()
    return tender
