# Five Strategy Standalone Reproduction V2

## Result

`TASK_STATUS = PARTIAL_COMPLETE`.

The subtree is import-independent and contains no CY runtime imports, Git-object retrieval, or built-in machine paths. MCB is genuinely closed from registered inputs to NAV and passed exact layer reconciliation. ATRDR's previously missing Fast and Slow Bear mother chains were recovered/reconstructed and replayed from registered daily input for 2014–2023; its historical event identities, routed trades and accepted set match exactly. OGR, IFCGR, SMV6 and ATRDR's post-2023 extension are not complete, so this report does not promote the overall task to COMPLETE.

No frozen strategy file or sealed result was modified. No new sealed validation was opened.

## Environment

- Branch: `codex/five-strategy-integration-20260906`
- Start HEAD: `4d9e70794736d1158624c8a58fd62b2cf4a7ce49`
- Starting worktree: clean, branch ahead of origin by two commits
- New production code: only under `standalone/five_strategy_bundle/`
- New large outputs: `/Volumes/quant/CY_quant_research/five_strategy_standalone_v2`

## What was actually run

MCB ran through the public package CLI. Rebuilt row counts were V53 8,760, V64 2,112, V65 2,383, V72 1,904, accepted 1,021 and NAV 2,397. Every configured identity and value comparison passed exactly, including `qty`, `entry_outlay` and `combined_nav`. Ending NAV is 1.9617491025224512.

ATRDR ran from daily PIT data for 2014–2023. The reconstructed OAI mother produced 3,433 exact identities; Fast Bear produced 660 exact V11 outcomes and 550 exact V13R1 accepted trades. The recovered Slow producer reproduced all 2014–2020 mother identities and the completed 2021/2022–2023 cache identities. Frozen V27 Bear routing produced 1,174 exact identities (153 fast, 1,021 slow). V29 Bull produced 2,877 exact mother identities and the combined historical source contained 4,036 exact identities. Shared portfolio acceptance matched all 2,119 historical event identities.

The first ATRDR value difference is confined to tiny floating representations in 2022–2023 Slow rows (maximum observed price delta about `5e-14`); symbol, date, route, entry/exit reason and accepted identity are unchanged. Because the request requires exact value comparison, these layers are not labeled exact PASS. Post-2023 producers are still absent from the standalone closure, so the registered V29 result of 2,898 accepted trades is not claimed reproduced by this package.

## Source archaeology and provenance

One original upstream producer was recovered: the Slow Supply Exhaustion mother screen at commit `c5e3ec548e93df15f4ef492d2aef2dcdd5063df1`. Its candidate SQL was minimally extracted. The original OAI and MCB V53 producer files were not found in reachable branches, tags, logs, reflog, registered worktrees or restored-source locations. They are explicitly marked behavioral reconstructions and were accepted only after whole-interval exact event/key-value comparisons. Downstream V64/V65/V72, V29 Bull, execution and portfolio functions are minimal extracts.

- Recovered original producer modules: 1
- Behavioral reconstruction modules: 2 (OAI mother and MCB V53)
- Mixed minimal-extract modules: 3

The detailed mapping is in `manifests/source_provenance.json`.

## Strategy status

- OGR — `SOURCE_CHAIN_INCOMPLETE`. Zero point is registered PIT daily/minute/amount. The V13→V27→V28→V28R1→V28R2 closure was not bundled; no frozen intermediate is consumed by production code.
- IFCGR — `SOURCE_CHAIN_INCOMPLETE`. Intended zero point is standalone OGR plus registered PIT-B issuer facts. OGR is unavailable and the PIT-B fact adapter is not bundled. The evidence grade remains PIT-B.
- MCB — `FULL_END_TO_END_REPRODUCIBLE`. Zero point is registered daily PIT plus causal completed-close market/industry state. Production frozen-intermediate dependency: NO. Signal/trade/NAV: exact PASS.
- ATRDR — `SOURCE_CHAIN_INCOMPLETE`. Zero point is registered daily PIT. Production frozen-intermediate dependency: NO. Historical 2014–2023 identity closure: PASS. Post-2023 production closure: blocked.
- SMV6 — `SOURCE_CHAIN_INCOMPLETE`. Intended zero point is registered QMT daily plus hybrid critical minute data. The 779-event ledger is never consumed. Frozen callbacks/compatibility layer are not bundled. Native SuperMind equivalence remains UNVERIFIED.

## Commands

```bash
python -m five_strategy_bundle.reproduce --strategy MCB --input-config /path/inputs.json --golden-config /path/mcb-golden.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy ATRDR --input-config /path/inputs.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy OGR --input-config /path/inputs.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy IFCGR --input-config /path/inputs.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy SMV6 --input-config /path/inputs.json --output-root /path/output
```

The last three commands fail closed with `SOURCE_CHAIN_INCOMPLETE`; they are documented to make the missing boundary explicit, not presented as successful reproduction commands.

Focused verification: 4 tests passed, 0 failed (including one real registered-input MCB reproduction test). Style/static checks excluding inherited long SQL lines passed.

## Isolation and split

The isolation test copies only this directory, installs it locally with `--no-deps`, runs tests/firewall, verifies imported module origins, and runs MCB from real registered paths. See `reports/isolation_test.log` for the executed command and result.

```bash
git subtree split --prefix=standalone/five_strategy_bundle -b five-strategy-standalone
```
