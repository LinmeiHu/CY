# Experiment Registry

| ID | Phase | Status | Frozen purpose | Inputs | Primary outputs | Strategy implication |
|---|---:|---|---|---|---|---|
| OC-EXP-P0-001 | 0 | PASS | Freeze prior evidence, source lineage, definitions, oracle boundary, and research gates | Prior reports/contracts; 399-cycle ledger; feature parquet | Contract, hashes, data audit | None; governance only |
| OC-EXP-P1-001 | 1 | PASS | Build a zero-loss 399-cycle conversion panel and daily holding-path table using frozen definitions | Authoritative cycles; PIT-B daily bars; calendar; frozen market features | 399 trades; 5,551 path rows; exact reconciliation | None; outcome measurement only |
| OC-EXP-P2-001 | 2 | PASS | Separate candidate supply from selected-trade opportunity quality; quantify MFE distribution, tail frequency, timing, and dispersion versus continuous breadth | Reconciled event ledger; daily market-gate state; P1 panel | 1,821 candidates; opportunity plateau; terminal disconnect | Cannot create an overlay |
| OC-EXP-P2-002 | 2 | PASS | Audit whether authoritative selection ranks opportunity inside the 1,821-event candidate pool using fixed-horizon oracle outcomes | Persisted candidates; next-session executable-open checks; `OC-SPEC-P2-002` | Selected modestly better; only 30 competitive selection days; RS weak | Oracle cannot create replacement NAV |
| OC-EXP-P3-001 | 3 | PASS | Compare future outcome classes using only existing PIT entry stock features, continuous breadth, and fixed year controls | P1 panel; `OC-SPEC-P2-P4-001` | 0/54 pass frozen causal-feature gate before extreme sensitivity | No entry candidate promoted |
| OC-EXP-P4-001 | 4 | PASS | Attribute Opportunity -> Peak -> Capture using frozen path descriptors, MFE bands, exit lineage, and hold timing | P1 panel and daily path; `OC-SPEC-P2-P4-001` | MFE20-50 conversion leakage; peak-to-exit giveback localization | Path outcomes are diagnostic, not predictors |
| OC-EXP-P5-001 | 5 | PASS | Quantify non-additive selection and exit oracle ceilings and inherit frozen executable exit counterfactuals | P1 panel; frozen Phase 6-9 reports; preregistered post-exit path | Selection/exit ceilings; 398/399 post-exit20 coverage; executable counterevidence | Oracle does not authorize candidate |
| OC-EXP-P6-001 | 6 | PASS | Test Breadth x stock setup, cohort, MFE timing, persistence, giveback, and tail probability without threshold search | P1-P5 outputs; frozen daily feature library | Dispersion mechanism; 0/27 interactions pass | No conditional candidate promoted |
| OC-EXP-P7-001 | 7 | PASS | Apply yearly, rolling, LOYO, neighbors, monotonicity, counts, top-N, extremes, multiplicity, PIT, cost/coverage gates | P2-P6 frozen outputs | Robust opportunity evidence; conversion/predictability falsification | Strategy-design gate FAIL |
| OC-EXP-P8-001 | 8 | PASS | Choose terminal A-E decision and, only if allowed, state the minimum sufficient candidate | All frozen reports | `FINAL_REPORT.md`; 7 tests pass; deterministic rerun | Terminal D; stop without candidate |

## Registry rules

- Status changes and material deviations are recorded before downstream use.
- Exploratory additions receive a new experiment ID; they do not silently
  enter a confirmatory family.
- Neighboring definitions are robustness checks, never a threshold search.
- Failed and null results remain in the registry.
