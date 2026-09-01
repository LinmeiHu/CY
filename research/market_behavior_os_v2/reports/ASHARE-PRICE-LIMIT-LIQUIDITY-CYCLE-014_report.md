# ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014

Consumed 2018--2023 development history only; not OOS, independent confirmation, validation, live, or production evidence. Post-2023 outcomes and CY-011 were not read.

## Price-limit lifecycle

Historical `up_limit_price` and `limit_pct` are used stock-date by stock-date. A touch is a completed bar high at the registered limit; acceptance is a completed bar close at the limit. Transitions inside one bar remain unresolved.

The accepted sample contains 10,583 5% ST stock-days, 91,542 10% stock-days,
and 5,008 20% stock-days. No universal limit is inferred. The daily high is
only a coarse candidate filter: 546 of 107,679 candidates do not touch the
registered limit in the bound raw-minute session and are excluded, not repaired.
All remaining 107,133 rows have an exact CY-008 241-bar session binding.

The taxonomy was frozen before outcomes: first completed accepted close by
11:00 with no later completed reopen is `EARLY_STABLE_ACCEPTANCE`; first
acceptance after 11:00 and before 14:00 with no reopen is
`MID_STABLE_ACCEPTANCE`; first acceptance from 14:00 is
`LATE_STABLE_ACCEPTANCE`; a completed reopen followed by a final accepted close
is `REOPEN_SUCCESSFUL_RESEAL`; every touched but non-accepted close is
`FAILED_ACCEPTANCE`. The close-known signal is timestamped 15:30 and can first
enter at the next legal open. Outcomes are net of 20 bps per side and preserve
T+1, suspension, limit, and accepted corporate-action handling.

Track-A classification: `NO_USEFUL_LIFECYCLE_INFORMATION`.

| lifecycle                |   events |   dates |   symbols |   entry_coverage |   next_day_blocked |   next_day_suspended |   median_capacity_cny |   p10_capacity_cny |   complete_h1 |   mean_net_h1 |   median_net_h1 |   complete_h3 |   mean_net_h3 |   median_net_h3 |   complete_h5 |   mean_net_h5 |   median_net_h5 |   winner_h3 |   severe_h5 |   mean_net_h3_early |   events_early |   mean_net_h3_late |   events_late |
|:-------------------------|---------:|--------:|----------:|-----------------:|-------------------:|---------------------:|----------------------:|-------------------:|--------------:|--------------:|----------------:|--------------:|--------------:|----------------:|--------------:|--------------:|----------------:|------------:|------------:|--------------------:|---------------:|-------------------:|--------------:|
| EARLY_STABLE_ACCEPTANCE  |    24537 |    1436 |      3662 |           0.9632 |             0.2197 |               0.0044 |           869526.3805 |        288641.4337 |         23522 |       -0.0218 |         -0.0272 |         23355 |       -0.0273 |         -0.0378 |         23185 |       -0.0314 |         -0.0454 |      0.3258 |      0.2774 |             -0.0316 |          10335 |            -0.0242 |         14202 |
| FAILED_ACCEPTANCE        |    35570 |    1437 |      4136 |           0.9959 |             0.0060 |               0.0024 |          1100472.8080 |        309241.1503 |         35276 |       -0.0024 |         -0.0065 |         35044 |       -0.0028 |         -0.0107 |         34764 |       -0.0032 |         -0.0132 |      0.4322 |      0.1278 |             -0.0036 |          16501 |            -0.0021 |         19069 |
| LATE_STABLE_ACCEPTANCE   |     6588 |    1324 |      2753 |           0.9917 |             0.0231 |               0.0047 |          1524171.7665 |        368436.5469 |          6497 |       -0.0103 |         -0.0147 |          6445 |       -0.0150 |         -0.0211 |          6395 |       -0.0187 |         -0.0283 |      0.3787 |      0.1947 |             -0.0155 |           3604 |            -0.0145 |          2984 |
| MID_STABLE_ACCEPTANCE    |     8422 |    1374 |      3087 |           0.9917 |             0.0489 |               0.0028 |          1216358.4321 |        340670.8510 |          8310 |       -0.0136 |         -0.0185 |          8231 |       -0.0169 |         -0.0265 |          8155 |       -0.0202 |         -0.0314 |      0.3616 |      0.2040 |             -0.0222 |           3425 |            -0.0133 |          4997 |
| REOPEN_SUCCESSFUL_RESEAL |    32016 |    1437 |      4129 |           0.9893 |             0.0398 |               0.0046 |          1297181.8984 |        330555.9727 |         31531 |       -0.0067 |         -0.0111 |         31231 |       -0.0094 |         -0.0176 |         31010 |       -0.0115 |         -0.0230 |      0.4080 |      0.2017 |             -0.0104 |          15769 |            -0.0084 |         16247 |

