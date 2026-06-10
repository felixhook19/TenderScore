# TenderScore (working name)

**Private repository — pre-clearance preparation only.**

Two-tier AI bid evaluation platform for UK public sector procurement teams.
AI scores, humans moderate, AI documents.

> **⚠ Blocking item:** the employment IP/non-compete review is not yet cleared.
> Until it is: this repository stays private, runs locally on synthetic data only,
> is not deployed, not branded, and not shared. See `docs/architecture.md`.

## Start here

1. Read `CLAUDE.md` — the binding engineering rules.
2. Read `docs/architecture.md` — the full P2 architecture and the M0–M10 build plan.
3. First task for Claude Code: execute **Milestone M0** (Part I / Part L of the architecture doc).

## Quick start

Requires Docker, [uv](https://docs.astral.sh/uv/) and Node 22.

```sh
make dev          # boot the full local stack (db, minio, api, worker, web)
make test         # backend pytest + frontend vitest (incl. axe-core)
make lint         # ruff + mypy --strict + tsc --noEmit
make regression   # synthetic tender regression suite (fails loudly until M5)
make redteam      # injection red-team suite (fails loudly until M2+)
```

API: http://localhost:8000 (health at `/health`) · Web: http://localhost:5173
· MinIO console: http://localhost:9001.

## Ground rules (summary — CLAUDE.md governs)

- Append-only, hash-chained audit trail; no state change without an event.
- Temperature 0; pinned model version per procurement; versioned, hashed prompts.
- Per-question, per-bidder isolated scoring; comparative prompts permanently prohibited.
- Citations validated deterministically in code; uncited claims invalidate a pass.
- Synthetic data only. No real tender, bidder, employer or client material — ever.
- British English throughout. WCAG 2.2 AA is a hard requirement.
