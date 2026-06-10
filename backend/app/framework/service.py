"""Framework service: procurement set-up and the framework lock.

The lock hashes the full criteria tree, descriptors (verbatim), gates,
limits and the pinned model version. After lock, every edit is rejected
and the rejection itself is audited.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.hashing import canonical_json, state_hash
from app.audit.recorder import AuditRecorder
from app.core.config import get_settings
from app.core.hashing import content_hash_text
from app.framework.models import (
    BandDescriptor,
    Criterion,
    FrameworkLockEvent,
    Lot,
    Procurement,
    SpecRequirement,
)


class FrameworkError(Exception):
    """Invalid framework operation; message is safe to show."""


class FrameworkLockedError(FrameworkError):
    """An edit was attempted on a locked framework."""


def ensure_editable(procurement: Procurement) -> None:
    if procurement.status != "draft":
        raise FrameworkLockedError(
            "The framework is locked. Locked frameworks cannot be edited; the "
            "attempted change has been recorded."
        )


def create_procurement(
    session: Session,
    recorder: AuditRecorder,
    *,
    title: str,
    reference: str,
    regime: str,
) -> Procurement:
    if regime not in ("PA23", "PCR15"):
        raise FrameworkError("The regime must be PA23 or PCR15.")
    procurement = Procurement(title=title.strip(), reference=reference.strip(), regime=regime)
    session.add(procurement)
    session.flush()
    recorder.record(
        "procurement.created",
        entity_type="procurement",
        entity_id=str(procurement.id),
        after_hash=state_hash(
            {"id": procurement.id, "title": procurement.title, "reference": procurement.reference}
        ),
    )
    return procurement


def add_lot(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement: Procurement,
    lot_number: int,
    title: str,
) -> Lot:
    ensure_editable(procurement)
    lot = Lot(procurement_id=procurement.id, lot_number=lot_number, title=title.strip())
    session.add(lot)
    session.flush()
    recorder.record(
        "lot.created",
        entity_type="lot",
        entity_id=str(lot.id),
        after_hash=state_hash({"id": lot.id, "lot_number": lot.lot_number, "title": lot.title}),
    )
    return lot


def add_criterion(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement: Procurement,
    ref: str,
    title: str,
    weighting_pct: Decimal,
    lot_id: uuid.UUID | None = None,
    parent_id: uuid.UUID | None = None,
    is_gate: bool = False,
    gate_rule: dict[str, object] | None = None,
    word_limit: int | None = None,
    page_limit: int | None = None,
    price_criterion: bool = False,
    descriptors: list[tuple[int, str, str]] | None = None,
    requirements: list[tuple[str, str]] | None = None,
) -> Criterion:
    """Add a criterion (or sub-criterion when parent_id is set), with its
    band descriptors (band, label, verbatim text) and spec requirements."""
    ensure_editable(procurement)
    if is_gate and not gate_rule:
        raise FrameworkError("A gate criterion requires a gate rule.")

    criterion = Criterion(
        procurement_id=procurement.id,
        lot_id=lot_id,
        parent_id=parent_id,
        ref=ref.strip(),
        title=title.strip(),
        weighting_pct=weighting_pct,
        is_gate=is_gate,
        gate_rule=gate_rule,
        word_limit=word_limit,
        page_limit=page_limit,
        price_criterion=price_criterion,
    )
    session.add(criterion)
    session.flush()

    for band, label, descriptor_text in descriptors or []:
        session.add(
            BandDescriptor(
                criterion_id=criterion.id,
                band=band,
                label=label,
                descriptor_text=descriptor_text,
            )
        )
    for req_ref, req_text in requirements or []:
        session.add(SpecRequirement(criterion_id=criterion.id, ref=req_ref, text=req_text))
    session.flush()

    recorder.record(
        "criterion.created",
        entity_type="criterion",
        entity_id=str(criterion.id),
        after_hash=state_hash({"id": criterion.id, "ref": criterion.ref}),
    )
    return criterion


def _framework_snapshot(session: Session, procurement: Procurement) -> dict[str, object]:
    """The complete, canonical framework content covered by the lock hash."""
    lots = session.scalars(
        select(Lot).where(Lot.procurement_id == procurement.id).order_by(Lot.lot_number)
    ).all()
    criteria = session.scalars(
        select(Criterion)
        .where(Criterion.procurement_id == procurement.id)
        .order_by(Criterion.ref)
    ).all()
    criterion_ids = [criterion.id for criterion in criteria]
    descriptors = session.scalars(
        select(BandDescriptor)
        .where(BandDescriptor.criterion_id.in_(criterion_ids))
        .order_by(BandDescriptor.criterion_id, BandDescriptor.band)
    ).all() if criterion_ids else []
    requirements = session.scalars(
        select(SpecRequirement)
        .where(SpecRequirement.criterion_id.in_(criterion_ids))
        .order_by(SpecRequirement.criterion_id, SpecRequirement.ref)
    ).all() if criterion_ids else []

    return {
        "procurement": {
            "title": procurement.title,
            "reference": procurement.reference,
            "regime": procurement.regime,
        },
        "lots": [
            {"lot_number": lot.lot_number, "title": lot.title} for lot in lots
        ],
        "criteria": [
            {
                "ref": criterion.ref,
                "title": criterion.title,
                "parent_ref": next(
                    (parent.ref for parent in criteria if parent.id == criterion.parent_id),
                    None,
                ),
                "weighting_pct": str(criterion.weighting_pct),
                "is_gate": criterion.is_gate,
                "gate_rule": criterion.gate_rule,
                "word_limit": criterion.word_limit,
                "page_limit": criterion.page_limit,
                "price_criterion": criterion.price_criterion,
            }
            for criterion in criteria
        ],
        "band_descriptors": [
            {
                "criterion_id": str(descriptor.criterion_id),
                "band": descriptor.band,
                "label": descriptor.label,
                "descriptor_text": descriptor.descriptor_text,
            }
            for descriptor in descriptors
        ],
        "spec_requirements": [
            {
                "criterion_id": str(requirement.criterion_id),
                "ref": requirement.ref,
                "text": requirement.text,
            }
            for requirement in requirements
        ],
    }


def compute_lock_hash(
    session: Session, procurement: Procurement, model_version: str
) -> str:
    snapshot = _framework_snapshot(session, procurement)
    snapshot["pinned_model_version"] = model_version
    return content_hash_text(canonical_json(snapshot))


def lock_framework(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement: Procurement,
    locked_by: uuid.UUID | None,
) -> FrameworkLockEvent:
    """Lock the framework: hash the tree and pin the model version."""
    ensure_editable(procurement)

    criteria_count = session.scalar(
        select(Criterion.id).where(Criterion.procurement_id == procurement.id).limit(1)
    )
    if criteria_count is None:
        raise FrameworkError("A framework cannot be locked without criteria.")

    # The exact model version is pinned per procurement at lock time
    # (CLAUDE.md rule 2). [[ASSUMED: default model string in configuration —
    # confirm exact pinned model string and UK/EEA residency before pilots.]]
    model_version = get_settings().pinned_model_version_default
    lock_hash = compute_lock_hash(session, procurement, model_version)

    procurement.status = "locked"
    procurement.pinned_model_version = model_version
    procurement.framework_locked_at = datetime.now(UTC)
    procurement.framework_lock_hash = lock_hash

    lock_event = FrameworkLockEvent(
        procurement_id=procurement.id,
        lock_hash=lock_hash,
        model_version=model_version,
        locked_by=locked_by,
    )
    session.add(lock_event)
    session.flush()

    recorder.record(
        "framework.locked",
        entity_type="procurement",
        entity_id=str(procurement.id),
        after_hash=lock_hash,
        model_version=model_version,
    )
    return lock_event
