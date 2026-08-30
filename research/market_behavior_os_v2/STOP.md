# Current autonomous STOP

Status: `STOP_UNSAFE_MARKET_MINUTE_REPRESENTATION_SCALE`

AUDIT-MKT-MIN-001 proves exact strategy-independent minute readiness on 240
trajectories and 1,200 five-day sessions across 2018-2023 and four governed
views. It does not provide enough market dates or cross-sectional depth to
establish a market-state representation with the Research OS requirement of 504
causal historical observations per view.

A defensible next experiment must freeze many more anchor dates and a materially
deeper cross-section before computing five-day trajectory roles, PIT
normalization, neighboring-definition stability, and portability. Under the
current rowwise QD-004/CY-008 adapter this implies hundreds of thousands of
session validations and over 100 million one-minute rows. The accepted prior
scale policy explicitly prohibits a full-market minute build, and attempting
this unvectorized expansion would create unsafe memory/runtime risk.

The scale floor is concrete: 504 anchor dates x four views x an illustrative
minimum 50-security cross-section x five sessions x 241 rows equals 121,464,000
trajectory-mapped minute rows before duplicate-view reuse. The scientific
cross-section size still requires a separate frozen contract; this calculation
is a resource lower-bound illustration, not a selected research parameter.

This meets the Research Contract stop boundary `unsafe resource use`. It is not:

- a minute-data contract failure;
- a rejection of any intraday mechanism;
- a request to weaken the 504-observation PIT gate;
- permission to reuse CHINEXT event sampling;
- permission to read outcomes or CY-011.

Resume only after a separately reviewed, vectorized, partition-pruned market-
minute aggregation adapter and a frozen resource budget/sample-size contract
exist. The next scientific action is then an outcome-blind five-day Market
Intraday Representation Map, not an economic-usefulness or strategy test.
