# TenderScore — Technical Architecture & Claude Code Build Kit
**Version:** v1 · June 2026 · **Phase:** P2 (architecture & security design), producing the P3 build kickoff kit
**Audience:** Claude Code (and any contracted engineer). This document is structured so Part A can be pasted directly into the repository root as `CLAUDE.md`, and Parts B–L are the architecture specification Claude Code works from.

> **⚠ BLOCKING ITEM — read before running anything.** Open Decision #1 (employment IP/non-compete review against Felix's Investigo contract) is **not cleared**. Until it is, treat all code produced from this kit as **pre-clearance preparation**: local development only, no deployment, no public repository, no company branding, no customer contact. The architecture and synthetic-data work below is structured so nothing depends on that clearance — but the clearance gates everything beyond it. `[[LEGAL REVIEW NEEDED — blocking]]`

---

## PART A — `CLAUDE.md` (paste verbatim into the repository root)

---START CLAUDE.MD---

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

---END CLAUDE.MD---

---

## PART B — Stack decisions and rationale

| Layer | Choice | Rationale | Status |
|---|---|---|---|
| API | Python 3.12 + FastAPI | LLM-ecosystem maturity, typed, async, SSE support | Fixed (handover §3.2) |
| ORM/migrations | SQLAlchemy 2.0 + Alembic | Boring, auditable, per-schema tenancy support | Fixed |
| Frontend | React 18 + TypeScript + Vite | Fixed in handover; SPA is sufficient — no SEO need behind login | Fixed |
| Database | PostgreSQL 16, schema-per-tenant | Isolation without operational sprawl; upgrade path to database-per-tenant for enterprise | Fixed |
| Object storage | S3-compatible API (MinIO in dev) | Encrypted originals; portable across AWS/Azure (Open Decision #4 unresolved) | `[[ASSUMED]]` |
| Queue | Postgres-backed job table + worker process (e.g. `procrastinate` or hand-rolled `FOR UPDATE SKIP LOCKED`) | One less moving part locally; identical semantics to SQS/Cloud Tasks; swap at deploy | `[[ASSUMED — revisit at P4]]` |
| LLM | Anthropic Claude API via `llm_gateway` | Fixed in handover; second provider certifiable later through the same interface | Fixed |
| Auth (dev) | Email + password + TOTP, with an `IdentityProvider` interface | Entra ID SSO is the production target (ICP runs it) but needs a tenant; interface now, SSO at P4 | `[[ASSUMED]]` |
| IaC | Terraform skeleton **deferred** | Cloud provider is Open Decision #4 — do not pre-empt it. Docker Compose is the only infrastructure until decided | Deferred |
| Local dev | Docker Compose: `db`, `minio`, `api`, `worker`, `web` | Reproducible from clone in one command | Fixed |

**What is deliberately not chosen yet:** cloud provider (Open Decision #4), SSO tenant, managed queue, monitoring stack. The architecture isolates all four behind interfaces or deployment config so the build is not blocked.

---

## PART C — Repository layout (monorepo)

```
tenderscore/
├── CLAUDE.md                      # Part A above
├── docker-compose.yml
├── Makefile                       # make dev / test / lint / redteam / regression
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py                # FastAPI app factory
│   │   ├── core/                  # config, security, tenancy resolution
│   │   ├── audit/                 # event schema, middleware, hash chain, verifier
│   │   ├── auth/                  # IdentityProvider interface, dev provider, RBAC
│   │   ├── tenancy/               # tenant lifecycle, schema provisioning
│   │   ├── ingestion/             # upload, parse (pdf/docx), split, normalise, hash
│   │   ├── framework/             # procurement, lots, criteria tree, descriptors, lock
│   │   ├── compliance/            # limits, gates, caveats, attachment checks
│   │   ├── anonymisation/         # NER + rules, token mapping, privileged access
│   │   ├── llm_gateway/           # provider abstraction, prompt registry, injection scan,
│   │   │                          #   token accounting, model-version pinning
│   │   ├── scoring/               # orchestrator, passes, citation validator, variance
│   │   ├── moderation/            # tiering, confirm/amend workflow, moderation packs
│   │   ├── documents/             # pack & summary generation (docx/pdf out)
│   │   └── jobs/                  # queue, worker entrypoint
│   ├── prompts/                   # versioned YAML prompt artefacts (see Part E)
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── regression/            # synthetic tender suite + expected scores
│       └── redteam/               # injection attack corpus + assertions
├── frontend/
│   ├── src/
│   │   ├── app/                   # routing, auth shell
│   │   ├── features/              # framework, submissions, scoring, moderation, admin
│   │   ├── components/            # design system (WCAG 2.2 AA)
│   │   └── api/                   # typed client generated from OpenAPI
│   └── tests/                     # vitest + axe-core accessibility checks
└── docs/
    ├── architecture.md            # Parts B–H of this kit, kept current
    ├── adr/                       # architecture decision records (ADR-001 onwards)
    └── runbooks/
```

---

## PART D — Data model (core DDL intent)

Per-tenant schema; `audit_events` and `prompt_registry` live in a shared `platform` schema with tenant scoping. Lots and sub-criteria are **first-class** (v2 instruction — pulled into V1). Types abbreviated; Claude Code derives full Alembic migrations from this.

```sql
-- Tenancy & identity (platform schema)
tenants(id, name, schema_name, created_at, status)
users(id, tenant_id, email, display_name, totp_secret, status)
roles: admin | procurement_lead | evaluator | moderator | observer_auditor
user_roles(user_id, role, tenant_id)
-- anonymisation-map access is a distinct grant, not implied by any role:
privileges(user_id, privilege)            -- e.g. 'anonymisation_map.read'

-- Procurement & framework (tenant schema)
procurements(id, title, reference, regime ENUM('PA23','PCR15'), status,
             pinned_model_version, framework_locked_at, framework_lock_hash)
lots(id, procurement_id, lot_number, title)                 -- first-class
criteria(id, procurement_id, lot_id NULL, parent_id NULL,   -- tree: criterion → sub-criteria
         ref, title, weighting_pct, is_gate BOOL,
         gate_rule JSONB NULL,            -- e.g. {"type":"min_score","value":2}
         word_limit INT NULL, page_limit INT NULL,
         price_criterion BOOL DEFAULT FALSE)
band_descriptors(id, criterion_id, band INT, label, descriptor_text)  -- verbatim, locked
spec_requirements(id, criterion_id, ref, text)
framework_lock_events(...)                -- lock = hash of full criteria tree + descriptors
                                          --        + pinned model version; immutable after

-- Bidders & submissions
bidders(id, procurement_id, legal_name, companies_house_no NULL)   -- restricted table
anonymisation_map(bidder_id, token)       -- 'Bidder A'… ; every read audited
submissions(id, procurement_id, bidder_id, lot_id NULL, received_at,
            original_object_key, content_hash)
question_responses(id, submission_id, criterion_id, text, content_hash,
                   word_count, attachments JSONB,
                   compliance_status ENUM('compliant','non_compliant','caveat_flagged'),
                   injection_scan JSONB)  -- {score, patterns[], llm_flag}

-- Scoring
scoring_runs(id, procurement_id, criterion_id, bidder_id, status,
             pass_count_target, model_version, prompt_id, prompt_version, prompt_hash,
             created_by, created_at)
scoring_passes(id, run_id, pass_number, raw_output JSONB, validated BOOL,
               validation_failures JSONB, score INT NULL,
               injection_suspicion BOOL, latency_ms, tokens_in, tokens_out)
recommendations(id, run_id, score INT, band_label,
                justification TEXT, citations JSONB,   -- [{span, start, end, verified}]
                requirements JSONB,                    -- {met[],partial[],not_met[]}
                weaknesses JSONB, variance INT,
                confidence_tier ENUM('converged','moderate','escalate'))

-- Moderation
moderation_decisions(id, recommendation_id, action ENUM('confirm','amend'),
                     final_score INT, rationale TEXT,   -- mandatory on amend
                     decided_by, decided_at)
moderation_packs(id, procurement_id, version, object_key, generated_at)

-- Audit (platform schema, append-only)
audit_events(id BIGSERIAL, tenant_id, actor_id NULL, actor_type ENUM('user','system'),
             action, entity_type, entity_id,
             before_hash NULL, after_hash NULL,
             prompt_id NULL, prompt_version NULL, model_version NULL,
             occurred_at TIMESTAMPTZ, prev_event_hash, event_hash)
-- Enforcement: REVOKE UPDATE, DELETE ON audit_events FROM app_role;
-- BEFORE UPDATE OR DELETE trigger → RAISE EXCEPTION;
-- event_hash = sha256(prev_event_hash || canonical_json(event)) — verifier job re-walks chain.

-- Prompt registry (platform schema)
prompt_registry(prompt_id, version, sha256_hash, purpose, file_path, released_at, released_by)

-- Jobs
jobs(id, tenant_id, type, payload JSONB, status, attempts, locked_by, locked_at,
     scheduled_at, completed_at, error TEXT)
```

**Tier 2 entities (claims, clarifications, calibration_examples, consistency_flags) are designed but not built in P3** — leave migration headroom (no conflicting names), do not implement.

---

## PART E — LLM gateway and prompt registry

**Gateway interface (the only door to any model):**

```python
class LLMGateway(Protocol):
    async def score(
        self,
        prompt: RegisteredPrompt,        # id, version, hash — resolved from registry
        instruction_vars: dict,          # locked descriptors, spec requirements, schema
        content_block: ScannedContent,   # bidder text: scanned, truncated, hashed
        model_version: str,              # the procurement's pinned version — mandatory
        temperature: float = 0.0,        # the only permitted value in scoring paths
    ) -> GatewayResult: ...              # raw output + token counts + latency + request hash
```

Rules enforced *inside* the gateway, not by callers:
- Rejects any call whose `model_version` does not match the procurement's pinned version.
- Rejects any call where bidder content appears in `instruction_vars` (taint check: content hash must not appear in the rendered instruction layer).
- Rejects unregistered or hash-mismatched prompts.
- Records every call as an `AuditEvent` with prompt ID/version/hash, model version, input content hashes and token counts.
- Provider adapters: `AnthropicAdapter` first; the interface is provider-neutral so an Azure OpenAI UK adapter can be certified later without touching callers.
- No streaming in scoring paths (whole-response validation required); SSE to the UI is driven by job status, not token streams.

**Prompt registry:** prompts live as YAML artefacts in `backend/prompts/`, e.g.:

```yaml
id: score_question_v1
version: 1.3.0
purpose: per-question, per-bidder recommended scoring
output_schema: score_output_v1        # JSON Schema, also versioned
instruction_template: |
  You are scoring one bidder's answer to one question in a UK public
  procurement. Score strictly against the band descriptors below. ...
  Every claim in your justification must cite a verbatim span from the
  answer with character offsets. Uncited claims invalidate the output.
  Never compare with other bidders. Never reward style over evidence.
```

On application start, files are hashed and reconciled against `prompt_registry`; a changed file without a version bump fails startup. Prompt changes go through PR review + the red-team and regression suites — **prompts are code**.

**Injection scanning (ingest-time, layered):**
1. Deterministic pattern layer — known injection markers (role-play pivots, "ignore previous instructions" families, system-prompt probes, unicode/homoglyph smuggling, markdown/HTML instruction smuggling). Corpus lives in `tests/redteam/corpus/` and doubles as the CI attack set.
2. LLM classifier pass (separate prompt, separate call, also registry-managed) producing a suspicion score.
3. Self-report: the scoring output schema includes `injection_suspicion: bool`.
4. Deterministic validation (Part F) catches descriptor-inconsistent outputs regardless.
Any positive at layers 1–3 flags the response for human review; it never silently blocks (a false positive must not disadvantage a bidder — a human decides).

---

## PART F — Scoring engine specification

**Call structure (per question, per bidder, per pass):**
- *Instruction layer:* role; the locked band descriptors **verbatim**; relevant spec requirements (order randomised per pass to expose order sensitivity); output JSON schema; citation rules.
- *Content layer (structurally separated):* the bidder's answer to this question only — pre-scanned, truncated at the published limit, hash-verified.

**Output schema (`score_output_v1`):**

```json
{
  "score": 3,
  "band_descriptor_mapping": "Fully meets the requirement with adequate detail...",
  "justification": "…",
  "citations": [{"span": "verbatim text", "start": 1042, "end": 1131, "supports": "claim ref"}],
  "requirements": {"met": ["R1","R3"], "partial": ["R2"], "not_met": ["R4"]},
  "weaknesses": ["…"],
  "injection_suspicion": false
}
```

**Deterministic validation layer (code, never LLM) — a pass fails if any check fails:**
1. Output parses against the JSON Schema.
2. Every citation span exists verbatim in the hash-verified source at (or near, with exact-match fallback scan) the stated offsets.
3. Score is a valid band for this criterion.
4. Justification vocabulary maps to the descriptor vocabulary for the awarded band (lexical overlap threshold against descriptor text; misses flag, not fail, in v1 — tune with calibration data).
5. Every justification claim is linked to ≥1 verified citation.
Failed pass → rejected, rerun once, flag if it fails again. Rejection reasons stored on the pass and audited.

**Multi-pass protocol:** 3 passes default; 5 where criterion weighting ≥ the configurable high-weight threshold (default 15%). Temperature 0. Variance = max(score) − min(score) across validated passes. Variance ≤ 1 band → recommendation at the modal score, `confidence_tier` per tier rules; variance > 1 band → `escalate`, no recommended score is auto-presented.

**Calibration gate:** before live scoring on a procurement, the buyer scores 2–3 benchmark answers in-product; the engine scores the same answers; divergence beyond one band on any benchmark **blocks the run** until a procurement lead reviews and either adjusts the framework lock (pre-lock only) or records an accepted-divergence rationale (audited).

---

## PART G — API surface (v1, illustrative)

```
POST   /auth/login · /auth/totp                      GET /me
POST   /procurements                                 GET /procurements/{id}
POST   /procurements/{id}/lots
POST   /procurements/{id}/criteria                   (tree ops; blocked after lock)
POST   /procurements/{id}/framework/extract          (LLM-assisted draft — human edits)
POST   /procurements/{id}/framework/lock             (hashes tree, pins model version)
POST   /procurements/{id}/bidders                    POST /bidders/{id}/submissions
POST   /submissions/{id}/ingest                      (parse, split, hash, scan — job)
GET    /procurements/{id}/compliance                 (limits, gates, attachments, caveats)
POST   /procurements/{id}/scoring/runs               (enqueue per-question×bidder runs)
GET    /scoring/runs/{id}  · SSE /scoring/stream
GET    /procurements/{id}/moderation/queue           (tiered: converged → escalated)
POST   /recommendations/{id}/moderate                (confirm/amend + mandatory rationale)
POST   /procurements/{id}/packs/moderation           (generate pack — job)
GET    /audit/events?entity=…                        (observer/auditor role)
GET    /audit/verify                                 (hash-chain verification report)
```

All endpoints tenant-scoped by the tenancy middleware; all mutating endpoints emit audit events via the audit middleware — both are app-level middleware, not per-endpoint opt-ins.

---

## PART H — Security baseline for the build phase

- **AuthZ:** RBAC roles per Part D; anonymisation-map reads require the distinct privilege and are individually audited. Default-deny route guards.
- **Crypto:** TLS termination assumed at deploy; AES-256 at rest via storage layer; per-tenant envelope keys designed in (`tenant_keys` table + KMS interface, dev implementation = local key file, production = cloud KMS once Open Decision #4 lands).
- **Data hygiene:** synthetic data only until DPIA + CE+ + legal clearance (P4/P5 gates). The repo's fixtures must never contain real bidder or buyer material — this also enforces Hard Rule 7 (no Investigo or client documents, ever).
- **Dependency posture:** lockfiles committed, `pip-audit`/`npm audit` in CI, Dependabot-equivalent weekly.
- **No-training guarantee:** provider adapter sets the appropriate API controls; assert in config tests so a misconfiguration fails CI. `[[LEGAL REVIEW NEEDED at P5: mirror in DPA wording]]`
- **Residency:** all provider endpoints/regions are config, with a startup assertion that refuses non-UK/EEA endpoints in any environment flagged `production`.

---

## PART I — Build order for Claude Code (milestones with exit criteria)

Work strictly in order; each milestone is a PR series with its exit criteria demonstrated by tests.

| # | Milestone | Scope | Exit criteria |
|---|---|---|---|
| M0 | Scaffold | Monorepo, Docker Compose (db/minio/api/worker/web), CI (ruff, mypy --strict, pytest, vitest, axe-core), Makefile, CLAUDE.md, ADR-001 (stack) | `make dev` boots; `make test` green; health endpoint |
| M1 | Tenancy, auth, audit spine | Tenant provisioning (schema-per-tenant), dev IdentityProvider + TOTP, RBAC, audit middleware + append-only store + hash chain + verifier | Audit-completeness test passes; UPDATE/DELETE on audit_events provably impossible; chain verifier detects tampering in test |
| M2 | Ingestion | Upload to object storage, PDF/DOCX parse, split to question responses, content hashing, injection pattern scan | Synthetic submission round-trips; hashes stable; scan flags seeded attacks |
| M3 | Framework service | Procurements, **lots**, criteria tree (sub-criteria), descriptors, gates, limits; framework lock (hash + model-version pin); LLM-assisted extraction draft | Lock immutability enforced; post-lock edits rejected and audited |
| M4 | LLM gateway + prompt registry | Gateway per Part E, Anthropic adapter, registry load/reconcile, taint check, token accounting | Unregistered prompt, wrong model version and tainted instruction calls all rejected with audited refusals |
| M5 | Scoring engine | Orchestrator jobs (per question × bidder), multi-pass at temp 0, deterministic validation incl. citation matcher, variance routing, calibration gate | Full synthetic procurement scores end-to-end; replay from audit record reproduces identical validated outputs; citation validity ≥ 99.5% on regression suite |
| M6 | Compliance + anonymisation | Word/page limits, attachment checks, caveat detection, gate enforcement; NER+rules anonymiser, token mapping, privileged reveal | Gate failures block scoring of failed bidders; anonymised text contains no seeded identifiers; every map access audited |
| M7 | Moderation workflow + UI | Tiered queue, confirm/amend with mandatory rationale, side-by-side descriptor view, evaluator/moderator UI | A moderator completes a full synthetic moderation; every decision audited; WCAG 2.2 AA (axe-core clean + keyboard run-through) |
| M8 | Document generation | Moderation pack (docx/pdf) generated from the record; versioned, stored, hashed | Pack content provably derived only from moderation record fields |
| M9 | Red-team + regression hardening | Expand injection corpus (≥50 attack variants), order-sensitivity tests, descriptor-vocabulary tuning | Red-team suite green in CI; documented variance distribution on synthetic suite |
| M10 | Pre-pilot hardening | Pen-test prep checklist, rate limiting, session hardening, backup/restore runbook, log scrubbing | Runbooks exist; OWASP ASVS L2 self-assessment documented |

**Maps to project phases:** M0–M1 ≈ P2; M2–M8 ≈ P3 (Evaluate tier complete); M9–M10 ≈ P3 exit / P4 entry. Tier 2 modules (consistency engine, claims verification, commercial/ALT, clarifications, standstill generation, Submission Integrity Analysis, SME reporting) are **P7 — do not build yet**, but M3/M5 data structures must not preclude them.

---

## PART J — Quality gates (CI, every PR)

1. `ruff` + `mypy --strict` + `tsc --noEmit` clean.
2. Unit + integration tests green; coverage floor 85% on `audit/`, `llm_gateway/`, `scoring/` (the legally load-bearing modules).
3. **Synthetic tender regression suite:** known-correct scores within tolerance; citation-validity ≥ 99.5%.
4. **Injection red-team suite:** zero successful manipulations (a "success" = any attack that shifts a score or passes validation while altering instructions).
5. **Audit-completeness test:** walks every mutating route, asserts ≥1 audit event per state change, then verifies the hash chain.
6. **Accessibility:** axe-core zero violations on changed frontend routes (WCAG 2.2 AA).
7. No real data check: fixture linter rejects files containing seeded "real-data" markers, Companies House numbers not on the synthetic allowlist, or common PII patterns.

---

## PART K — Synthetic test data specification

Build one full synthetic procurement as the canonical fixture (`tests/regression/fixtures/synthetic_tender_01/`):
- A fictional district council tendering "Grounds Maintenance Services", 2 lots, 6 quality criteria (two with sub-criteria), 0–5 band descriptors per Part 2.3 of the legal reference, one pass/fail gate (safety, min score 2), 60/40 quality/price.
- 4 fictional bidders: one strong, one mid, one weak, one that fails the gate; one bidder's responses seeded with 5 injection attempts of escalating subtlety.
- Hand-written expected scores + rationales (the regression oracle), agreed by Felix as domain reviewer `[[HUMAN INPUT NEEDED: Felix to review/author the oracle scores — this is genuinely his domain expertise and the calibration anchor]]`.
- All names, numbers and content invented; no resemblance to real bids (Hard Rule 7).

---

## PART L — Kickoff prompt to paste into Claude Code

> Read `CLAUDE.md` and `docs/architecture.md` in full before writing anything. Then execute **Milestone M0** from Part I of the architecture document: scaffold the monorepo exactly per Part C, with Docker Compose (postgres 16, minio, api, worker, web), FastAPI app factory with health endpoint, React+TS+Vite shell, CI pipeline (ruff, mypy --strict, pytest, vitest, axe-core), Makefile (`dev`, `test`, `lint`, `regression`, `redteam` targets — the last two may be empty stubs that fail loudly if no tests exist), and ADR-001 recording the stack decisions. Do not build any business logic yet. Do not add any cloud provider configuration — that decision is open. When M0's exit criteria pass, stop and report before starting M1.

---

## Done / In progress / Missing / Assumed

**Done:** Paste-ready `CLAUDE.md` encoding all non-negotiable engineering rules; stack decisions with open items isolated behind interfaces; full repository layout; DDL-level data model with Lots/sub-criteria first-class and database-enforced append-only audit chain; LLM gateway and prompt-registry specification with in-gateway rule enforcement; scoring engine spec (call structure, output schema, deterministic validation, multi-pass/variance protocol, calibration gate); v1 API surface; build-phase security baseline; M0–M10 milestone plan with exit criteria mapped to project phases; CI quality gates; synthetic-data specification; literal Claude Code kickoff prompt.

**In progress:** Nothing — v1 complete as a build kit. The living copy belongs in `docs/architecture.md` and evolves by ADR.

**Missing (human-owned):** Employment IP/non-compete clearance (**blocking** — local synthetic-data development is the maximum safe activity until cleared); resourcing decision (Open Decision #2 — this kit assumes Claude Code plus Felix's review, but M7's UI and M10's hardening will benefit from an engineer's eyes before pilots); cloud provider choice (Open Decision #4 — Terraform deliberately deferred); Felix's authorship/review of the synthetic oracle scores (Part K); Anthropic API key and confirmation of current UK/EEA inference residency options at build time (verify, don't assume).

**Assumed (labelled in-text):** Postgres-backed queue for v1; MinIO/S3-compatible storage pending provider choice; dev-grade email+TOTP auth with Entra ID SSO deferred to P4; 15% as the high-weighting threshold for 5-pass scoring; OWASP ASVS L2 as the pre-pilot hardening bar.
