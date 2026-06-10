# Injection red-team suite

Holds the prompt-injection attack corpus (`corpus/`) and the assertions
that no attack shifts a score or alters instructions while passing
validation (`docs/architecture.md` Part J, gate 4). The corpus doubles as
the ingest-time deterministic scan's pattern source (Part E).

Empty at M0 — `make redteam` fails loudly until the suite exists (M2
onwards, expanded to ≥ 50 variants in M9).