### Direct contrasts

| comparison       |   pairs |   complete_pairs |   same_industry_fraction |   mean_match_distance |   mean_net_h3_delta |   winner_improvement |   severe_h5_improvement |   mean_net_h3_delta_early |   mean_net_h3_delta_late |
|:-----------------|--------:|-----------------:|-------------------------:|----------------------:|--------------------:|---------------------:|------------------------:|--------------------------:|-------------------------:|
| EARLY_VS_LATE    |   21270 |            19632 |                   0.1079 |                3.7804 |             -0.0126 |              -0.0471 |                 -0.0989 |                   -0.0170 |                  -0.0092 |
| STABLE_VS_FAILED |   39006 |            36484 |                   0.3434 |                3.4105 |             -0.0188 |              -0.0815 |                 -0.1272 |                   -0.0216 |                  -0.0167 |
| STABLE_VS_RESEAL |   39001 |            36151 |                   0.3524 |                3.3655 |             -0.0110 |              -0.0502 |                 -0.0600 |                   -0.0136 |                  -0.0090 |

The preregistered acceptance ordering fails in every direct contrast and both
broad blocks. Stable acceptance is 1.884 percentage points worse at h3 than
failed acceptance and worsens h5 severe-loss incidence by 12.723 points.
Early stable acceptance is 1.261 points worse than late acceptance at h3; it is
also 1.102 points worse than reopen/reseal. Early acceptance alone loses 2.181%,
2.732%, and 3.144% net at h1/h3/h5 and is unbuyable at the next open in 21.975%
of observations. This is adverse evidence against the specified long
continuation mechanism, not authorization to invert the sign.

## Liquidity transition

|   events |   dates |   symbols |   entry_coverage |   next_day_blocked |   next_day_suspended |   median_capacity_cny |   p10_capacity_cny |   complete_h1 |   mean_net_h1 |   median_net_h1 |   complete_h3 |   mean_net_h3 |   median_net_h3 |   complete_h5 |   mean_net_h5 |   median_net_h5 |   winner_h3 |   severe_h5 |   mean_net_h3_early |   events_early |   mean_net_h3_late |   events_late | hypothesis                          | role    |
|---------:|--------:|----------:|-----------------:|-------------------:|---------------------:|----------------------:|-------------------:|--------------:|--------------:|----------------:|--------------:|--------------:|----------------:|--------------:|--------------:|----------------:|------------:|------------:|--------------------:|---------------:|-------------------:|--------------:|:------------------------------------|:--------|
|    43493 |    1397 |      4780 |           0.9946 |             0.0045 |               0.0026 |           727613.1117 |        285265.0017 |         43033 |       -0.0052 |         -0.0086 |         42635 |       -0.0067 |         -0.0130 |         42274 |       -0.0081 |         -0.0157 |      0.3956 |      0.0928 |             -0.0078 |          16259 |            -0.0061 |         27234 | ACTIVITY_SHOCK_REJECTION            | control |
|    94912 |    1397 |      4858 |           0.9959 |             0.0025 |               0.0015 |           815603.0593 |        293099.4924 |         94090 |       -0.0036 |         -0.0064 |         93302 |       -0.0045 |         -0.0110 |         92533 |       -0.0051 |         -0.0140 |      0.4075 |      0.0890 |             -0.0044 |          37743 |            -0.0045 |         57169 | ACTIVITY_SHOCK_REJECTION            | event   |
|     4287 |    1089 |      2658 |           0.9925 |             0.0040 |               0.0030 |           571891.3513 |        259543.9685 |          4226 |       -0.0043 |         -0.0060 |          4186 |       -0.0059 |         -0.0090 |          4157 |       -0.0071 |         -0.0103 |      0.4035 |      0.0409 |             -0.0078 |           1808 |            -0.0044 |          2479 | DORMANT_ACTIVE_CONSTRUCTIVE         | control |
|     7150 |    1113 |      3450 |           0.9908 |             0.0048 |               0.0042 |           621385.4084 |        257725.7374 |          7032 |       -0.0037 |         -0.0059 |          6948 |       -0.0048 |         -0.0083 |          6882 |       -0.0042 |         -0.0080 |      0.4165 |      0.0453 |             -0.0066 |           2916 |            -0.0036 |          4234 | DORMANT_ACTIVE_CONSTRUCTIVE         | event   |
|     7551 |    1168 |      3470 |           0.9968 |             0.0008 |               0.0005 |           811247.8215 |        301810.7525 |          7466 |       -0.0044 |         -0.0041 |          7412 |       -0.0062 |         -0.0080 |          7366 |       -0.0076 |         -0.0103 |      0.3958 |      0.0371 |             -0.0077 |           3610 |            -0.0049 |          3941 | LIQUIDITY_RECOVERY_AFTER_WITHDRAWAL | control |
|     8534 |    1168 |      3631 |           0.9952 |             0.0008 |               0.0005 |           646308.4124 |        258405.8266 |          8413 |       -0.0040 |         -0.0050 |          8338 |       -0.0048 |         -0.0081 |          8270 |       -0.0060 |         -0.0102 |      0.3898 |      0.0305 |             -0.0038 |           4269 |            -0.0059 |          4265 | LIQUIDITY_RECOVERY_AFTER_WITHDRAWAL | event   |

