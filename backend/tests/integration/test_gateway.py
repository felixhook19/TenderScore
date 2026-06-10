"""M4 exit criteria: gateway refusals are enforced and audited."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditEvent
from app.audit.recorder import AuditRecorder
from app.framework.models import Procurement
from app.llm_gateway.adapters import DeterministicFakeAdapter
from app.llm_gateway.gateway import GatewayRefusalError, LLMGateway, make_scanned_content
from app.llm_gateway.registry import RegisteredPrompt
from tests.support.fake_llm import OracleResponder


@pytest.fixture
def prompt() -> RegisteredPrompt:
    return RegisteredPrompt(
        prompt_id="score_question_v1",
        version="1.0.0",
        sha256_hash="a" * 64,
        purpose="test",
        output_schema="score_output_v1",
        instruction_template=(
            "Score {criterion_ref}.\nBand 3 (Good): Meets the requirement.\n"
            "{band_descriptors}"
        ),
    )


@pytest.fixture
def procurement() -> Procurement:
    return Procurement(
        id=uuid.uuid4(),
        title="Gateway Test",
        reference=f"GT-{uuid.uuid4().hex[:8]}",
        pinned_model_version="pinned-model-1",
    )


def _gateway() -> LLMGateway:
    return LLMGateway(DeterministicFakeAdapter(OracleResponder()))


def _refusal_count(db_session: Session) -> int:
    count = db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "llm.call_refused")
    )
    assert count is not None
    return count


def test_non_zero_temperature_is_refused(
    db_session: Session, prompt: RegisteredPrompt, procurement: Procurement
) -> None:
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    before = _refusal_count(db_session)
    with pytest.raises(GatewayRefusalError, match=r"[Tt]emperature"):
        _gateway().score(
            db_session,
            recorder,
            prompt=prompt,
            instruction_vars={"criterion_ref": "Q1", "band_descriptors": ""},
            content_block=make_scanned_content("answer", scan_flagged=False, truncated=False),
            procurement=procurement,
            model_version="pinned-model-1",
            temperature=0.7,
        )
    db_session.commit()
    assert _refusal_count(db_session) == before + 1


def test_wrong_model_version_is_refused_and_audited(
    db_session: Session, prompt: RegisteredPrompt, procurement: Procurement
) -> None:
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    before = _refusal_count(db_session)
    with pytest.raises(GatewayRefusalError, match="pinned"):
        _gateway().score(
            db_session,
            recorder,
            prompt=prompt,
            instruction_vars={"criterion_ref": "Q1", "band_descriptors": ""},
            content_block=make_scanned_content("answer", scan_flagged=False, truncated=False),
            procurement=procurement,
            model_version="some-other-model",
        )
    db_session.commit()
    assert _refusal_count(db_session) == before + 1


def test_unlocked_procurement_is_refused(
    db_session: Session, prompt: RegisteredPrompt
) -> None:
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    unlocked = Procurement(
        id=uuid.uuid4(), title="U", reference=f"U-{uuid.uuid4().hex[:6]}"
    )
    with pytest.raises(GatewayRefusalError, match="pinned model version"):
        _gateway().score(
            db_session,
            recorder,
            prompt=prompt,
            instruction_vars={"criterion_ref": "Q1", "band_descriptors": ""},
            content_block=make_scanned_content("answer", scan_flagged=False, truncated=False),
            procurement=unlocked,
            model_version="anything",
        )
    db_session.commit()


def test_tainted_instruction_is_refused_and_audited(
    db_session: Session, prompt: RegisteredPrompt, procurement: Procurement
) -> None:
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    before = _refusal_count(db_session)
    bidder_text = "Our unique mobilisation answer text."
    with pytest.raises(GatewayRefusalError, match="instruction"):
        _gateway().score(
            db_session,
            recorder,
            prompt=prompt,
            instruction_vars={"criterion_ref": "Q1", "band_descriptors": bidder_text},
            content_block=make_scanned_content(
                bidder_text, scan_flagged=False, truncated=False
            ),
            procurement=procurement,
            model_version="pinned-model-1",
        )
    db_session.commit()
    assert _refusal_count(db_session) == before + 1


def test_registered_call_succeeds_and_is_recorded(
    db_session: Session, prompt: RegisteredPrompt, procurement: Procurement
) -> None:
    recorder = AuditRecorder(db_session, tenant_id=None, actor_id=None, actor_type="system")
    result = _gateway().score(
        db_session,
        recorder,
        prompt=prompt,
        instruction_vars={"criterion_ref": "Q1", "band_descriptors": "Band 3 (Good): Meets."},
        content_block=make_scanned_content(
            "Our answer describes weekly inspections.", scan_flagged=False, truncated=False
        ),
        procurement=procurement,
        model_version="pinned-model-1",
    )
    db_session.commit()
    assert result.model_version == "pinned-model-1"
    assert result.tokens_in > 0

    event = db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "llm.call", AuditEvent.entity_id == result.request_hash)
        .order_by(AuditEvent.id.desc())
    )
    assert event is not None
    assert event.prompt_id == "score_question_v1"
    assert event.prompt_version == "1.0.0"
    assert event.model_version == "pinned-model-1"
