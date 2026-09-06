# Strategy Identity Registry

This registry supplies stable human-facing names for strategy candidates. When a
user invokes an alias, resolve it to the machine-readable identity record, then
read the linked frozen contract and current evidence report before describing,
modifying, or evaluating the strategy.

| Canonical Chinese name | Canonical English name | Stable ID | Aliases | Evidence status | Identity record |
|---|---|---|---|---|---|
| A股三路需求路由 V29 | A-Share Three-Route Demand Router V29 | `ATRDR-V29` | 三路需求路由；需求路由V29；ATRDR；A股需求路由 | Iterative causal historical candidate; not pristine external validation | `experiments/ASHARE-THREE-ROUTE-DEMAND-ROUTER-V29_identity.json` |

## Resolution rule

`ATRDR-V29` must always resolve to the frozen
`ASHARE-SIMPLE-REGIME-COMPLEMENTARY-DEMAND-ROUTER-V29` contract at commit
`c12a7fdd269cdc7f240d9de3d0943c609edb5317`. It has three routes: Bear
fast-capitulation demand, Bear slow-supply exhaustion, and simple Bull
participation/industry ignition. Do not call it live-deployable or externally
validated without a separately frozen, untouched prospective evaluation.
