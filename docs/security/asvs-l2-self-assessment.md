# OWASP ASVS 4.0 Level 2 self-assessment (pre-pilot)

**Date:** 2026-06-10 · **Assessor:** engineering (self) · **Scope:** Evaluate tier, synthetic data only.
Verdict key: ✓ met · ◐ partly met (gap noted) · ✗ not met (planned) · n/a

| Chapter | Verdict | Notes |
|---|---|---|
| V1 Architecture | ✓ | Threat-informed design docs (architecture Part H); seams for KMS/SSO/queue recorded in ADRs; permanently-excluded features listed in CLAUDE.md. |
| V2 Authentication | ◐ | Password+TOTP with bcrypt, lockout, rate limiting. Gap: password policy is length-only (12+); breach-corpus checks at P4; production SSO (Entra ID) deferred — human-owned decision. |
| V3 Session management | ✓ | Opaque DB-backed tokens, hashed at rest, expiring, revocable, rotated at second factor, logout endpoint, no tokens in URLs or logs (scrubbing filter). |
| V4 Access control | ✓ | Default-deny on every route (CI-enforced); RBAC; distinct audited privilege for the anonymisation map; tenant scoping in dedicated schemas. |
| V5 Validation/encoding | ✓ | Pydantic v2 strict schemas everywhere; SQLAlchemy bound parameters; React escaping; no HTML rendering of bidder text. |
| V6 Cryptography | ◐ | sha256 chains, bcrypt, secrets from env only. Gap: per-tenant envelope encryption designed but awaiting KMS/provider decision (P4). |
| V7 Error/logging | ✓ | Exact, non-leaking error messages; scrubbed logs; the audit trail is append-only and hash-chained — beyond L2's integrity ask. |
| V8 Data protection | ◐ | Synthetic data only by rule; anonymisation before scoring; no-training provider assertion enforced at startup. Gap: at-rest encryption is delegated to volume/bucket config until P4. |
| V9 Communications | ✗ | TLS termination is deploy-time (P4); local Compose is HTTP. Pilot must sit behind TLS with HSTS. |
| V10 Malicious code | ✓ | Lockfiles; no dynamic code loading; prompt artefacts hash-verified at startup. |
| V11 Business logic | ✓ | Framework lock immutability; calibration gate; variance routing to humans; gate enforcement; mandatory rationale on amendment (DB-enforced). |
| V12 Files/resources | ◐ | Extension allowlist (PDF/DOCX/TXT), hash verification, object storage outside the web root. Gap: explicit upload size cap and parser resource limits to add before pilot. |
| V13 API | ✓ | Uniform REST; authenticated SSE; no mass-assignment (explicit schemas). |
| V14 Configuration | ✓ | Env-only secrets; `.env` ignored; CI runs the full gate set; residency assertion refuses non-UK/EEA endpoints in production. |

## Actions before pilot (tracked for P4)

1. TLS + HSTS at the edge (V9) — blocking for any non-local deployment.
2. Upload size cap and parser timeouts (V12).
3. Password breach-corpus check or SSO cutover (V2).
4. KMS-backed envelope encryption once the cloud provider lands (V6/V8).
