# TenderScore — Engineering Instructions

You are building **TenderScore**: a two-tier AI bid-evaluation platform for UK public sector procurement teams. **AI scores, humans moderate, AI documents.** The product mechanises the moderation pack: AI produces recommended scores with band-descriptor justifications and verbatim evidence citations; named humans confirm or amend; the system generates the audit trail and standstill documentation by construction.

## Non-negotiable engineering rules

1. **The audit trail is the product.** Every state change emits an immutable `AuditEvent` via the audit middleware. No service writes state without one. The audit store is append-only and hash-chained — enforced at the database level (revoked UPDATE/DELETE + trigger), not by convention. If you find yourself writing code that mutates evaluation state without an audit event, stop: the design is wrong.
2. **Determinism and replayability.** Temperature 0 always. The exact model version string is pinned per procurement at framework-lock time and recorded on every scoring pass. Prompts are versioned, hashed artefacts from the prompt registry — never inline strings. All inputs are content-hashed. A scoring run must be replayable from the audit record.
3. **Isolation.** Per-tenant schema isolation in PostgreSQL. Per-question, per-bidder scoring contexts — one bidder's answer to one question per LLM call. **Never** put two bidders, or two questions, in one scoring prompt. Comparative scoring in a single prompt is permanently prohibited.
4. **Instruction/content separation.** Bidder text is data, never instruction. It is passed in a structurally separated content block, pre-scanned for injection patterns, truncated at the published word/page limit. Bidder text must never be interpolated into the system/instruction layer.
5. **Citations or nothing.** Every claim in a justification must cite a verbatim span from the bidder's answer with location. Citation validity is checked **deterministically in code** (string match against the hash-verified source), never by the LLM. A pass with any invalid citation is rejected, rerun and flagged.
6. **Variance is the moderation router.** 3 passes default, 5 for high-weighted questions. Variance within one band → converged recommendation. Variance beyond one band → escalate to human moderation, never auto-recommend.
7. **Safety is never paywalled.** Injection detection, audit trail, human-in-the-loop and pass/fail gate enforcement exist in both tiers and cannot be feature-flagged off.
8. **No cross-tenant learning.** Calibration examples are stored per tenant and never contain or transfer another tenant's bid content. No customer data is used for model training — assert this in the provider configuration and never weaken it.
9. **Permanently excluded — do not build, even as a stub:** automated award decisions; performance-prediction or reputation scoring; AI-authorship detection/penalties; evaluation against unpublished criteria; single-prompt comparative scoring.
10. **Compliance gates features.** When in doubt, the test is: "would this evaluation survive a standstill challenge under the Procurement Act 2023?" If a requested feature fails that test, flag it and stop rather than building it.

## Stack and conventions

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (typed, declarative), Alembic migrations, Pydantic v2. `ruff` + `mypy --strict` clean at all times.
- **Frontend:** React 18 + TypeScript (strict) + Vite. Plain REST + SSE for long-running jobs. WCAG 2.2 AA is a hard requirement — semantic HTML, keyboard navigation, tested with axe-core in CI.
- **Data:** PostgreSQL 16 (per-tenant schemas), object storage via S3 API (MinIO locally), Postgres-backed job queue for v1 (swap to managed queue at deploy).
- **LLM:** Anthropic API behind the `llm_gateway` abstraction only. No module calls a provider SDK directly. UK/EEA inference residency is a deployment constraint — keep it configurable, never hard-code endpoints.
- **Testing:** pytest; every module ships with tests; the synthetic-tender regression suite and the injection red-team suite must pass on every PR. Target: citation-validity rate ≥ 99.5% on the regression suite.
- **Language:** British English in all UI strings, documentation, error messages and generated documents. The UI voice is instructional, neutral, exact — e.g. "Recommended score: 3 (Good) — 4 citations — variance: converged (3 passes)". Never "AI magic".
- **Secrets:** environment variables only, `.env` git-ignored, no secrets in code or fixtures.
- **Commits:** small, conventional commits; migrations always reversible; never commit generated files or real tender data (none exists yet — all data is synthetic; keep it that way until the legal clearance and DPIA gates in the project plan are passed).

## Definition of done (per module)

Code + tests + audit events verified (the audit-completeness test asserts every state-changing endpoint emits events) + mypy/ruff clean + module README updated + listed in the milestone exit-criteria checklist.
