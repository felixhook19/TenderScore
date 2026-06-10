# Milestone exit-criteria checklist

Tracks M0–M10 per `docs/architecture.md` Part I. Evidence is the named
test(s) or a demonstrated run; everything below runs in CI on every PR.

## M0 — Scaffold ✓ (confirmed 2026-06-10)
- [x] `make dev` boots db, minio, api, worker, web; health endpoint returns
- [x] `make test` green; CI workflow on PR; ADR-001

## M1 — Tenancy, auth, audit spine ✓ (confirmed 2026-06-10)
- [x] Audit-completeness test; DB-level UPDATE/DELETE rejection; tamper
      detection (`test_audit_*`); schema-per-tenant provisioning; dev
      IdentityProvider + TOTP; RBAC + distinct privilege; ADR-002

## M2 — Ingestion ✓
- [x] Synthetic submission round-trips byte-identical (`test_ingestion.py`)
- [x] Hashes stable across re-ingestion
- [x] All five seeded injection attempts flagged; clean bidder unflagged

## M3 — Framework service ✓
- [x] Post-lock edits rejected (409) and audited (`framework.edit_rejected`)
- [x] A locked framework reproduces its hash (`test_framework.py`)
- [x] Lots and criteria tree (sub-criteria) first-class; LLM-assisted
      extraction draft endpoint (human edits before locking)

## M4 — LLM gateway + prompt registry ✓
- [x] Unregistered prompt, wrong model version and tainted-instruction
      calls rejected with audited refusals (`test_gateway.py`,
      `test_registry.py`)
- [x] Changed prompt artefact without version bump fails startup
- [x] Registered calls succeed and are recorded with prompt id/version/hash

## M5 — Scoring engine ✓
- [x] Full synthetic procurement scores end-to-end
      (`tests/regression/test_synthetic_tender.py`)
- [x] Replay from the record reproduces identical validated outputs
- [x] Citation validity ≥ 99.5% (currently 100%)
- [x] Variance routing: converged/moderate/escalate; 3/5 passes by weight
- [x] Calibration gate blocks until benchmarks reviewed
- [ ] `[[HUMAN INPUT NEEDED: Felix to author/review the oracle scores —
      the committed oracle is a placeholder]]`

## M6 — Compliance + anonymisation ✓
- [x] Gate failure blocks the bidder's remaining runs, audited
- [x] Anonymised text contains no seeded identifiers
      (`test_anonymisation.py`)
- [x] Every map access individually audited; reveal needs the distinct
      privilege

## M7 — Moderation workflow + UI ✓
- [x] Tiered queue (escalated first); confirm/amend with mandatory
      rationale on amend (service + DB constraint)
- [x] Every decision audited (completeness walk)
- [x] axe-core clean on every view; semantic HTML and labelled controls
- [ ] Manual keyboard-only run-through against the live stack — scripted in
      `frontend/README.md`, to be performed by a human reviewer

## M8 — Document generation ✓
- [x] Pack generated only from the moderation record; the completeness walk
      asserts every paragraph derives from recorded fields
- [x] Versioned, stored, hashed (docx and pdf)

## M9 — Red-team + regression hardening ✓
- [x] Corpus at 54 variants across 7 families; zero score-shifting or
      instruction-altering successes (`tests/redteam/`)
- [x] Order-sensitivity deterministic and replayable
- [x] Variance distribution documented (`docs/variance-report.md`)

## M10 — Pre-pilot hardening ✓
- [x] Rate limiting on auth endpoints; account lockout; logout; session
      revocation (`test_hardening.py`)
- [x] Log scrubbing installed at startup
- [x] Backup/restore runbook; pen-test prep checklist
- [x] OWASP ASVS L2 self-assessment with named gaps
      (`docs/security/asvs-l2-self-assessment.md`)

## Out of scope (P7 — not built, by design)
Tier 2 / Assure: consistency engine, claims verification, commercial/ALT,
clarifications, standstill generation, Submission Integrity Analysis, SME
reporting. Data structures leave migration headroom; nothing precludes them.
