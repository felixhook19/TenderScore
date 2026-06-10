"""Split a submission into per-question responses.

Splitting is deterministic and anchored on question headings. When the
expected criterion refs are known (the framework usually exists before
submissions arrive), they anchor the match; otherwise a generic question
heading pattern applies.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionSection:
    criterion_ref: str
    text: str
    word_count: int


_GENERIC_HEADING = re.compile(
    r"^\s*(?:Question|Q)[\s.]*([0-9]+(?:\.[0-9]+)*[a-z]?)\s*[-\u2013:.)]?\s*$",
    re.IGNORECASE,
)


def _heading_for_refs(expected_refs: list[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(ref) for ref in sorted(expected_refs, key=len, reverse=True))
    return re.compile(
        rf"^\s*(?:Question|Q)?[\s.]*({alternatives})\s*[-\u2013:.)]?\s*$",
        re.IGNORECASE,
    )


def split_into_questions(
    text: str, expected_refs: list[str] | None = None
) -> list[QuestionSection]:
    """Split text into sections, one per detected question heading."""
    pattern = _heading_for_refs(expected_refs) if expected_refs else _GENERIC_HEADING

    sections: list[QuestionSection] = []
    current_ref: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_ref is None:
            return
        body = "\n".join(current_lines).strip()
        sections.append(
            QuestionSection(
                criterion_ref=current_ref,
                text=body,
                word_count=len(body.split()),
            )
        )

    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            flush()
            current_ref = match.group(1)
            current_lines = []
        elif current_ref is not None:
            current_lines.append(line)

    flush()
    return sections


def truncate_to_word_limit(text: str, word_limit: int | None) -> tuple[str, bool]:
    """Truncate at the published word limit; the limit is the boundary of
    what may be evaluated (CLAUDE.md rule 4). Returns (text, truncated?)."""
    if word_limit is None:
        return text, False
    words = text.split()
    if len(words) <= word_limit:
        return text, False
    return " ".join(words[:word_limit]), True