### Matched transition contrasts

| comparison                          |   pairs |   complete_pairs |   same_industry_fraction |   mean_match_distance |   mean_net_h3_delta |   winner_improvement |   severe_h5_improvement |   mean_net_h3_delta_early |   mean_net_h3_delta_late |
|:------------------------------------|--------:|-----------------:|-------------------------:|----------------------:|--------------------:|---------------------:|------------------------:|--------------------------:|-------------------------:|
| ACTIVITY_SHOCK_REJECTION            |   94912 |            90394 |                   0.5273 |                3.6590 |              0.0030 |               0.0130 |                  0.0133 |                    0.0040 |                   0.0024 |
| DORMANT_ACTIVE_CONSTRUCTIVE         |    7106 |             6708 |                   0.3099 |                1.1284 |              0.0004 |               0.0133 |                 -0.0103 |                    0.0002 |                   0.0005 |
| LIQUIDITY_RECOVERY_AFTER_WITHDRAWAL |    8534 |             8137 |                   0.7266 |                1.2349 |              0.0005 |              -0.0125 |                  0.0058 |                    0.0020 |                  -0.0011 |

`DORMANT_ACTIVE_CONSTRUCTIVE` uses a prior-20 activity baseline, a bounded
current activity expansion, positive daily return, and close-location
acceptance. Its matched h3 advantage is only 0.04 percentage points and its h5
severe-loss rate is 1.03 points worse: `PROMISING_INFORMATION`, below replay
gates. `ACTIVITY_SHOCK_REJECTION` was preregistered as adverse after an activity
shock plus weak price acceptance; the observed event-minus-control h3 effect is
+0.30 points in both blocks, the opposite sign, so it is `ADVERSE` and is not
inverted. `LIQUIDITY_RECOVERY_AFTER_WITHDRAWAL` is +0.20 points early and -0.11
points late at h3: `CHRONOLOGICALLY_MIXED`.

## Advancement

Early proxy: `NOT_AUTHORIZED`. Price-limit replay: `NOT_AUTHORIZED`. Liquidity replay: `NOT_AUTHORIZED`.

No Track-A/Track-B signal combination was run. Cross-mechanism overlap is descriptive only.
The transition hypotheses explicitly exclude price-limit-touch days, so the
recorded overlap is zero by construction and is not evidence of independence.
An initially computed mechanical early-proxy diagnostic was quarantined before
interpretation; its values are absent from the accepted result and did not
affect classification.

## Next research capital

Do not continue this exact lifecycle taxonomy or these transition definitions.
Highest expected-information-value frontiers are now: (1) bounded external
validation/confirmation data if a lawful independent period becomes available;
(2) order-book/queue or investor-flow identity only under a multi-family PIT
data contract; (3) borrow-feasible relative-value questions; and (4) immutable-
vintage fundamentals if a turnkey source appears. No new strategy archetype is
implied by this cycle.
