# EXP-SLP-001 preregistration — post-Day-3 residual failure

H-024 asks whether the frozen H-023 adverse state precedes additional failure
after removing the return already realized by the Day-3 close. It is a
mechanical-overlap falsification, not an exit experiment.

The primary population is the fixed 356 actual Day-3 survivors, including 42
accepted severe losses and 342 rows with complete fixed controls. The endpoint
is `-((1 + round_trip_return) / (1 + return_3d) - 1)`. The feature is the
unchanged `adverse_stock_specific_3d`. No post-exit prices, imputation,
counterfactual survival, alternate landmark, threshold, strategy replay, or
action is permitted.

The frozen attacks are within-year ranks, eight LOYO omissions, three temporal
blocks, concurrent 399102 and fixed pre-entry controls, beta-adjusted Day 3,
all-cycle Day 2, actual-survivor Day 5, duration/exit controls, Bottom-4 PnL
removal, severe-loss removal, and security/industry omission. Accepted H-014
Day-5 non-persistence is bound as prior contradictory evidence and cannot be
reinterpreted or tuned away.

AVAILABLE_AT_TIMESTAMP is Day-3 session 15:30 Asia/Shanghai. Any potential action
would be next valid session or later, but this explanatory experiment authorizes
no action. The complete frozen contract and exact gates are in
`experiments/EXP-SLP-001_spec.json`.
