# A-share Shock Absorption / Recovery Discovery V1.1

## Executive conclusion

Final classification: `NULL`.

The bounded 18-cell neighborhood contains no useful stable post-shock absorption mechanism in the frozen orientation.

This is consumed 2018-2023 development evidence. The exact V1 result was already known before V1.1 was frozen; the 18 new cell outcomes were not.

## Parameter neighborhood

The complete frozen grid is absolute shock <= -4%/-6%/-8%, stock-minus-PIT-industry shock <= -2%/-4%, and exact W=2/3/5 completed sessions: 18 cells, with no additions or removals.

## Event coverage

Across cells there are 709,981 ranked event instances, spanning 4,344 securities, 119 industries, and 1308 confirmation dates. Per-cell ranked events range from 14,472 to 94,404.

## Parameter surface

| Cell | Events | h5 net | h5 industry | h10 net | h10 industry | h20 net | h20 industry | Favorable | Coherent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| ABS_m04_REL_m02_W2 | 94,404 | -0.443% | -0.292% | -0.779% | -0.499% | -1.130% | -0.751% | False | False |
| ABS_m04_REL_m02_W3 | 88,280 | -0.349% | -0.195% | -0.770% | -0.356% | -1.230% | -0.700% | False | False |
| ABS_m04_REL_m02_W5 | 78,428 | -0.445% | -0.250% | -0.946% | -0.465% | -1.509% | -0.814% | False | False |
| ABS_m04_REL_m04_W2 | 50,115 | -0.315% | -0.148% | -0.682% | -0.300% | -0.933% | -0.372% | False | False |
| ABS_m04_REL_m04_W3 | 47,636 | -0.477% | -0.204% | -0.900% | -0.315% | -1.437% | -0.554% | False | False |
| ABS_m04_REL_m04_W5 | 43,756 | -0.506% | -0.188% | -0.954% | -0.338% | -1.559% | -0.522% | False | False |
| ABS_m06_REL_m02_W2 | 42,258 | -0.177% | -0.255% | -0.496% | -0.390% | -0.736% | -0.602% | False | False |
| ABS_m06_REL_m02_W3 | 40,570 | -0.287% | -0.202% | -0.663% | -0.332% | -1.037% | -0.674% | False | False |
| ABS_m06_REL_m02_W5 | 37,629 | -0.313% | -0.177% | -0.737% | -0.342% | -1.360% | -0.705% | False | False |
| ABS_m06_REL_m04_W2 | 30,532 | -0.041% | -0.080% | -0.278% | -0.088% | -0.537% | -0.203% | False | False |
| ABS_m06_REL_m04_W3 | 29,427 | -0.315% | -0.233% | -0.654% | -0.327% | -0.924% | -0.529% | False | False |
| ABS_m06_REL_m04_W5 | 27,644 | -0.280% | -0.184% | -0.674% | -0.285% | -1.038% | -0.335% | False | False |
| ABS_m08_REL_m02_W2 | 18,679 | -0.109% | -0.272% | -0.418% | -0.337% | -0.803% | -0.519% | False | False |
| ABS_m08_REL_m02_W3 | 18,187 | -0.012% | -0.209% | -0.343% | -0.272% | -0.783% | -0.496% | False | False |
| ABS_m08_REL_m02_W5 | 17,262 | -0.068% | -0.092% | -0.392% | -0.131% | -1.048% | -0.381% | False | False |
| ABS_m08_REL_m04_W2 | 15,552 | -0.107% | -0.200% | -0.550% | -0.242% | -0.934% | -0.329% | False | False |
| ABS_m08_REL_m04_W3 | 15,150 | -0.102% | -0.271% | -0.471% | -0.320% | -0.851% | -0.490% | False | False |
| ABS_m08_REL_m04_W5 | 14,472 | -0.172% | -0.112% | -0.557% | -0.189% | -1.081% | -0.280% | False | False |

## Stability topology

Stable region found: `False`. Favorable cells: 0; coherent cells: 0; sign-reversal cells: 0. Region: none. Region center: none.

## Controls

Control target: `ABS_m06_REL_m04_W3`. Severity pass: `False`; supported cells: 9; positive fraction: 22.2%.
- W2 shock/generic mean primary industry-relative spread: -0.124%/-0.001%; generic-similar=False.
- W3 shock/generic mean primary industry-relative spread: -0.363%/+0.001%; generic-similar=True.
- W5 shock/generic mean primary industry-relative spread: -0.268%/+0.000%; generic-similar=True.
- PRE_SHOCK_TREND: -0.311% / -0.436% / -0.448%; pass=False.
- REALIZED_VOLATILITY: -0.300% / -0.354% / -0.494%; pass=False.
- LIQUIDITY: -0.396% / -0.349% / -0.366%; pass=False.

## Chronological stability

Cell-level early/late and annual signs are persisted in the compact surface and result artifacts. Coherence requires both blocks positive and at least four positive annual means; no year is relabeled OOS.

## Walk-forward gate

Gate: `FAIL`. Failed frozen gates: stable_region, severity_pass, trend_pass, volatility_pass, liquidity_pass, generic_not_similar.

## Development walk-forward

Not run because the frozen discovery gate failed.

## Strategy-A independence and execution

Low-MAX mean same-date rho is 0.031; Champion Q5 overlap is 0.05%. No Strategy-A rule or result changed.

Control-target next-open actionability is 99.89%.

## Decision

`NULL`. Close Shock Absorption V1.1 without rescue and resume the frozen Cross-Sectional Dispersion science.

No Strategy-B portfolio, parameter rescue, post-2023 outcome, or CY-011 input was used.
