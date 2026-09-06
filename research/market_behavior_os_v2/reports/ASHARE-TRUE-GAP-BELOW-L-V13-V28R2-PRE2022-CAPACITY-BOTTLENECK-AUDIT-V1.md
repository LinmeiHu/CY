# ASHARE-TRUE-GAP-BELOW-L V13–V28R2 pre-2022 capacity bottleneck audit

## Scope and counting semantics

- This audit uses only frozen development identities whose signal dates are no later than 2021-12-31.
- Counts were reconstructed from selected-entry files and their outcome-independent portfolio ledgers. No new return replay was run.
- `candidate` means the signal identity retained by that version's completed-bar selector. `executable` means `entry_status == EXECUTABLE_ENTRY` and an exact portfolio-ledger identity exists. `K80 accepted` means ledger status `EXECUTED`.
- All year and date distributions below use `signal_date`, not exit date. V13 and V27 also have 2017 development rows, but 2018–2021 is the comparable span because registered CY033 state used by V28 begins in 2018.

## CY033 lineage feasibility

An explicit four-partition join against CY033 `partition_year=2018`, `2019`, `2020`, and `2021` produced the following outcome-blind lineage audit:

The registry-bound CY033 manifest SHA-256 is `95905858212f9a79a4f99ba8746fe47c66619ea5f4815eeeb4f0ead195219977`. The exact consumed partition hashes are `b906d2c21fd35128b8f65f1b00fa12ae6e5bd9ee476a368a63881304f38ceed4` (2018), `c69a464e4a04efdca0177a8a09a13a34646531afa37a2b35b4892fd40ec3ebfd` (2019), `1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62` (2020), and `cbd4b2d2ccdff32b09ed1a2e9347f8045cde89ff7e4e1b189577bc353e4d9311` (2021).

|Frozen identity set|Signal rows|Exact symbol-date matches|`hard_valid`|`industry_valid`|Nonempty `snapshot_id`|Nonempty `industry_snapshot_id`|`available_at <= signal_time`|
|---|---:|---:|---:|---:|---:|---:|---:|
|V13, 2018–2021|850|850|850|850|850|850|850|
|V27, 2018–2021|444|444|444|444|444|444|444|
|V28R2, 2018–2021|370|370|370|370|370|370|370|

Therefore a new signal selector can be formalized from the frozen gap identity plus exact CY033 2018–2021 rows without CY034. The Stage A signal artifact should carry `signal_snapshot_id`, `signal_daily_snapshot_id`, `signal_industry_snapshot_id`, `signal_available_at`, and `signal_decision_at` without compacting them away. For any multi-row feature window, a separate hash-bound lineage table should retain every source trade date, `snapshot_id`, `industry_snapshot_id`, and `available_at`; aggregate counts alone are not a substitute for record lineage. Industry may be retained for audit and stratification, but none of the three hypotheses below needs industry as a selector.

Candidate counts are not executable-capacity claims. Every new cohort must still use the frozen next-legal-minute entry and exact K80 replay. The present evidence only shows that K80 does not bind in 2019–2021 for the current cohort, so a new signal on a genuinely new sparse-year date has more capacity value than another name on the 2018 cluster.

## Comparable 2018–2021 funnel

|Version and added economic condition|Candidates|Executable|K80 accepted|Accepted by signal year: 2018 / 2019 / 2020 / 2021|Distinct candidate / executable / accepted signal dates|
|---|---:|---:|---:|---|---|
|V13: first close above the prior completed day's high below untouched L|850|821|670|348 / 128 / 89 / 105|232 / 228 / 226|
|V27: V13 + M20 + F14 + R5|444|426|308|229 / 29 / 16 / 34|84 / 80 / 79|
|V28: V27 + non-ST + at most one prior-20 one-price limit-down|411|394|278|213 / 27 / 13 / 25|71 / 67 / 66|
|V28R1: V28 + signal close not locked at up-limit|397|381|267|204 / 26 / 12 / 25|64 / 60 / 59|
|V28R2: V28R1 + signal amount no more than 2× prior-20 median|370|355|255|198 / 23 / 10 / 24|60 / 56 / 55|

For completeness, the full 2017–2021 development totals are 939 / 908 / 754 for V13 and 470 / 452 / 333 for V27. One V27 signal crosses from signal year 2020 into entry year 2021; therefore the published entry-year counts 15 / 35 for 2020 / 2021 differ from the signal-year counts 16 / 34 above, while the total remains 333.

The executable-to-K80 loss is almost entirely a 2018 congestion phenomenon. In V28R2, all 94 `SKIPPED_CAPACITY` and all 6 `SKIPPED_DUPLICATE_SYMBOL` rows occur in 2018; 2019–2021 have no K80 or duplicate-symbol rejection. Raising K therefore cannot repair sparse-year frequency.

## Where V27 removes the opportunity set

The V27 gates were replayed only as outcome-blind masks on frozen V13 entry identities:

|Signal year|V13 parent|After M20|After M20 + F14|After M20 + F14 + R5|Distinct dates along the same four stages|
|---:|---:|---:|---:|---:|---|
|2018|513|507|405|359|76 / 75 / 44 / 42|
|2019|138|101|53|32|46 / 38 / 18 / 13|
|2020|90|60|31|16|48 / 35 / 17 / 6|
|2021|109|95|68|37|62 / 54 / 41 / 23|
|2019–2021|337|256|152|85|156 / 127 / 76 / 42|

