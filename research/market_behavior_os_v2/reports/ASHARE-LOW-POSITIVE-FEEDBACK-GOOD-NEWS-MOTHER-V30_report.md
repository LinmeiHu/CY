# V30 — Low Positive-Feedback Good-News Mother

## Conclusion

V30 is closed as a strategy candidate. The mother population had positive aggregate development payoff, but it failed the required every-year gate and complete chart review did not produce a reliable static buy or sell rule.

This is not a statement that the charts contained no recurring shapes. Five motifs recurred: low-base first lift, orderly staircase advance, mature/terminal crowding, right-side repair, and isolated spike/turnover impulse. Each motif also had many near-looking losing and winning counterexamples, frequently on the same decision date. Market/calendar state explained more than a simple stock-chart taxonomy.

## Frozen signal-level result

- Signals: 2,312; completed lifecycles: 2,284.
- Overall mean net return per completed signal: +0.627%.
- Median: +4.115%; positive rate: 58.36%; severe-loss rate: 16.46%.
- Annual mean net return: 2014 +2.118%, 2015 -0.257%, 2016 -0.031%, 2017 -1.206%, 2018 -2.254%, 2019 +1.600%, 2020H1 +4.906%.
- Only 2020H1 exceeded the required +4% annual mean. Therefore the development gate failed and 2021 plus 2022–2024 stayed closed.

## Complete chart review

All 2,312 individual ±126-session charts were reviewed through 93 chronological and 95 mutually exclusive outcome-group sheets. Every occupied cell was examined. Eighty-one explicit counterexample rows were retained, and no post-signal candle was accepted as a signal-time rule input.

The result is `0` frozen rules. This is a deliberate rejection of false precision, not a skipped visual-analysis step.

The completed external review ledger is at `/Volumes/quant/CY_quant_research/ashare_low_positive_feedback_good_news_mother_v30/stage_d_visual_review/`; its manifest SHA-256 is `22645dea6616991f9641f1ca31bc8eddc1ea5c494636096ff979b4076b8201cb`.

## Rendering caveat and correction

The V30 image used one full-window price and turnover scale. A large future move could therefore visually compress the pre-signal shape. Because no V30 rule was promoted, this flaw cannot create a false surviving strategy; the conservative close decision stands. V31 corrects the protocol by masking the post-signal half during the first pass and calculating the two halves on independent scales.

## Research decision

Do not tune V30 thresholds or repeat the same turnover-feedback family. Continue with a distinct economic mechanism and a strictly blinded chart-compression protocol.
