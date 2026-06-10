"""Prompt registry: reconcile, hash verification, change-without-bump."""

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.llm_gateway.registry import (
    RegistryIntegrityError,
    load_prompt_files,
    reconcile,
    resolve,
)


def test_reconcile_registers_and_resolves(db_session: Session) -> None:
    reconcile(db_session)
    prompt = resolve(db_session, "score_question_v1")
    assert prompt.version
    assert prompt.sha256_hash
    assert "{band_descriptors}" in prompt.instruction_template


def test_unregistered_prompt_is_refused(db_session: Session) -> None:
    reconcile(db_session)
    with pytest.raises(RegistryIntegrityError, match="not registered"):
        resolve(db_session, "prompt_that_does_not_exist")


def test_changed_file_without_version_bump_fails_startup(
    db_session: Session, tmp_path: Path
) -> None:
    artefact = tmp_path / "test_prompt_v1.yaml"
    artefact.write_text(
        "id: test_prompt_v1\nversion: 1.0.0\npurpose: test\n"
        "output_schema: none\ninstruction_template: Original text.\n"
    )
    reconcile(db_session, prompts_dir=tmp_path)

    # Same id and version, different content: prompts are code.
    artefact.write_text(
        "id: test_prompt_v1\nversion: 1.0.0\npurpose: test\n"
        "output_schema: none\ninstruction_template: Quietly changed text.\n"
    )
    with pytest.raises(RegistryIntegrityError, match="version bump"):
        reconcile(db_session, prompts_dir=tmp_path)


def test_prompt_files_are_well_formed() -> None:
    prompts = load_prompt_files()
    assert {"score_question_v1", "injection_classifier_v1", "framework_extraction_v1"} <= set(
        prompts
    )
