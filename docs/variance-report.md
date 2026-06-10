# Variance distribution — synthetic regression suite (M9)

Source: `tests/regression/test_synthetic_tender.py` against
`synthetic_tender_01` with the deterministic oracle responder
(temperature 0, 3 passes default, 5 passes for Q1 at 15% weighting).

| Variance (bands) | Recommendations | Routing |
|---|---|---|
| 0 | 24 | Converged — recommendation presented at the modal score |
| 1 | 0 | (moderate tier unexercised by the current oracle) |
| 2 | 1 | Escalated — no auto-recommended score (mid bidder, Q4, seeded per-pass disagreement [2, 4, 2]) |

- 25 recommendations across 3 fully-scored bidders plus the gate-failer's
  gate criterion; the gate-failer's remaining 7 runs were blocked by the
  Health and Safety gate (score 1 against a minimum of 2).
- Citation validity: 100% (floor: 99.5%).
- Replay: every run reproduces identical validated outputs from the record.

**Caveat:** these figures characterise the deterministic test harness, not
live model behaviour. The live-model variance distribution must be measured
during calibration on a real procurement (with the pinned model and the
authored oracle) before any pilot conclusions are drawn.
`[[HUMAN INPUT NEEDED: oracle authorship — see fixtures/synthetic_tender_01/oracle.yaml]]`
