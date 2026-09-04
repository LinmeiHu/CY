# ASHARE-TRUE-GAP-BELOW-L-REGIME-ADAPTIVE-TRANSLATION-V25

## Fixed mechanism

V24 signal identity and entry. Five-session board return >=0 keeps A67/H20; a negative five-session board return uses A50/H10. No signal is removed.

## Development

`REGIME_ADAPTIVE_TRANSLATION_DEVELOPMENT_CANDIDATE`

Accepted 675 (135.0/year); mean 3.50%; median 4.89%; win 74.81%; severe10 7.26%; CAGR 2.96%; MaxDD -1.94%.

|Year|Trades|Mean|Median|Win|Portfolio return|
|---|---:|---:|---:|---:|---:|
|2017|66|0.05%|0.72%|53.03%|-0.02%|
|2018|325|5.37%|6.54%|84.62%|11.38%|
|2019|116|2.75%|4.13%|73.28%|2.07%|
|2020|72|0.82%|2.22%|61.11%|0.51%|
|2021|96|2.44%|3.96%|68.75%|1.44%|

## Translation regimes

```json
{
  "REPAIRED_A67_H20": {
    "cvar5": -0.1783125011309568,
    "mean_holding_sessions": 12.102161100196463,
    "mean_net": 0.04254484748280864,
    "median_holding_sessions": 11.0,
    "median_net": 0.05637211954046184,
    "severe10": 0.07072691552062868,
    "target_hit": 0.6601178781925344,
    "trades": 509,
    "unique_dates": 131,
    "unique_signals": 509,
    "unique_symbols": 462,
    "win": 0.7897838899803536,
    "yearly": {
      "2017": {
        "mean_holding": 16.387096774193548,
        "mean_net": -0.005606904251548836,
        "median_net": -0.0037901846888459545,
        "severe10": 0.16129032258064516,
        "trades": 31,
        "win": 0.4838709677419355
      },
      "2018": {
        "mean_holding": 10.273722627737227,
        "mean_net": 0.06075202230703647,
        "median_net": 0.06802950801944152,
        "severe10": 0.043795620437956206,
        "trades": 274,
        "win": 0.8832116788321168
      },
      "2019": {
        "mean_holding": 14.138613861386139,
        "mean_net": 0.02475012436255527,
        "median_net": 0.04101032493457768,
        "severe10": 0.07920792079207921,
        "trades": 101,
        "win": 0.7227722772277227
      },
      "2020": {
        "mean_holding": 13.891304347826088,
        "mean_net": 0.013251090374712738,
        "median_net": 0.0425100254731513,
        "severe10": 0.13043478260869565,
        "trades": 46,
        "win": 0.6521739130434783
      },
      "2021": {
        "mean_holding": 13.508771929824562,
        "mean_net": 0.036382010009907886,
        "median_net": 0.04754786600042915,
        "severe10": 0.08771929824561403,
        "trades": 57,
        "win": 0.7368421052631579
      }
    }
  },
  "WEAK_A50_H10": {
    "cvar5": -0.1352658408648192,
    "mean_holding_sessions": 8.228915662650602,
    "mean_net": 0.011809234422147164,
    "median_holding_sessions": 11.0,
    "median_net": 0.02560323890811611,
    "severe10": 0.0783132530120482,
    "target_hit": 0.42771084337349397,
    "trades": 166,
    "unique_dates": 86,
    "unique_signals": 166,
    "unique_symbols": 160,
    "win": 0.6204819277108434,
    "yearly": {
      "2017": {
        "mean_holding": 8.857142857142858,
        "mean_net": 0.0059671090146769,
        "median_net": 0.027774752239397626,
        "severe10": 0.08571428571428572,
        "trades": 35,
        "win": 0.5714285714285714
      },
      "2018": {
        "mean_holding": 8.27450980392157,
        "mean_net": 0.015971556760193382,
        "median_net": 0.04128110926048545,
        "severe10": 0.0784313725490196,
        "trades": 51,
        "win": 0.6470588235294118
      },
      "2019": {
        "mean_holding": 6.466666666666667,
        "mean_net": 0.046014774537956854,
        "median_net": 0.057549990192854894,
        "severe10": 0.0,
        "trades": 15,
        "win": 0.8
      },
      "2020": {
        "mean_holding": 9.923076923076923,
        "mean_net": -0.0007586023330458957,
        "median_net": 0.004516777183810605,
        "severe10": 0.07692307692307693,
        "trades": 26,
        "win": 0.5384615384615384
      },
      "2021": {
        "mean_holding": 7.153846153846154,
        "mean_net": 0.00683171144571066,
        "median_net": 0.02490568604560961,
        "severe10": 0.10256410256410256,
        "trades": 39,
        "win": 0.6153846153846154
      }
    }
  }
}
```

## Post-observation diagnostic

Verdict: `REGIME_ADAPTIVE_TRANSLATION_POST_OBSERVATION_FAILED`.
Accepted/year: 63.0; mean: 2.61%; median: 3.99%; win: 62.70%; severe10: 8.73%.

|Year|Trades|Mean|Median|Win|Portfolio return|
|---|---:|---:|---:|---:|---:|
|2022|80|4.59%|5.71%|77.50%|2.31%|
|2023|46|-0.83%|-2.45%|36.96%|-0.10%|

## Governance

- The translation rule was frozen after Development-only mechanism analysis and before this lane opened 2022-2023 outcomes.
- The five-session board feature uses completed sessions ending at the signal-day close; entry remains next session.
- No diagnostic threshold selection is permitted.
- 2024 data may only manage and complete pre-2024 signals.
