"""Anonymisation: rules + gazetteer redaction and the privileged map.

Bidder identity is removed from text before it reaches an evaluator or the
scoring context: legal names (and common variants), Companies House
numbers, email addresses, phone numbers, URLs and postcodes. The
bidder-to-token map is readable only with the distinct
`anonymisation_map.read` privilege, and every read is individually audited.

[[ASSUMED]] v1 is rules + gazetteer (the bidder register provides the
names); a statistical NER layer can be added behind the same function
without changing callers.
"""

import re
import string
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anonymisation.models import AnonymisationMapEntry
from app.audit.recorder import AuditRecorder
from app.ingestion.models import Bidder

_LEGAL_SUFFIXES = (
    "limited",
    "ltd",
    "ltd.",
    "plc",
    "llp",
    "cic",
    "group",
    "services",
    "solutions",
)

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\b(?:\+44\s?\d{4}|\(?0\d{3,4}\)?)\s?\d{3}\s?\d{3,4}\b")
_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+\b", re.IGNORECASE)
_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
_COMPANIES_HOUSE = re.compile(r"\b(?:company\s+(?:no|number)\.?:?\s*)?\d{8}\b", re.IGNORECASE)


def token_for_index(index: int) -> str:
    """0 -> 'Bidder A', 25 -> 'Bidder Z', 26 -> 'Bidder AA', ..."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = string.ascii_uppercase[remainder] + letters
    return f"Bidder {letters}"


def assign_tokens(session: Session, recorder: AuditRecorder, procurement_id: uuid.UUID) -> None:
    """Assign anonymisation tokens to any bidders that lack one, audited."""
    bidders = session.scalars(
        select(Bidder)
        .where(Bidder.procurement_id == procurement_id)
        .order_by(Bidder.created_at, Bidder.id)
    ).all()
    existing = {
        entry.bidder_id: entry
        for entry in session.scalars(
            select(AnonymisationMapEntry).where(
                AnonymisationMapEntry.procurement_id == procurement_id
            )
        )
    }
    used_indices = len(existing)
    for bidder in bidders:
        if bidder.id in existing:
            continue
        entry = AnonymisationMapEntry(
            bidder_id=bidder.id,
            procurement_id=procurement_id,
            token=token_for_index(used_indices),
        )
        used_indices += 1
        session.add(entry)
        session.flush()
        recorder.record(
            "anonymisation.token_assigned",
            entity_type="bidder",
            entity_id=str(bidder.id),
        )


def _name_variants(legal_name: str) -> list[str]:
    """The legal name plus its de-suffixed variants, longest first."""
    variants = {legal_name.strip()}
    lowered = legal_name.strip()
    for suffix in _LEGAL_SUFFIXES:
        pattern = re.compile(rf"\s+{re.escape(suffix)}\.?$", re.IGNORECASE)
        without = pattern.sub("", lowered)
        if without and without.lower() != lowered.lower():
            variants.add(without)
            lowered = without
    return sorted(variants, key=len, reverse=True)


def anonymise_text(
    session: Session, *, procurement_id: uuid.UUID, bidder_id: uuid.UUID, text: str
) -> str:
    """Redact bidder identity from text using the procurement's register."""
    bidders = session.scalars(
        select(Bidder).where(Bidder.procurement_id == procurement_id)
    ).all()
    tokens = {
        map_entry.bidder_id: map_entry.token
        for map_entry in session.scalars(
            select(AnonymisationMapEntry).where(
                AnonymisationMapEntry.procurement_id == procurement_id
            )
        )
    }

    redacted = text
    for bidder in sorted(bidders, key=lambda b: len(b.legal_name), reverse=True):
        replacement = tokens.get(bidder.id, "another bidder")
        for variant in _name_variants(bidder.legal_name):
            redacted = re.sub(re.escape(variant), replacement, redacted, flags=re.IGNORECASE)
        if bidder.companies_house_no:
            redacted = redacted.replace(bidder.companies_house_no, "[company number]")

    redacted = _EMAIL.sub("[email address]", redacted)
    redacted = _URL.sub("[web address]", redacted)
    redacted = _PHONE.sub("[telephone number]", redacted)
    redacted = _POSTCODE.sub("[postcode]", redacted)
    redacted = _COMPANIES_HOUSE.sub("[company number]", redacted)
    return redacted


def reveal_map(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement_id: uuid.UUID,
) -> list[tuple[str, str]]:
    """Reveal the bidder-to-token map. Caller must hold the distinct
    privilege; every access is audited here, unconditionally."""
    rows = session.execute(
        select(Bidder.legal_name, AnonymisationMapEntry.token)
        .join(AnonymisationMapEntry, AnonymisationMapEntry.bidder_id == Bidder.id)
        .where(AnonymisationMapEntry.procurement_id == procurement_id)
        .order_by(AnonymisationMapEntry.token)
    ).all()
    recorder.record(
        "anonymisation_map.read",
        entity_type="procurement",
        entity_id=str(procurement_id),
    )
    return [(row[0], row[1]) for row in rows]
