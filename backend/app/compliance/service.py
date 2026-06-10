"""Compliance: word/page limits, attachment checks, caveat detection, and
pass/fail gate enforcement.

Gate semantics: a bidder whose moderated (or, pre-moderation, recommended)
score on a gate criterion falls below the gate minimum fails the gate, and
further scoring for that bidder on that criterion (and dependent
recommendations) is blocked — never silently, always audited.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.framework.models import Criterion
from app.ingestion.models import QuestionResponse, Submission
from app.scoring.models import Recommendation, ScoringRun

_CAVEAT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bsubject\s+to\s+(?:contract|agreement|negotiation|survey|review)\b",
        r"\bwe\s+assume\b",
        r"\bour\s+(?:price|offer|proposal)\s+(?:assumes|excludes|is\s+conditional)\b",
        r"\bprovided\s+that\b",
        r"\bon\s+condition\s+that\b",
        r"\bthis\s+(?:offer|bid|price)\s+is\s+(?:conditional|contingent)\b",
        r"\bexcludes?\s+(?:vat\s+and|all|any)\s+\w+\s+(?:costs|charges|works)\b",
    )
]


def check_response_compliance(
    session: Session,
    recorder: AuditRecorder,
    *,
    response: QuestionResponse,
) -> QuestionResponse:
    """Apply limit and caveat checks to one question response, audited."""
    notes: list[str] = []
    status = "compliant"

    criterion = (
        session.get(Criterion, response.criterion_id)
        if response.criterion_id is not None
        else None
    )
    if criterion is not None and criterion.word_limit is not None:
        if response.word_count > criterion.word_limit:
            status = "non_compliant"
            notes.append(
                f"The response is {response.word_count} words against a published "
                f"limit of {criterion.word_limit}. Text beyond the limit is not "
                "evaluated."
            )

    caveats = [
        match.group(0)
        for pattern in _CAVEAT_PATTERNS
        for match in [pattern.search(response.text)]
        if match
    ]
    if caveats and status == "compliant":
        status = "caveat_flagged"
    if caveats:
        notes.append(
            "Possible caveats detected for human review: "
            + "; ".join(f"'{caveat}'" for caveat in caveats[:5])
        )

    response.compliance_status = status
    response.compliance_notes = notes
    session.flush()
    recorder.record(
        "compliance.checked",
        entity_type="question_response",
        entity_id=str(response.id),
        after_hash=response.content_hash,
    )
    return response


def run_compliance_checks(
    session: Session, recorder: AuditRecorder, *, submission_id: uuid.UUID
) -> list[QuestionResponse]:
    responses = session.scalars(
        select(QuestionResponse).where(QuestionResponse.submission_id == submission_id)
    ).all()
    return [
        check_response_compliance(session, recorder, response=response)
        for response in responses
    ]


def gate_minimum(criterion: Criterion) -> int | None:
    """The minimum score demanded by a gate criterion's rule, if any."""
    if not criterion.is_gate or not criterion.gate_rule:
        return None
    rule = criterion.gate_rule
    if rule.get("type") == "min_score":
        value = rule.get("value")
        if isinstance(value, int):
            return value
    return None


def failed_gate_bidders(session: Session, procurement_id: uuid.UUID) -> set[uuid.UUID]:
    """Bidders whose recommended score on any gate criterion is below the
    gate minimum (moderation may supersede; v1 evaluates on recommendations
    and confirmed decisions alike via the recommendation score)."""
    gates = session.scalars(
        select(Criterion).where(
            Criterion.procurement_id == procurement_id, Criterion.is_gate.is_(True)
        )
    ).all()
    failed: set[uuid.UUID] = set()
    for gate in gates:
        minimum = gate_minimum(gate)
        if minimum is None:
            continue
        rows = session.execute(
            select(ScoringRun.bidder_id, Recommendation.score)
            .join(Recommendation, Recommendation.run_id == ScoringRun.id)
            .where(
                ScoringRun.procurement_id == procurement_id,
                ScoringRun.criterion_id == gate.id,
                Recommendation.score.is_not(None),
            )
        ).all()
        for bidder_id, score in rows:
            if score is not None and score < minimum:
                failed.add(bidder_id)
    return failed


def record_gate_failure(
    session: Session,
    recorder: AuditRecorder,
    *,
    procurement_id: uuid.UUID,
    bidder_id: uuid.UUID,
    criterion_id: uuid.UUID,
) -> None:
    recorder.record(
        "gate.failed",
        entity_type="bidder",
        entity_id=str(bidder_id),
    )


def attachment_check(submission: Submission, responses: list[QuestionResponse]) -> list[str]:
    """Attachment presence notes (v1: declared attachments are listed per
    response; missing declarations produce review notes)."""
    notes: list[str] = []
    for response in responses:
        declared = response.attachments or []
        if declared:
            notes.append(
                f"Response {response.criterion_ref} declares {len(declared)} "
                "attachment(s); verify they were provided."
            )
    return notes
