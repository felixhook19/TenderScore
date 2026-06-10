"""Canonical serialisation and hash-chain computation.

The event hash is `sha256(prev_event_hash || canonical_json(event_fields))`
over every recorded field except the database identifier. The verifier
recomputes exactly this from the stored columns, so any change to the
canonical form is a breaking change to chain verification and must never
happen silently.
"""

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime

GENESIS_HASH = "0" * 64

# Identifies the canonical serialisation; bump only with a migration story.
CHAIN_VERSION = 1


def _jsonify(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f"Type {type(value).__name__} is not canonically serialisable.")


def canonical_json(payload: Mapping[str, object]) -> str:
    """Serialise a payload deterministically: sorted keys, no whitespace."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_jsonify
    )


def compute_event_hash(prev_event_hash: str, payload: Mapping[str, object]) -> str:
    """Compute the chained hash for one event."""
    material = prev_event_hash + canonical_json(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def state_hash(payload: Mapping[str, object]) -> str:
    """Content-hash an entity state snapshot (for before_hash/after_hash)."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def event_payload(
    *,
    tenant_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    actor_type: str,
    action: str,
    entity_type: str,
    entity_id: str,
    before_hash: str | None,
    after_hash: str | None,
    prompt_id: str | None,
    prompt_version: str | None,
    model_version: str | None,
    occurred_at: datetime,
) -> dict[str, object]:
    """The exact field set covered by the event hash, in canonical form."""
    return {
        "chain_version": CHAIN_VERSION,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
        "actor_id": str(actor_id) if actor_id is not None else None,
        "actor_type": actor_type,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before_hash": before_hash,
        "after_hash": after_hash,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "model_version": model_version,
        "occurred_at": occurred_at.isoformat(),
    }