In the sparse 2019–2021 years, M20 removes 81 candidates and 29 dates, F14 then removes 104 candidates and 51 dates, and R5 removes another 67 candidates and 34 dates. Thus F14 is the largest date-coverage bottleneck and R5 is the second. V27 causes 243 of the 265 accepted-trade losses from V13 to V28R2 in those three years; the V28/V28R1/V28R2 quality gates together account for only the remaining 22.

V28's 444-parent to 411-selected reduction consists of 30 repeated one-price-limit-down failures and 4 ST failures with one overlapping identity. V28R1 removes 14 more candidates and V28R2 removes 27. These filters improve demand/executability semantics, but they are not the primary capacity bottleneck.

## Date concentration

- On 2018-10-26, V13 has 171 candidates; M20 retains all 171, F14 retains all 171, and R5 still retains 158. The 2018 cluster is therefore inherited from the market-wide shock, not created by a later quality gate.
- V28R2 accepts 85 trades from that single signal date: 33.33% of all 255 accepted trades and 42.93% of its 2018 accepted trades.
- V28R2's accepted signal-date counts are only 23 / 12 / 4 / 16 in 2018 / 2019 / 2020 / 2021. Six of the ten 2020 accepted trades occur on 2020-02-17.
- 2018 supplies 77.65% of all V28R2 accepted trades. Its apparent 63.75 accepted trades per year is therefore a cross-sectional count from a few crash episodes, not a stable annual event rate.

Portfolio replay after each selector can reallocate K80 slots, so accepted sets need not be strict subsets on congested dates. For example, a stricter child can admit a previously capacity-skipped row after removing a higher-ranked parent row. Candidate attrition, rather than date-level accepted-set subtraction, is the valid selector-bottleneck measure.

## Three bounded expansion hypotheses

### 1. Select the first final-quality recapture, not the first weak reversal

Current ordering freezes the first V13 prior-high reversal for a gap and only afterward applies R5, V28, V28R1, and V28R2. If that early reversal is too small, locked, or abnormally crowded, the gap is discarded even if a later bar inside the same untouched-L/F14 window becomes the first orderly, two-sided recapture.

Change only the state-machine ordering: for each gap, retain at most one signal, but choose the first completed bar that simultaneously satisfies the final V27–V28R2 signal conditions. A failed provisional reversal does not consume the gap identity. This preserves every threshold and has the clearest economic meaning: the event is the first *investable demand recapture*, not merely the first bounce.

Outcome-blind preregistration must bind the exact V13 gap population and daily/minute inputs, define the per-gap re-arm state, retain the untouched-L and F14 clocks, forbid same-bar entry, freeze the selected identities before any outcome join, and disclose candidate/date concentration. The 2019–2021 upper opportunity reservoir is material: 67 identities are lost at R5 and another 25 at later signal-quality gates, although only a fresh Stage A scan can determine how many later qualify.

### 2. Let a renewed sell wave refresh an older gap

Replace F14 with one bounded superset:

`gap_age <= 14 OR (gap_age <= 30 AND days_since_low20 <= 3)`

Economic meaning: the gap is the structural overhead cost zone, while the most recent 20-session low dates the active sell-pressure episode. An older gap remains relevant only when a new sell wave has just made a fresh low and demand immediately reverses it; the 30-session cap prevents indefinite gap memory.

Without reading outcomes, this mask raises 2018–2021 V27 candidates from 444 on 84 dates to 499 on 114 dates. The attached frozen V13 entries show 481 next-minute-executable identities on 110 dates, versus 426 on 80 dates for current V27. In 2019–2021 it raises 85 candidates on 42 dates to 109 on 60 dates, of which 103 are executable on 58 dates. These are pre-K80 capacity figures, not accepted-trade claims. The preregistration must freeze 14, 30, and 3 as economic constants, prohibit sibling-threshold sweeps, and preserve M20, R5, V28–V28R2, exact entry, A67, H20, costs, and K80.

### 3. Remove the absolute R5 distance gate and retain the local seller-level reclaim

V13 already requires at least 10% post-gap maximum depth, signal close still at least 5% below L, a recent-low recovery of at least 3%, and a close above the prior day's high. R5 adds an absolute recovery distance of 5% of L; it is a price-distance threshold, not direct proof of absorption, and it deletes many distinct sparse-year dates.

Change only one condition: remove R5 while retaining the V13 reversal and all V28–V28R2 quality/execution guards. Outcome-blind capacity rises from 444 candidates on 84 dates to 557 on 120 dates in 2018–2021; 533 identities are already next-minute executable on 116 dates, versus current V27's 426 on 80 dates. In 2019–2021 it rises from 85 candidates on 42 dates to 152 on 76 dates, with 142 executable identities on 75 dates. These figures precede the later signal-quality filters and exact K80 replay. This has the largest known capacity but the highest weak-bounce risk, so it should be tested after the composite-first state machine, as an independently frozen development sleeve rather than combined post hoc.

Its preregistration must bind the exact parent identity, name `R5 removal` as the sole selector change, freeze the selected cohort before outcome access, and require the original frequency/mean/holding gates plus signal-date concentration diagnostics. No rescue threshold may be introduced after outcomes are opened.

## Recommended next move

Prioritize hypothesis 1. It fixes a semantic ordering defect without weakening the economic rule. Run only an outcome-blind Stage A first and require it to increase 2019–2021 distinct signal dates, not merely add more names to 2018-10-26. If its capacity remains inadequate, preregister hypothesis 2 next. Hypothesis 3 is the broadest fallback and should carry the strongest concentration disclosure.
