# HAB-CHX-RANK-INFO-001 — candidate information scan

The current fixed admission system produced 398 candidate events on 225 dates. Only 75 dates contain ranking competition.

| Descriptor | Family | Role | Oriented rho dev | Oriented rho later | Top-1 mean delta dev | Top-1 mean delta later |
|---|---|---|---:|---:|---:|---:|
| rs_score | trend_relative_strength | EXISTING_BASELINE_CONDITIONAL | 0.170 | -0.004 | 0.000% | 0.000% |
| r20 | trend_relative_strength | COMPLEMENTARY | 0.102 | 0.004 | 0.746% | 0.523% |
| r60 | trend_relative_strength | REDUNDANT | 0.220 | -0.040 | 2.436% | -0.114% |
| r120 | trend_relative_strength | COMPLEMENTARY | 0.048 | 0.090 | -0.738% | 3.440% |
| rs_acceleration | trend_relative_strength | CONDITIONAL | -0.102 | 0.068 | 1.795% | 1.708% |
| mom20 | trend_relative_strength | CONDITIONAL | -0.058 | 0.072 | 0.746% | 0.523% |
| mom60 | trend_relative_strength | COMPLEMENTARY | -0.013 | -0.338 | 2.436% | -0.114% |
| mom120 | trend_relative_strength | COMPLEMENTARY | -0.056 | -0.063 | -0.738% | 3.440% |
| box_width | risk_path_setup | CONDITIONAL | 0.165 | -0.054 | 3.958% | 0.178% |
| ma_dispersion | risk_path_setup | COMPLEMENTARY | -0.021 | -0.121 | 1.061% | -0.360% |
| direction_efficiency | risk_path_setup | COMPLEMENTARY | -0.048 | -0.074 | 2.004% | -1.922% |
| vol_ratio | supply_demand | COMPLEMENTARY | 0.061 | 0.090 | 0.816% | -0.662% |
| minvol_location | supply_demand | CONDITIONAL | 0.080 | -0.064 | 6.578% | 0.807% |
| minvol_ratio | supply_demand | CONDITIONAL | 0.070 | -0.059 | 3.310% | -0.579% |
| breakout_volume_ratio | supply_demand | CONDITIONAL | 0.003 | -0.001 | 1.813% | 2.528% |

The 20-session target is attribution from an executable next open, not a strategy replay. All descriptors are available at the completed signal close; future return, MFE, and MAE fields are never predictors.

Every block is consumed development history. No post-2023 or CY-011 row was read.
