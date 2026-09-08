"""Source-based boundary contract and identity gate, before full outcome replay."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import pandas as pd
from .audit import HERE, ROOT, PARENT, sha256, write_json, frozen_ranking

SHARED=ROOT/'research/shared_capital_v1'
COMPONENTS=['positions','cash','cooldown','pending_membership','ranking_history','callback_state','execution_state','corporate_action_state','market_industry_state','scaling_account_state']


def definitions():
    rows=[]
    for strategy in ['ATRDR','MCB','OGR','IFCGR','SMV6']:
        stock=strategy in ['ATRDR','MCB']; etf=strategy=='SMV6'
        for component in COMPONENTS:
            initial=('Exact registered native 2014-2017 continuation snapshot' if stock else
                     'Native 2018 origin, flat, original cash/board state' if not etf else
                     'Native init once, 1,000,000 cash, flat; registered prior history available')
            rows.append(dict(strategy=strategy,state_component=component,initialization_2018=initial,
                segmented_2022=('Independent research interval: fresh PhysicalPlatform and init; cash 1,000,000, flat, prev_trade_date None' if etf else
                                'Reload independently produced native continuous 2022 boundary state; scaled book is initialized from parent state, not inherited scaled holdings'),
                continuous_2022='Carry actual account and all live adapter state through the calendar boundary; no reinit',
                reset_classification='RESEARCH_SEGMENT_ONLY',
                native_reset_conditions=('before_trading clears only native daily one-shot/pending execution queues; native rebalance/exit updates membership; no annual init' if etf else
                                         'Native event exit/cooldown expiry, actual corporate-action application/release; no calendar-year reset'),
                economic_justification='Calendar segmentation is an experiment boundary, not a strategy instruction to replace economic ownership or cash',
                source=('research/shared_capital_v1/native_states_v06.py:109-117; src/five_strategy_bundle/strategies/smv6.py:416; research/shared_capital_v1/smv6_physical.py:103; src/five_strategy_bundle/strategies/smv6_frozen.py:1825' if etf else
                        'research/shared_capital_v1/native_states_v06.py:64-107; research/shared_capital_v1/common_p0_v06.py:39-70; research/shared_capital_v1/'+('stock_p0.py' if stock else 'gap_p0.py'))))
    return dict(version='ROLLFORWARD_PROTOCOL_DISTINCTION_V1',protocols=['SEGMENTED_RESEARCH_PROTOCOL','CONTINUOUS_LIVE_PROTOCOL'],states=rows,
                scope='Source-based research account; live continuity semantics do not establish native platform equivalence or production readiness')


def matrix():
    rows=[]
    universe=json.loads((PARENT/'contracts/capital_scaling_policy_v1.json').read_text())['universes']
    for strategy in universe:
        adapter='stock_p0.py' if strategy in ['ATRDR','MCB'] else 'smv6_physical.py' if strategy=='SMV6' else 'gap_p0.py'
        for item in ['universe','eligibility','feature_source','market_state','industry_state','costs','execution_timing','position_membership','cooldown','native_exit','corporate_actions','full_book_scaling']:
            source=SHARED/adapter
            note='Same frozen producer and physical adapter; temporal extension only'
            legacy='EXACT'; corrected='EXACT'
            if item=='universe':source=PARENT/'contracts/capital_scaling_policy_v1.json';note=universe[strategy]
            if item=='costs':source=PARENT/'contracts/capital_scaling_policy_v1.json';note='Stock fractional shares 20bp/side; ETF 100-share lot, 2bp commission + 8bp slippage, 50% per-order minute volume cap'
            if item=='full_book_scaling':source=PARENT/'scaling.py';note='Same Scaling class; native event triggers and causal independent Native HOME; no calendar rebalance or target changes'
            if strategy=='MCB' and item=='eligibility':
                legacy='BUG';source=HERE/'snapshot.py';note='Original industry_snapshot_id IS NOT NULL restored; original manifest/inventory files and PIT notice lag verified; no causal_industry fallback'
            if strategy in ['MCB','ATRDR'] and item in ['feature_source','industry_state']:
                legacy='BUG';source=HERE/'snapshot.py';note='59,392 valid rows from 2026-08-14 had coarse taxonomy; restored original Eastmoney snapshot backward ASOF and rebuilt dependent features; original snapshot vintage carried after Aug 13'
            if strategy=='SMV6' and item in ['position_membership','execution_timing','market_state']:
                corrected='AUTHORIZED_CONTINUOUS_STATE_CARRY';source=HERE/'boundary.py';note='Same callback clocks/rules; init once. Full callback carry including prev_trade_date changes 2022 week-boundary decision; source-defined protocol difference'
            if strategy=='MCB' and item=='position_membership':
                corrected='AUTHORIZED_CONTINUOUS_STATE_CARRY';source=HERE/'accounts.py';note='Continuous confirmation_tag retains its own historical cash/positions; segmented parent reloads independent native 2022 stock state. This was specified before outcomes in rollforward protocol state definitions'
            if item=='corporate_actions':
                source=SHARED/'shared_account/held_actions.py';note='Same held action engine and registered actual pay/release facts; extended official action registry. No inferred sellability'
            if strategy=='IFCGR' and item in ['eligibility','feature_source']:
                note='Same frozen OGR-parent issuer classifier and 120-day information rule; bound official-source PIT-B coverage; strict historical revision archive incomplete'
            rows.append(dict(strategy=strategy,item=item,legacy_status=legacy,status=corrected,source=str(source),source_sha256=sha256(source),evidence=note,resolution='SOURCE_IDENTICAL_OR_EXPLICIT_PROTOCOL_CARRY'))
    frame=pd.DataFrame(rows)
    frame.to_csv(HERE/'output/continuous_runtime_identity_matrix.csv',index=False)
    return frame


def selection():
    actual=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
    expected=frozen_ranking(pd.read_csv(PARENT/'output/scenario_summary.csv'))
    fields=['gap','mcb_mode','target']
    assert actual[fields].to_dict('records')==expected[fields].to_dict('records')
    actual['ranking_source_period']='2018-01-01/2021-12-31'
    actual['ranking_metric']='CAGR descending; original deterministic tie keys'
    actual['selection_timestamp']='NOT_RECORDED_IN_ORIGINAL_PRODUCER'
    actual['selection_evidence']='Frozen original CSV and producer bytes registered at f4ebf924; no claim selection was sealed before later years existed'
    actual['source_sha256']=sha256(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
    actual['status']='PASS'
    actual.to_csv(HERE/'output/top_combination_selection_identity.csv',index=False)


def reports():
    trace=json.loads((HERE/'output/smv6_boundary_trace.json').read_text())
    rows=[]
    for label in ['segmented','continuous']:
        data=trace[label]
        for r in data['rows']:
            if r['phase'] in ['BEFORE_PREPARE','AFTER_CLOSE'] and '2022-01-04' in r['timestamp']:
                rows.append(f"|{label}|{r['phase']}|{r['cash']:.6f}|{r['nav']:.6f}|{r['gross']:.6f}|{json.dumps(r['positions'])}|")
    (HERE/'reports/smv6_2022_boundary_protocol.md').write_text('''# SMV6 2022 边界协议

结论：RESEARCH_SEGMENT_ONLY。冻结策略没有 2022-01-01 或年度 init 规则。`smv6.py:_run_callbacks` 和 `smv6_physical.py:callback_stream` 均在一次运行的日历循环之前调用 init；`native_states_v06.py:109–117` 为两个研究区间各创建一次平台，这才导致第二次初始化。连续运行必须携带所有状态。

`smv6_frozen.py:168` 初始化 prev_trade_date=None；651–669 的 is_new_trading_week 对 None 返回 False，否则比较 W-FRI 周。725–806 在 before_trading 更新 prev_trade_date 之前计算市场条件；1825–1879 仅进行策略原生每日队列重置。全年重置没有源码依据。

原始回调实跑结果（元；逐阶段完整 context、desired 与 pending 在 output/smv6_boundary_state.csv 和 trace.json）：

|协议|阶段|cash|NAV|gross|positions|
|---|---|---:|---:|---:|---|
'''+ '\n'.join(rows)+'''

连续账户带入 2021-12-31 的 prev_trade_date，1 月 4 日是新交易周。HS300 ETF 前收 4.589 低于 MA20 4.6199，weekly_exit=True；日紧急阈值 4.5275 尚未触发。周退出使 entry_permission=False。分段 prev_trade_date=None 导致 weekly_exit=False，而 CSI1000 的 entry gate 为 True，于是 desired=['159865.SZ']，CAP50_SET 买入 554,300 股，收盘持仓 519,933.40。

分类：现金 260,255.978086 元差为 SEGMENT_RESET_EFFECT；周边界与许可差为 CALLBACK_STATE_EFFECT；后续订单/持仓差为 EXECUTION_STATE_EFFECT。开盘前两边均空仓，因此 POSITION_CARRY_EFFECT 在此边界为零；注册历史数据相同，RANKING_HISTORY_EFFECT 为零。不存在 UNKNOWN，也不把合法连续状态定性为 BUG。逐日运行与旧连续 Native/父分段参考最大 NAV 误差分别为 4.66e-10 元/0。

这些结果只解释 2022-01-04 的状态，不声称解释任何后续年度盈亏。local SMV6 仍未证明原生 SuperMind 平台完全等价。
''')
    (HERE/'reports/legacy_rollforward_deprecation.md').write_text('''# LEGACY_ROLLFORWARD_IDENTITY_MISMATCH

原图及原报告保留在 evidence 原始来源索引记录的父工作区，快照与 SHA256 继续绑定。它们属于历史审计对象，不能作为 AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1 的结果引用；本任务的新图另命名。

旧连续状态携带本身符合本次明确的连续协议。旧结果不权威的运行时原因是 MCB 快照资格被替换，以及发现的 2026-08-14 起行业分类源切换。补回同一个 manifest 的 snapshot_id 并恢复原分类后必须重跑；不能仅改图标题。各项年度效果需受控分解，累计差额不能随意全归给某一项。
''')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');args=parser.parse_args()
    definition=definitions();write_json(HERE/'contracts/rollforward_protocol_v1.json',definition)
    frame=matrix();selection();reports()
    if not args.freeze:return
    prefix=pd.read_csv(HERE/'output/new_top5_prefix_identity.csv')
    assert len(prefix)==5 and prefix.status.eq('PASS').all() and prefix.days.eq(973).all()
    from .closure_checks import assert_json_close
    from .accounts import folder,group_cases
    selected=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
    for case,old in zip(group_cases('identity_prefix'),selected.itertuples(index=False)):
        actual=json.loads((folder(*case)/'account.json').read_text())
        expected=json.loads((Path(old.source)/'account.json').read_text())
        for key in ['positions','pending_positions']:
            assert_json_close(actual[key],expected[key])
    signals=pd.read_csv(HERE/'output/stock_signal_prefix_identity.csv');assert signals.historical_prefix.eq('PASS').all()
    proof=json.loads((HERE/'output/mcb_snapshot_source_proof.json').read_text());assert proof['coverage_status']=='PASS'
    assert not frame.status.isin(['BUG','DATA_MISSING']).any()
    contract=dict(version='AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1',account_protocol='CONTINUOUS_LIVE_PROTOCOL',start='2018-01-01',end='2026-09-04',
        definition=definition,state_carry='All actual ownership, cash, native adapter/callback/cooldown/history/pending/CA states and scaling desired book; no calendar boundary reinitialization',
        warmup='Exact parent 2018 initial states; stock native account history from 2014, Gap 2018 origin, SMV6 all registered completed daily history; existing prior corporate-action state',
        original_policy_sha256=sha256(PARENT/'contracts/capital_scaling_policy_v1.json'),
        initial_state_hashes={p.name:sha256(p) for p in sorted((SHARED/'output').glob('*initial_state_2018.json'))},
        source_input_binding=sha256(HERE/'account_run_input_identity.json'),industry_snapshot=proof,
        native_sizing='Causal independent continuous Native pre-capital requests/HOME before funding; actual scaled physical state drives decisions and fills',
        costs='Exact parent costs, legal clocks, tradability, inventory, native exits, Full Book and MCB mode rules',
        forbidden=['year as feature','post-outcome alpha changes','new exit','new universe','new gross target','new DD gate','financing','post-2021 Top reselection'],
        economic_outcome_policy='POST_HOC_DIAGNOSTIC_NOT_NEW_SEALED_VALIDATION',native_platform_equivalence='UNVERIFIED',freeze_basis='Frozen source and pre-2022 identity checks only')
    path=HERE/'contracts/continuous_rollforward_protocol_v1.json'
    if path.exists():
        assert json.loads(path.read_text())==contract,'FROZEN_CONTINUOUS_PROTOCOL_DRIFT'
    else:
        write_json(path,contract)
        write_json(HERE/'contracts/continuous_protocol_freeze_receipt.json',dict(sha256=sha256(path),frozen_at=datetime.now(timezone.utc).isoformat(),outcome_bearing_continuous_runs_started=False))
    print('CONTINUOUS_PROTOCOL_FROZEN',sha256(path),flush=True)


if __name__=='__main__':main()
