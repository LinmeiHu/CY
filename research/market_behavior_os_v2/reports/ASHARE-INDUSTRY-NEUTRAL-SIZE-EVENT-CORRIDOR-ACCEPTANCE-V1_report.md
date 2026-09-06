# ASHARE Industry-Neutral Size Event-Corridor Acceptance V1

## Decision

`DEVELOPMENT_GATE_FAIL_EXACT_RULE_CLOSED`

The exact visually derived rule passed the opportunity-breadth gate but failed the one-shot development economics gate. It is closed without threshold, lane, regime, holding-period, or exit rescue. Validation outcomes for 2022–2024 remain unopened.

## Frozen rule

1. Start from the exact monthly, PIT-industry-neutral smallest and largest accepted circulating-market-value mother events.
2. Form a fixed corridor from the mother session and the next four valid sessions.
3. Before entry, reject two consecutive closes below the corridor floor; then require three of the latest five closes above the corridor ceiling, including the current close.
4. Require a causal broad-market `BULL` state or simultaneous 20-versus-60-session improvement in median return and positive-stock participation.
5. Buy the next legal open; exit the next legal open after two consecutive closes below the corridor ceiling, otherwise at H120; charge 40 bps round trip.

Frozen specification SHA-256: `52cd905e371b518d92097ae360c0e62f5c6b07edeb506dd57766d6a4df74fe76`.

## Visual evidence

- Reviewed all 220 chronological contact sheets and all 1,975 individual charts.
- The size lane itself did not visually separate winners from losers.
- Event-area resolution and later retention were the only sufficiently recurrent causal morphology to justify one test.
- Static `BULL` state was visibly too coarse, motivating the pre-frozen causal repair alternative.
- Counterexamples were common; the rule was tested as a data-generated development hypothesis, not treated as a discovered fact.

## Outcome-blind breadth gate

| Signal year | Completed executable signals | Required | Pass |
|---|---:|---:|---|
| 2018 | 193 | >50 | Yes |
| 2019 | 220 | >50 | Yes |
| 2020 | 234 | >50 | Yes |

There were 647 completed entries and exits. No annual or pooled return aggregate was produced until this gate passed.

## One-shot development result

| Signal year | N | Mean net | Median net | Positive | Profit ≥4% | Severe loss ≤−10% | Full gate |
|---|---:|---:|---:|---:|---:|---:|---|
| 2018 | 193 | −4.639% | −6.015% | 9.33% | 8.29% | 24.35% | Fail |
| 2019 | 220 | +1.782% | −4.437% | 23.64% | 20.00% | 17.27% | Fail |
| 2020 | 234 | +4.805% | −5.227% | 21.79% | 20.51% | 19.23% | Fail |
| Pooled | 647 | +0.960% | −5.340% | 18.70% | 16.69% | 20.09% | Fail |

The required condition was more than 50 completed signals, mean net return above 4%, and median net return above zero in every development year. It failed decisively.

## Failure anatomy

- Failed-acceptance exits: N=511, mean net −7.684%, median −6.635%, positive rate 0.78%, severe-loss rate 24.46%.
- H120 time exits: N=136, mean net +33.436%, median +24.418%, positive rate 86.03%.
- Large-size lane: N=280, mean +4.355%, median −4.494%.
- Small-size lane: N=367, mean −1.630%, median −5.821%.

The split says that a small minority of persistent trends carried the mean, while most attempted acceptances failed. Selecting the large lane after observing this result, removing the failure exit, or conditioning on realized persistence would be a rescue experiment and is prohibited.

## Governance

- Development signal years: 2018–2020.
- Maximum context date: 2021-06-30, solely to complete/context pre-2021 signals.
- Post-2021 signal identity read: no.
- Validation 2022–2024 outcome read: no.
- Parameter rescue: no.
- Exact family status: closed.

## Artifacts

- Selection ledger without returns: `/Volumes/quant/CY_quant_research/ashare_industry_neutral_size_event_corridor_acceptance_v1/stage_1/selection_ledger_without_returns.parquet`
- Breadth manifest: `/Volumes/quant/CY_quant_research/ashare_industry_neutral_size_event_corridor_acceptance_v1/stage_1/breadth_gate_manifest.json`
- Trade ledger: `/Volumes/quant/CY_quant_research/ashare_industry_neutral_size_event_corridor_acceptance_v1/stage_2/trade_ledger.parquet`
- Compact result: `/Volumes/quant/CY_quant_research/ashare_industry_neutral_size_event_corridor_acceptance_v1/stage_2/result.json`
