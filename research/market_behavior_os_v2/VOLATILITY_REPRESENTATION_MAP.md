# Volatility Representation Map

Frozen before MKT-VOL-001. Volatility is not represented by one realized-
volatility number and is not assumed to mean panic, opportunity, or risk premia.

| Concept | Primary absolute representation | Fixed neighbors | Economic role |
|---|---|---|---|
| Realized volatility | cross-sectional median annualized 20-session security log-return volatility | 10 and 40 sessions | price variation level |
| Downside volatility | cross-sectional median annualized 20-session negative-log-return semideviation | 10 and 40 sessions | downside variation level |
| Intraday range | five-session mean of the cross-sectional median `log(high/low)` | three and ten sessions | completed-bar range intensity |
| Volatility term structure | median security RV10/RV40 | RV10/RV20 and RV20/RV40 | short-versus-long variation |
| Cross-sectional dispersion | five-session mean of the daily median absolute security return deviation from the governed-view median | three and ten sessions | idiosyncratic spread |
| Downside mass share | five-session mean of negative squared-return mass divided by all squared-return mass | three and ten sessions | directional volatility asymmetry |
| Volatility concentration | share of current squared-return mass in the top squared-return decile | top 5% and top 20% shares | tail concentration |
| Volatility change | five-session change in median RV20 | three and ten sessions | volatility transition |

Fixed neighbors are robustness definitions, not a search. A failed primary is
not replaced by the best horizon. Realized volatility, downside volatility,
range, dispersion, asymmetry, concentration, term structure, and change remain
distinct until outcome-blind redundancy evidence supports compression.

All raw measures are dimensionless and cross-year comparable. Each primary also
preserves strictly causal expanding/trailing percentiles, robust z-scores, and
governed-view relative coordinates. The views, denominators, causal corporate-
action return coordinate, current-trading core, decision timestamp, and bounded
PIT-B semantics are inherited unchanged from the breadth/correlation contracts.

Current-day high, low, and close are used only after the completed 15:00 bar.
Exact rolling security windows require consecutive valid sessions. Invalid OHLC,
missing coordinate steps, or unknown required lineage fail closed. No volatility
measure is a same-bar executable signal.

MKT-VOL-001 is representation construction only. It cannot establish contraction
or expansion usefulness, panic, reversal, continuation, a habitat, or a strategy.
