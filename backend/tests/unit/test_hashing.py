"""Canonical serialisation and hash-chain computation tests."""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.hashing import (
    GENESIS_HASH,
    canonical_json,
    compute_event_hash,
    event_payload,
    state_hash,
)


def test_canonical_json_is_key_order_independent() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_canonical_json_has_no_whitespace() -> None:
    assert canonical_json({"a": [1, 2], "b": "x"}) == '{"a":[1,2],"b":"x"}'


def test_canonical_json_serialises_datetimes_and_uuids() -> None:
    moment = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    identifier = uuid.UUID("00000000-0000-0000-0000-000000000001")
    rendered = canonical_json({"at": moment, "id": identifier})
    assert "2026-06-10T12:00:00+00:00" in rendered
    assert "00000000-0000-0000-0000-000000000001" in rendered


def test_canonical_json_rejects_unserialisable_types() -> None:
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


def test_event_hash_is_deterministic_and_chained() -> None:
    payload = {"action": "test"}
    first = compute_event_hash(GENESIS_HASH, payload)
    assert first == compute_event_hash(GENESIS_HASH, payload)
    second = compute_event_hash(first, payload)
    assert second != first


def test_event_payload_covers_every_recorded_field() -> None:
    payload = event_payload(
        tenant_id=uuid.uuid4(),
        actor_id=None,
        actor_type="system",
        action="tenant.provisioned",
        entity_type="tenant",
        entity_id="x",
        before_hash=None,
        after_hash="a" * 64,
        prompt_id=None,
        prompt_version=None,
        model_version=None,
        occurred_at=datetime.now(UTC),
    )
    assert set(payload) == {
        "chain_version",
        "tenant_id",
        "actor_id",
        "actor_type",
        "action",
        "entity_type",
        "entity_id",
        "before_hash",
        "after_hash",
        "prompt_id",
        "prompt_version",
        "model_version",
        "occurred_at",
    }


def test_state_hash_is_stable() -> None:
    assert state_hash({"a": 1}) == state_hash({"a": 1})
    assert state_hash({"a": 1}) != state_hash({"a": 2})
