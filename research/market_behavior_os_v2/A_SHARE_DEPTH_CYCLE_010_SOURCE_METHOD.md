# A-share depth cycle 010 — source and method reconciliation

Frozen before cycle-010 forward-outcome access. All 2018–2023 outcomes remain consumed development evidence; this document does not create an independent-confirmation claim.

## Revised momentum / upper-limit overreaction

Primary source: Chenye Liu, Ying Wu, and Dongming Zhu (2022), “Price overreaction to up-limit events and revised momentum strategies in the Chinese stock market,” *Economic Modelling* 114, 105910, <https://doi.org/10.1016/j.econmod.2022.105910>.

Recovered source method:

- sample: Shanghai and Shenzhen A-shares, January 2000–December 2020;
- exclusions: special-treatment/particular-transfer stocks and stocks below CNY 5 at monthly formation; a daily return is missing when the preceding ten trading days do not provide valid prices;
- event: a close at the regulatory upper limit; successive upper-limit closes are one event whose event date is the last session of the run;
- revised measure: sum daily log returns in the estimation period after removing upper-limit-return sessions and their next trading session;
- portfolio clock: sort at the beginning of each month into deciles; the paper reports equal- and value-weighted excess returns;
- published construction range: estimation and holding periods each in 1, 3, 6, 9, 12, 36, and 60 months.

The accessible original-source text did not expose the unique Table-3 estimation horizon or establish which of equal/value weighting is the single “main” convention. That uncertainty is not filled by inference. Cycle 010 therefore labels 12-month formation / 1-month holding / equal weight as a **paper-specified representative primary cell**, not as a verified unique main-table cell. The two predeclared sensitivities are 6-month and 9-month formation with the same one-month holding. All three horizons are in the paper’s published set.

Local institutional translation, frozen before outcomes:

- use the repository’s causal `up_limit_price`/`limit_pct` by symbol and date instead of assuming 10%; missing or invalid rule rows fail closed;
- a run of consecutive upper-limit closes excludes every upper-limit session and the union of their next-stock-trading-session flags, which reduces to the run plus the first session after the run;
- use completed month-end information at 15:00 and earliest next-session open execution;
- require non-ST, tradable, PIT-valid rows, CNY 5 or higher, and the existing CNY 50m prior-20-session average-amount research floor;
- use 20/120/180/240 sessions as the repository’s fixed trading-session translations of 1/6/9/12 months;
- compare conventional and revised scores under identical rows, formation horizon, holding horizon, clock, and equal weighting;
- report top/bottom deciles and top-minus-bottom. The bottom leg is diagnostic, not a deployable short claim.

The local liquidity floor and post-2020 historical board/ST limit rules are deliberate repository-contract adaptations, so the experiment is a source-faithful mechanism replication under our execution universe rather than a literal reconstruction of the paper’s 2000–2020 sample.

## IVOL, MAX, and MIN

Primary source: Xiaoyuan Wan (2018), “Is the idiosyncratic volatility anomaly driven by the MAX or MIN effect? Evidence from the Chinese stock market,” *International Review of Economics & Finance* 53, 1–15, <https://doi.org/10.1016/j.iref.2017.10.015>.

Recovered source method and question:

- inputs include daily/monthly CSMAR returns plus RESSET RMRF, SMB, HML, and WML factors;
- canonical IVOL is factor-residual volatility, not the repository’s existing cross-sectional-median residual proxy;
- MAX and MIN are the prior month’s maximum and minimum daily returns;
- stocks are sorted monthly and future-month returns are examined;
- the paper’s central mechanism challenge asks whether IVOL survives controls for MAX/MIN and whether MAX/MIN survive IVOL.

Registered-data decision:

- CY-006 supplies causal daily returns, historical identities, limits, industries, liquidity, and execution fields;
- the registry does not contain a PIT-safe historical RMRF/SMB/HML/WML panel, and QD-011 fundamentals are not materialized or allowed for alpha;
- therefore `CANONICAL_IVOL_DATA_LIMITED` is mandatory. No market-only or industry-only residual may be called Wan IVOL;
- source-faithful standalone MAX and MIN quintile tests remain feasible and are predeclared at 20 sessions / one future month / monthly clock;
- the Wan two-way IVOL × MAX/MIN matrix and internal-lead mapping are not run because canonical IVOL is absent. Existing Low Idio, Low Vol-of-Vol, and Low Skewness retain their prior proxy classifications unchanged.

## Optional third family

No third family is authorized. The exact left-tail-reversal construction was not recovered from an original source. Canonical residual momentum needs PIT factor history including unavailable PIT fundamentals and remains `DATA_BLOCKED_FOR_CANONICAL_REPLICATION`. No substitute proxy is permitted.
