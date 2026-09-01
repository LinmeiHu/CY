# Methodology

## Reused causal infrastructure

V1 imports the predecessor experiment's registered CY-006 authorization, frozen input
inventory checks, hard-valid historical universe, adjusted reference-price chain, LOW
eligibility, and next-legal-open forward outcomes. It does not alter predecessor artifacts.
All feature rows are known by the signal close; a signal cannot enter until the next listed
session's legal open. Unknown required lineage fails closed.

## Frozen research population

LOW requires a causal 60-session adjusted-close drawdown of at most -15%, adjusted close no
more than 5% above the causal 60-session adjusted intraday low, at least 120 valid trading
sessions, and 20-session median amount of at least CNY 10 million. The current row must be
hard-valid, trading, non-ST, and usable; its 60-session feature history must contain no
unknown required lineage. Main analysis also requires a complete hard-valid 20-session
outcome path and legal next-open entry.

## Variables

- `depth_score = -drawdown_60`; larger is deeper.
- `crash_speed = -Ret10 / -drawdown_60`; larger means more of the current causal peak
  drawdown accumulated in the last ten sessions. This is a frozen path descriptor, not an
  optimized formula.
- `market_relative_20 = stock Ret20 - market Ret20`. The market return compounds twenty
  causal daily equal-weight returns from the same eligible panel. Larger means less
  stock-specific underperformance and therefore a more systematic decline.
- `industry_relative_20` uses the historical PIT industry attached to each daily row and an
  otherwise identical causal equal-weight industry return.
- `near_low_score = -distance_from_low_60`; larger means closer to the causal recent low.

The primary matrices use four economic depth regions and pooled axis terciles formed within
each depth region. This keeps the 4x3 tables dense without searching boundaries on future
returns. The three-axis check uses only the deeper half and excludes middle axis terciles.

## Outcomes and comparisons

Ret5, Ret10, and Ret20 run from the next legal-session open to the adjusted close at the
corresponding horizon. MFE20 and MAE20 use adjusted intraday extremes on that same path.
All are gross discovery outcomes, not strategy returns.

Pooled observations, fixed 20-trading-row de-duplicated LOW events, and daily Spearman rank
relationships are reported separately. Incrementality is the equal-weight average of
top-minus-bottom axis-tercile return spreads within date x depth-region cells of at least
nine observations. The first broad time block is 2020 only because the inherited frozen
signal evaluation begins on 2020-01-02; the other blocks are 2021-2023 and 2024-2026.
Date-relative liquidity terciles, PIT-industry-neutralized daily ranks, and market segments
are descriptive stability checks.

## Limitations

CY-006 is PIT-B rather than a strict PIT-A archive. The benchmark is an equal-weight research
aggregate, not a named tradable index. There is no announcement or fundamental-shock
classifier, minute/L2 fill model, transaction cost model, or portfolio construction. The
study identifies empirical structure only.
