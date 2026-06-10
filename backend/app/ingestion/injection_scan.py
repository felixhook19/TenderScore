"""Deterministic prompt-injection scanner (layer 1 of the defence in
`docs/architecture.md` Part E).

The scanner never blocks: a positive flags the response for human review,
because a false positive must not disadvantage a bidder — a human decides.
Patterns are organised in families; the red-team corpus in
`tests/redteam/corpus/` exercises every family in CI.
"""

import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width and direction-control characters used to smuggle instructions.
_SMUGGLING_CHARS = "​‌‍﻿⁠‪‫‬‭‮"

_PATTERN_FAMILIES: dict[str, list[str]] = {
    "instruction_override": [
        r"\bignore\s+(?:all|any|the|previous|prior|above|earlier)\b[^.\n]{0,40}\binstructions?\b",
        r"\bdisregard\b[^.\n]{0,40}\b(?:instructions?|rules?|guidance|descriptors?|criteria)\b",
        r"\bforget\s+(?:everything|all|your)\b[^.\n]{0,40}\b(?:instructions?|told)\b",
        r"\boverride\b[^.\n]{0,40}\b(?:instructions?|settings?|rules?)\b",
        r"\bnew\s+instructions?\s*(?::|follow)\b",
        r"\bdo\s+not\s+follow\b[^.\n]{0,40}\binstructions?\b",
    ],
    "role_pivot": [
        r"\byou\s+are\s+(?:now|no\s+longer)\b",
        r"\bact\s+as\s+(?:a|an|the)\b",
        r"\bpretend\s+(?:to\s+be|you\s+are)\b",
        r"\bassume\s+the\s+role\b",
        r"\bswitch\s+(?:to|into)\s+\w+\s+mode\b",
        r"\bjailbreak\b",
        r"\bdeveloper\s+mode\b",
        r"\bfrom\s+now\s+on\s+you\s+are\b",
    ],
    "score_manipulation": [
        r"\baward\b[^.\n]{0,40}\b(?:maximum|highest|top|full)\b",
        r"\bscore\s+(?:this|us|it)\b[^.\n]{0,30}\b(?:5|five|maximum|highest)\b",
        r"\bgive\s+(?:this|us|it)\b[^.\n]{0,30}\b(?:5|five|full\s+marks|top\s+score)\b",
        r"\bmust\s+(?:be\s+)?(?:scored?|rated?)\b[^.\n]{0,30}\b(?:5|five|excellent)\b",
        r"\bthis\s+(?:answer|response|bid)\s+(?:deserves|merits|warrants)\b[^.\n]{0,30}\b(?:5|five|maximum|highest|top)\b",
        r"\bas\s+the\s+evaluator\b[^.\n]{0,60}\b(?:you|score|award)\b",
    ],
    "prompt_probe": [
        r"\brepeat\s+(?:your|the)\s+(?:instructions?|prompt|system)\b",
        r"\bwhat\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions?)\b",
        r"\bprint\s+(?:your|the)\s+(?:prompt|instructions?)\b",
        r"\breveal\s+(?:your|the)\s+(?:prompt|instructions?|rules)\b",
    ],
    "delimiter_smuggling": [
        r"```\s*system",
        r"<\s*/?\s*system\s*>",
        r"\[\s*system\s*\]",
        r"<\|im_start\|>",
        r"<\|endoftext\|>",
        r"###\s*(?:system|instruction)",
        r"\{\{\s*system\s*\}\}",
    ],
    "markup_smuggling": [
        r"<script\b",
        r"<img\b[^>]*\bonerror\b",
        r"<!--[^>]{0,200}(?:instruction|ignore|score)[^>]{0,200}-->",
        r"\bjavascript\s*:",
    ],
}

_COMPILED: list[tuple[str, re.Pattern[str]]] = [
    (family, re.compile(pattern, re.IGNORECASE))
    for family, patterns in _PATTERN_FAMILIES.items()
    for pattern in patterns
]


@dataclass(frozen=True)
class ScanFinding:
    family: str
    excerpt: str


@dataclass(frozen=True)
class ScanResult:
    flagged: bool
    score: int
    findings: list[ScanFinding] = field(default_factory=list)

    def as_json(self) -> dict[str, object]:
        return {
            "flagged": self.flagged,
            "score": self.score,
            "findings": [
                {"family": finding.family, "excerpt": finding.excerpt}
                for finding in self.findings
            ],
        }


def _normalise(text: str) -> str:
    """Defeat smuggling tricks before matching: strip zero-width and
    direction-control characters, fold compatibility forms (homoglyph
    families), lower-case."""
    cleaned = "".join(char for char in text if char not in _SMUGGLING_CHARS)
    return unicodedata.normalize("NFKC", cleaned)


def scan_text(text: str) -> ScanResult:
    """Scan bidder text for known injection patterns. Deterministic."""
    findings: list[ScanFinding] = []

    smuggling_count = sum(1 for char in text if char in _SMUGGLING_CHARS)
    # A single direction-override character is already an active reordering
    # of how the text reads; zero-width characters need a small cluster.
    direction_overrides = sum(1 for char in text if char in "‭‮⁦⁧⁨")
    if smuggling_count >= 3 or direction_overrides >= 1:
        findings.append(
            ScanFinding(
                family="unicode_smuggling",
                excerpt=f"{smuggling_count} zero-width or direction-control characters",
            )
        )

    normalised = _normalise(text)
    for family, pattern in _COMPILED:
        match = pattern.search(normalised)
        if match:
            start = max(0, match.start() - 30)
            end = min(len(normalised), match.end() + 30)
            findings.append(ScanFinding(family=family, excerpt=normalised[start:end].strip()))

    return ScanResult(flagged=bool(findings), score=len(findings), findings=findings)
