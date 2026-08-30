# MKT-LDR-001 leader-failure representation freeze

## Boundary

- Status: `COMPLETE_OUTCOME_BLIND_LEADER_REPRESENTATION_FREEZE`
- Input is the immutable MKT-BRTH-002 representation panel only.
- Strategy membership, outcomes, future returns, paths, and CY-011 read: **none**.
- Concentration level is not leader failure; this experiment establishes no reversal, continuation, short, veto, or strategy claim.
- Joint deterioration geometry: `NOT_CONSTRUCTED_TRANSITION_GATE_FAILED`.

## Representation gates

| Concept | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Gate |
|---|---:|---:|---:|---:|---|
| concentration_decay | 1.000 | 0.683 | 1.000 | 1.000 | FAIL |
| discovery_deterioration | 1.000 | 0.500 | 0.986 | 1.000 | FAIL |
| leadership_discovery_imbalance | 1.000 | 0.988 | 0.996 | 1.000 | PASS |

Failed exact representations leave the broader leader-failure family open; no favorable neighbor may replace a failed primary.

## Reproducibility

- Spec SHA-256: `6fc2435efc9b0aca2c24392c2b8a32be881dcdc94e473cb75ebd0eed0383f2a7`
- Input panel SHA-256: `60ca6bf5a69c8054d9d4c9543d6eea6aa3bfbc2835fc8f8efa63d1d09c03374a`
- Output panel SHA-256: `67fb4aee780db8c9b15861dd2d16be83c9f7ea31696d1a8985547024825be8dd`
