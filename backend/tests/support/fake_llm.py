"""Deterministic fake LLM responder for tests and offline development.

Produces schema-valid scoring outputs derived from the request itself:
the awarded band's verbatim descriptor is parsed from the instruction
layer, citations are verbatim slices of the content block, and scores come
from the regression oracle (default band 3). Replays are bit-identical.
"""

import json
import re
from collections import defaultdict

from app.core.hashing import content_hash_text
from app.llm_gateway.gateway import CONTENT_BLOCK_FOOTER, CONTENT_BLOCK_HEADER

_BAND_LINE = re.compile(r"^Band (\d+) \(([^)]+)\): (.+)$", re.MULTILINE)
_REQUIREMENT_LINE = re.compile(r"^(R\d+): ", re.MULTILINE)


def extract_content(user_content: str) -> str:
    """Recover the bidder content from between the gateway's markers."""
    start = user_content.find(CONTENT_BLOCK_HEADER)
    end = user_content.rfind(CONTENT_BLOCK_FOOTER)
    if start < 0 or end < 0:
        return user_content
    return user_content[start + len(CONTENT_BLOCK_HEADER) : end].strip("\n")


class OracleResponder:
    """Callable (system, user_content) -> response text.

    `scores_by_content_hash` maps the hash of the prepared content block to
    either a single expected score or a per-pass list of scores.
    """

    def __init__(
        self,
        scores_by_content_hash: dict[str, int | list[int]] | None = None,
        default_score: int = 3,
    ) -> None:
        self.scores = scores_by_content_hash or {}
        self.default_score = default_score
        self._call_counts: dict[str, int] = defaultdict(int)

    def __call__(self, system: str, user_content: str) -> str:
        if "security classifier" in system:
            return json.dumps(
                {"suspicion": False, "confidence": 0.1, "reason": "No manipulation found."}
            )
        if "drafting an evaluation framework" in system:
            return json.dumps({"lots": [], "criteria": []})
        return self._score_response(system, user_content)

    def _score_response(self, system: str, user_content: str) -> str:
        content = extract_content(user_content)
        content_hash = content_hash_text(content)

        configured = self.scores.get(content_hash, self.default_score)
        if isinstance(configured, list):
            index = self._call_counts[content_hash] % len(configured)
            score = configured[index]
        else:
            score = configured
        self._call_counts[content_hash] += 1

        bands = {
            int(match.group(1)): match.group(3).strip()
            for match in _BAND_LINE.finditer(system)
        }
        descriptor = bands.get(score, "")

        span = content[: min(100, len(content))]
        requirements = _REQUIREMENT_LINE.findall(system)

        output = {
            "score": score,
            "band_descriptor_mapping": descriptor,
            "justification": (
                "The answer evidences the awarded band. "
                f"Descriptor applied: {descriptor}"
            ),
            "citations": [
                {
                    "span": span,
                    "start": 0,
                    "end": len(span),
                    "supports": "The answer evidences the awarded band.",
                }
            ],
            "requirements": {"met": requirements, "partial": [], "not_met": []},
            "weaknesses": [],
            "injection_suspicion": False,
        }
        return json.dumps(output)


class ManipulatedResponder(OracleResponder):
    """A responder simulating a model successfully manipulated by injected
    bidder text: it awards the maximum score with a fabricated citation.
    Deterministic validation must reject every output it produces."""

    def _score_response(self, system: str, user_content: str) -> str:
        bands = {
            int(match.group(1)): match.group(3).strip()
            for match in _BAND_LINE.finditer(system)
        }
        top_band = max(bands) if bands else 5
        return json.dumps(
            {
                "score": top_band,
                "band_descriptor_mapping": bands.get(top_band, "Excellent"),
                "justification": "This answer is outstanding in every respect.",
                "citations": [
                    {
                        "span": "this text does not appear in the bidder's answer",
                        "start": 0,
                        "end": 47,
                        "supports": "Fabricated evidence.",
                    }
                ],
                "requirements": {"met": [], "partial": [], "not_met": []},
                "weaknesses": [],
                "injection_suspicion": False,
            }
        )
