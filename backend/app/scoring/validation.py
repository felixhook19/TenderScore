"""Deterministic validation of scoring outputs — code, never the LLM.

A pass fails when any check fails:
1. The output parses against the schema (see `schema.py`).
2. Every citation span exists verbatim in the hash-verified source, at the
   stated offsets or located by exact-match fallback scan.
3. The score is a valid band for the criterion.
4. The band_descriptor_mapping is the verbatim descriptor of the awarded band.
5. Every justification has at least one verified citation.
Vocabulary checks (descriptor lexical overlap) flag rather than fail in v1.
"""

import re
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.scoring.schema import OutputParseError, ScoreOutput, parse_score_output

_WORD = re.compile(r"[a-z']+")

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have if in into is it of on or "
    "that the their there these this to was were will with would".split()
)


@dataclass(frozen=True)
class ValidatedCitation:
    span: str
    start: int
    end: int
    supports: str
    verified: bool
    offset_corrected: bool


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    output: ScoreOutput | None
    failures: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    citations: list[ValidatedCitation] = field(default_factory=list)


def _tokens(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS}


def validate_citation(source: str, span: str, start: int, end: int) -> ValidatedCitation:
    """Check one citation against the hash-verified source, in code."""
    if source[start:end] == span:
        return ValidatedCitation(span, start, end, "", True, False)
    located = source.find(span)
    if located >= 0:
        return ValidatedCitation(span, located, located + len(span), "", True, True)
    return ValidatedCitation(span, start, end, "", False, False)


def validate_pass(
    raw_text: str,
    *,
    source_text: str,
    valid_bands: dict[int, str],
) -> ValidationResult:
    """Validate one scoring pass output. `valid_bands` maps band number to
    the verbatim descriptor text for the criterion."""
    failures: list[str] = []
    flags: list[str] = []

    try:
        output = parse_score_output(raw_text)
    except OutputParseError as error:
        return ValidationResult(valid=False, output=None, failures=[str(error)])

    if output.score not in valid_bands:
        failures.append(
            f"Score {output.score} is not a valid band for this criterion."
        )

    citations: list[ValidatedCitation] = []
    for citation in output.citations:
        checked = validate_citation(source_text, citation.span, citation.start, citation.end)
        checked = ValidatedCitation(
            span=checked.span,
            start=checked.start,
            end=checked.end,
            supports=citation.supports,
            verified=checked.verified,
            offset_corrected=checked.offset_corrected,
        )
        citations.append(checked)
        if not checked.verified:
            failures.append(
                "A citation span does not exist verbatim in the bidder's answer: "
                f"'{citation.span[:80]}'."
            )
        elif checked.offset_corrected:
            flags.append("A citation's offsets were corrected by exact-match scan.")

    if not output.citations:
        failures.append("The justification has no citations; uncited claims are invalid.")

    if output.score in valid_bands:
        descriptor = valid_bands[output.score]
        if output.band_descriptor_mapping.strip() != descriptor.strip():
            failures.append(
                "band_descriptor_mapping is not the verbatim descriptor of the "
                "awarded band."
            )
        overlap_threshold = get_settings().descriptor_vocabulary_overlap_threshold
        descriptor_tokens = _tokens(descriptor)
        if descriptor_tokens:
            overlap = len(_tokens(output.justification) & descriptor_tokens) / len(
                descriptor_tokens
            )
            if overlap < overlap_threshold:
                flags.append(
                    "The justification vocabulary overlaps weakly with the awarded "
                    f"band's descriptor (overlap {overlap:.2f})."
                )

    return ValidationResult(
        valid=not failures,
        output=output,
        failures=failures,
        flags=flags,
        citations=citations,
    )
