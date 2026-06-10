"""Scoring output schema (`score_output_v1`) and strict parsing."""

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    supports: str = Field(min_length=1)


class RequirementsBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    met: list[str] = Field(default_factory=list)
    partial: list[str] = Field(default_factory=list)
    not_met: list[str] = Field(default_factory=list)


class ScoreOutput(BaseModel):
    """score_output_v1 — the only shape a scoring pass may take."""

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=10)
    band_descriptor_mapping: str = Field(min_length=1)
    justification: str = Field(min_length=1)
    citations: list[Citation]
    requirements: RequirementsBreakdown
    weaknesses: list[str] = Field(default_factory=list)
    injection_suspicion: bool


class OutputParseError(Exception):
    """The model output does not parse against score_output_v1."""


def parse_score_output(raw_text: str) -> ScoreOutput:
    """Parse a raw model response strictly against the schema."""
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise OutputParseError(f"The output is not valid JSON: {error}.") from error
    try:
        return ScoreOutput.model_validate(data)
    except ValidationError as error:
        raise OutputParseError(
            f"The output does not conform to score_output_v1: {error.error_count()} "
            "validation error(s)."
        ) from error
