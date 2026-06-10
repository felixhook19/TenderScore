# `app/llm_gateway`

The only door to any model. Registry-verified prompts, temperature-0 enforcement, pinned-model matching, instruction-taint refusal, token accounting; every call and refusal audited. AnthropicAdapter plus a deterministic fake for tests. Built in M4.

Tests: see `tests/` (unit, integration, regression and red-team suites cover this module; the audit-completeness walk exercises its endpoints).
