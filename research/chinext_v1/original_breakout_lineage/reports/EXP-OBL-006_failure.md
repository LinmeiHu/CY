# EXP-OBL-006 construction failure

EXP-OBL-006 stopped before writing a feature, audit, freeze manifest, or report.
No future outcome was read or joined.

The action-safe T-1 feature covered all 399 events, reconciled exactly to the
frozen formation artifact, had sufficient continuous variation, preserved log
additivity, and had positive temporal-neighbor direction in all eight years.
It failed the frozen neighboring-stability gate:

- T-1 versus T-3 Spearman rho: `0.420917098111`;
- T-1 versus T-5 Spearman rho: `0.309136767888`;
- frozen minimum for both: `0.60`.

The T-1 distance is therefore a transient one-session position, not a stable
prebreakout formation state across the fixed temporal neighbors. The gate will
not be weakened, and neither T-3 nor T-5 will be selected after inspection.

Decision: `REJECTED_BEFORE_OUTCOME`. No distance threshold, outcome reveal,
candidate rule, V1 change, or CY-011 access is authorized.
