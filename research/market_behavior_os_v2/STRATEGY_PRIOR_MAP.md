# External strategy prior map — cycle 005

Frozen before cycle-005 forward-outcome construction. External sources provide
definitions, not trusted performance. All local tests remain consumed
2018--2023 PIT-B development research.

| Prior | Archetype / source | Independent date | Economic mechanism | Canonical definition | A-share implementation | Cycle-005 status |
|---|---|---:|---|---|---|---|
| EXT-JT-MOM-001 | Cross-sectional momentum — [Jegadeesh and Titman](https://users.nber.org/~confer/99/bff99/jegadeesh.pdf.gz) | 1993 | Gradual information diffusion / underreaction | Rank prior 3--12 month return; buy winners and sell losers for 3--12 months | Long top portfolio only; monthly decision, 12-minus-1-month signal, six-month hold | `FROZEN_CANONICAL_LONG_LEG_SCREEN` |
| EXT-GH-52W-001 | 52-week-high anchoring — [George and Hwang](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2004.00695.x) | 2004 | Investors anchor on a salient prior high and underreact near it | Rank current price / prior 52-week high; long near-high, short far-from-high, six-month overlapping holds | Long top portfolio; exact causal action coordinate, monthly decision, six-month hold | `FROZEN_CANONICAL_LONG_LEG_SCREEN` |
| EXT-MG-INDMOM-001 | Industry momentum — [Moskowitz and Grinblatt](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2019/09/DoIndustriesExplainMomentum.pdf) | 1999 | Industry information diffuses gradually across constituent stocks | Rank stocks by past value-weighted industry return; buy winner industries, sell loser industries | PIT industry, leave-one-out equal-weight return, six-month formation/hold, monthly decision | `FROZEN_CANONICAL_LONG_LEG_SCREEN` |
| EXT-BCW-MAX-001 | Lottery/MAX — [Bali, Cakici, and Whitelaw](https://doi.org/10.1016/j.jfineco.2010.08.014) | 2011 | Lottery preference overprices stocks with extreme recent upside | MAX is the maximum daily return in the prior month; high MAX predicts low next-month return | Rank negative prior-20-session MAX; monthly decision and one-month hold | `FROZEN_CANONICAL_LONG_LEG_SCREEN` |
| EXT-MIWA-INTRAREV-001 | Intraday short reversal — [Miwa](https://doi.org/10.1142/S2010139219500022) | 2019 | Intraday liquidity concessions reverse over the next week | Past-week intraday return, not overnight return, reverses in the following week | Sum five causal open-to-close returns; long lowest; weekly decision and five-session hold | `FROZEN_CANONICAL_LONG_LEG_SCREEN` |
| EXT-AMIHUD-ILLIQ-001 | Illiquidity premium — [Amihud](https://www.sciencedirect.com/science/article/pii/S1386418101000246) | 2002 | Investors require compensation for price impact / illiquidity | Average daily absolute return divided by dollar volume, originally estimated over a year | Exact annual/calendar implementation is not available within the compact shared weekly/monthly runner | `CANONICAL_REPLICATION_DEFERRED_NOT_SILENTLY_ADAPTED` |
| EXT-FP-BAB-001 | Betting against beta — [Frazzini and Pedersen](https://pages.stern.nyu.edu/~afrazzin/pdf/Betting%20Against%20Beta%20-%20Frazzini%20and%20Pedersen.pdf) | 2014 | Leverage constraints overprice high-beta securities | Lever low-beta portfolio to beta one and short de-levered high-beta portfolio monthly | Historical beta is estimable, but leverage, shorting, and risk-free financing are unavailable | `A_SHARE_IMPLEMENTATION_CONFLICT` |
| EXT-GGR-PAIRS-001 | Pairs trading — [Gatev, Goetzmann, and Rouwenhorst](https://repec.som.yale.edu/icfpub/publications/2573.pdf) | 1998/2006 | Temporary relative mispricing of close substitutes converges | Select minimum-distance normalized-price pairs over 12 months; trade 2-sigma divergence for six months, long loser/short winner | Short leg and pair-level borrow/execution are unavailable | `A_SHARE_IMPLEMENTATION_CONFLICT` |
| EXT-BHM-RESMOM-001 | Residual momentum — [Blitz, Huij, and Martens](https://repub.eur.nl/pub/22252/ResidualMomentum-2011.pdf) | 2011 | Remove systematic-factor exposures from conventional momentum | Rank standardized residual returns from a Fama--French residual model | Registered PIT value/profitability factor inputs are unavailable; no proxy substitution | `DATA_UNAVAILABLE` |
| EXT-CRW-PRCLIM-001 | A-share price-limit delayed discovery — [Chen, Rui, and Wang](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID711101_code211389.pdf?abstractid=711101) | 2005 | Limits may delay price discovery and create post-limit continuation/asymmetry | Event study of upper/lower limit hits under historical Chinese market rules | Exact long-only `limit_up_aftermath` h5 formulation was already negative in cycle 002 | `EXISTING_EXACT_FORMULATION_ADVERSE_NO_RERUN` |

## Frozen cycle-005 local tests

- External screens: `jt_momentum_12_1`, `gh_52_week_high`,
  `industry_momentum_120`, `max_lottery_20`, and
  `intraday_reversal_5`. Long-only implementation differences are reported
  explicitly; no short-leg return is inferred.
- Internal screens: chip overhead-supply clearance, local below-close chip
  support density, and chip-cost concentration.
- Small combinations: equal-rank `max_lottery_20 + low_idio_20`, and equal-rank
  `industry_diffusion_acceleration + low_idio_20`.
- No fundamentals, post-2023 outcomes, CY-011, habitat, neighboring horizons,
  feature-subset search, or long-suspension repair enter this cycle.
