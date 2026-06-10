"""Prompt registry: versioned, hashed YAML artefacts.

Prompts are code. On startup, files in `backend/prompts/` are hashed and
reconciled against `platform.prompt_registry`; a changed file without a
version bump fails startup outright.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.hashing import content_hash_bytes
from app.llm_gateway.models import PromptRegistryEntry

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


class RegistryIntegrityError(Exception):
    """A prompt artefact changed without a version bump, or is malformed."""


@dataclass(frozen=True)
class RegisteredPrompt:
    prompt_id: str
    version: str
    sha256_hash: str
    purpose: str
    output_schema: str
    instruction_template: str


def _load_file(path: Path) -> RegisteredPrompt:
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise RegistryIntegrityError(f"Prompt artefact {path.name} is not a mapping.")
    try:
        return RegisteredPrompt(
            prompt_id=str(data["id"]),
            version=str(data["version"]),
            sha256_hash=content_hash_bytes(raw),
            purpose=str(data["purpose"]),
            output_schema=str(data["output_schema"]),
            instruction_template=str(data["instruction_template"]),
        )
    except KeyError as error:
        raise RegistryIntegrityError(
            f"Prompt artefact {path.name} is missing the {error} field."
        ) from error


def load_prompt_files(prompts_dir: Path | None = None) -> dict[str, RegisteredPrompt]:
    """Load every prompt artefact, keyed by prompt id (latest file wins is
    not a concept here: one file per id; duplicates are an error)."""
    directory = prompts_dir or PROMPTS_DIR
    prompts: dict[str, RegisteredPrompt] = {}
    for path in sorted(directory.glob("*.yaml")):
        prompt = _load_file(path)
        if prompt.prompt_id in prompts:
            raise RegistryIntegrityError(
                f"Duplicate prompt id '{prompt.prompt_id}' in {path.name}."
            )
        prompts[prompt.prompt_id] = prompt
    return prompts


def reconcile(session: Session, prompts_dir: Path | None = None) -> None:
    """Reconcile prompt files against the registry table.

    New (id, version) pairs are registered; a hash mismatch on an existing
    pair raises and must fail startup.
    """
    directory = prompts_dir or PROMPTS_DIR
    for path in sorted(directory.glob("*.yaml")):
        prompt = _load_file(path)
        existing = session.get(PromptRegistryEntry, (prompt.prompt_id, prompt.version))
        if existing is None:
            session.add(
                PromptRegistryEntry(
                    prompt_id=prompt.prompt_id,
                    version=prompt.version,
                    sha256_hash=prompt.sha256_hash,
                    purpose=prompt.purpose,
                    file_path=str(path.name),
                )
            )
            session.flush()
        elif existing.sha256_hash != prompt.sha256_hash:
            raise RegistryIntegrityError(
                f"Prompt '{prompt.prompt_id}' version {prompt.version} has changed "
                "on disk without a version bump. Prompts are code: bump the "
                "version and re-run the regression and red-team suites."
            )
    session.commit()


def resolve(
    session: Session, prompt_id: str, prompts_dir: Path | None = None
) -> RegisteredPrompt:
    """Resolve a prompt by id, verifying the file hash against the registry."""
    prompts = load_prompt_files(prompts_dir)
    prompt = prompts.get(prompt_id)
    if prompt is None:
        raise RegistryIntegrityError(f"Prompt '{prompt_id}' is not registered.")
    entry = session.get(PromptRegistryEntry, (prompt.prompt_id, prompt.version))
    if entry is None:
        raise RegistryIntegrityError(
            f"Prompt '{prompt_id}' version {prompt.version} is not in the registry; "
            "the application must reconcile at startup before use."
        )
    if entry.sha256_hash != prompt.sha256_hash:
        raise RegistryIntegrityError(
            f"Prompt '{prompt_id}' version {prompt.version} does not match its "
            "registered hash."
        )
    return prompt


def registered_versions(session: Session) -> list[tuple[str, str]]:
    rows = session.execute(
        select(PromptRegistryEntry.prompt_id, PromptRegistryEntry.version)
    )
    return [(row[0], row[1]) for row in rows]
