# Synthetic tender regression suite

Holds the canonical synthetic procurement fixture
(`fixtures/synthetic_tender_01/`) and the regression tests that assert
known-correct scores within tolerance and citation validity ≥ 99.5%
(`docs/architecture.md` Parts J and K).

Empty at M0 — `make regression` fails loudly until the suite exists (M5).

`[[HUMAN INPUT NEEDED: Felix to author/review the oracle scores for
synthetic_tender_01 — this is the regression ground truth.]]`
