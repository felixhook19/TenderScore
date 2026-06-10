# `app/ingestion`

Upload to object storage (S3 interface), PDF/DOCX/text parsing, per-question splitting anchored on criterion refs, content hashing, and the deterministic injection scanner (layer 1). Built in M2; compliance checks run after ingest.

Tests: see `tests/` (unit, integration, regression and red-team suites cover this module; the audit-completeness walk exercises its endpoints).
