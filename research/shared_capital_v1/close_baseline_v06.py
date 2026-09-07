"""V0.6 baseline closure only. Never dispatch P1/P2/P3."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE, ROOT, POLICY, sha256, frozen_hashes
from research.shared_capital_v1.close_baseline_v05 import hash_inputs, select_issuer, compact_accounts
from research.shared_capital_v1 import ca_forensic, native_states_v06, common_p0_v06

START_HEAD='ecb91d9af9d894f228cf3ce15f967e31660a5828'
OUT=HERE/'output'


def module(name,*args):
    print('RUN',name,*args,flush=True)
    log=OUT/f'v06_{name}.log'
    with log.open('w') as stream:
        result=subprocess.run([sys.executable,'-m','research.shared_capital_v1.'+name,*args],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if result.returncode:raise RuntimeError(f'{name} failed: {log}')


def cache_hashes():
    from verify_no_financing import _canonical_hash
    files=list((HERE/'cache').glob('*/*/p0_*.parquet'))+list((HERE/'cache').glob('smv6/*/physical_p0_*.parquet'))+list((HERE/'cache').glob('*/native_continuous/nav.parquet'))
    return {str(p.relative_to(HERE)):_canonical_hash(p) for p in sorted(set(files))}


def verify_inputs():
    previous=pd.read_csv(OUT/'input_hash_verification.csv')
    current=hash_inputs([Path(p) for p in previous.path])
    rows=[dict(path=r.path,expected_sha256=r.after_sha256,actual_sha256=current[r.path],status='PASS' if current[r.path]==r.after_sha256 else 'FAIL') for r in previous.itertuples()]
    for r in pd.read_csv(OUT/'ca_forensic_input_hashes.csv').itertuples():
        actual=sha256(r.path)
        rows.append(dict(path=r.path,expected_sha256=r.sha256,actual_sha256=actual,status='PASS' if actual==r.sha256 else 'FAIL'))
    table=pd.DataFrame(rows).drop_duplicates('path')
    table.to_csv(OUT/'v06_input_hash_verification.csv',index=False)
    if not table.status.eq('PASS').all():raise ValueError('registered input hash drift')
    return len(table)


def evidence(tests,states,p0,deterministic):
    standalone=compact_accounts() # refresh actual adapter/account streams, then restore common P0 table
    standalone.to_csv(OUT/'native_standalone_reconciliation.csv',index=False)
    pd.DataFrame(p0).to_csv(OUT/'p0_reconciliation.csv',index=False)
    baseline=[]
    for strategy in ('ATRDR','MCB','OGR','IFCGR','SMV6'):
        status={'ATRDR':'CORPORATE_ACTION_DATA_MISSING','MCB':'CORPORATE_ACTION_DATA_MISSING','OGR':'CAUSALLY_VALIDATED','IFCGR':'CAUSALLY_VALIDATED_WITH_PIT_B','SMV6':'CAUSAL_BUG_FIXED_AND_REVALIDATED'}[strategy]
        reason={'ATRDR':'600622.SH 2017-06-30 share arrival/tradability unresolved before both segment starts','MCB':'INDEPENDENT blocker 603368.SH 2020-06-24 missing share arrival/tradability; 2018 boundary validated','OGR':'raw daily parent prefix; continuous native account; bounded full action inputs; native account reference passes','IFCGR':'OGR checks plus raw parent/fact prefix and all 50 later PIT-B windows pass; revision history incomplete','SMV6':'native callbacks through common dispatcher match corrected standalone; future-close perturbation remains pass; local platform equivalence unverified'}[strategy]
        baseline.append(dict(strategy=strategy,status=status,reason=reason,common_p0_validated=False))
    pd.DataFrame(baseline).to_csv(OUT/'baseline_integrity_status.csv',index=False)
    adapters=pd.read_csv(OUT/'opportunity_adapter_reconciliation.csv')
    adapters['scheduler']='shared_account.scheduler.run_streams'
    adapters['common_p0_validated']=False
    adapters['status']=adapters.apply(lambda r:'PARTIAL_PREFIX_CORPORATE_ACTION_BLOCKED' if r.strategy in ('ATRDR','MCB') and r.period=='2018_2021' else 'SCHEDULER_INTEGRATED_STANDALONE_RECONCILED',axis=1)
    entries=pd.read_parquet(HERE/'cache/ogr/entries.parquet')
    for i,r in adapters.loc[adapters.strategy.isin(['OGR','IFCGR'])].iterrows():
        selected=pd.read_parquet(HERE/'cache/ogr/signals.parquet') if r.strategy=='OGR' else pd.read_parquet(HERE/'cache/ifcgr'/r.period/'signals.parquet')
        selected=selected.loc[selected.signal_date.between('2018-01-01' if r.period=='2018_2021' else '2022-01-01','2021-12-31' if r.period=='2018_2021' else '2023-12-31')]
        ex=entries.loc[entries.gap_id.isin(selected.gap_id)]
        adapters.loc[i,'NATIVE_ENTRY_REJECTED_COUNT']=int(ex.entry_status.ne('EXECUTABLE_ENTRY').sum())
        assert int(r.PRE_CAPITAL_INTENT_COUNT)==int(r.NATIVE_FUNDED_COUNT+r.CAPITAL_REJECTED_COUNT)
    adapters.to_csv(OUT/'opportunity_adapter_reconciliation.csv',index=False)
    physical=pd.read_csv(OUT/'standalone_virtual_physical_reconciliation.csv')
    physical['scope']='INDEPENDENT_NATIVE_ADAPTER_THROUGH_COMMON_DISPATCHER'
    physical['tolerance_quantity']=1e-8;physical['tolerance_nav_pnl']=1e-6
    pd.concat([physical,pd.DataFrame([dict(strategy='ALL_ACTIVE',period=r['period'],gap=r['gap'],status='NOT_RUN_NATIVE_INITIAL_STATE_UNRESOLVED',common_account=True,scope='FORMAL_COMMON_P0') for r in p0])],ignore_index=True).to_csv(OUT/'virtual_physical_reconciliation.csv',index=False)
    checks=[
        ('30% conversion quantity','PASS','test_conversion_100_to_30_entitlement_nav_and_pro_rata'),
        ('pending entitlement vs tradable quantity','PASS','test_exit_before_or_after_tradable_keeps_entitlement'),
        ('corporate action NAV conservation','PASS','test_conversion_100_to_30_entitlement_nav_and_pro_rata'),
        ('cannot sell pending shares early','PASS','test_exit_before_or_after_tradable_keeps_entitlement'),
        ('future listing info cannot alter past state','PASS_SYNTHETIC_EXPLICIT_TRANSITIONS','test_future_listing_information_cannot_rewrite_prefix'),
        ('multi virtual lot pro rata action','PASS','test_conversion_100_to_30_entitlement_nav_and_pro_rata'),
        ('segment start deterministic','PASS_REACHABLE_STATES_ONLY','v06_deterministic_rerun.csv; native_segment_initial_states.csv'),
        ('per strategy reset/continuation semantics','PASS_REACHABLE_STATES_ONLY','native_segment_initial_states.csv; test_native_boundary_roundtrip_preserves_home_and_inherited_position'),
        ('scheduler chronological ordering','PASS','test_common_p0_actual_stock_adapter_streams_share_one_account'),
        ('same timestamp ordering','PASS','test_scheduler_native_clocks_ties_no_cross_sleeve_and_rerun'),
        ('P0 no cross sleeve funding','PASS_ENGINE_FORMAL_P0_BLOCKED','test_scheduler_native_clocks_ties_no_cross_sleeve_and_rerun'),
        ('physical virtual quantity','PASS_ENGINE_AND_STANDALONE_FORMAL_P0_BLOCKED','virtual_physical_reconciliation.csv'),
        ('physical virtual PNL','PASS_ENGINE_AND_STANDALONE_FORMAL_P0_BLOCKED','test_native_boundary_roundtrip_preserves_home_and_inherited_position; virtual_physical_reconciliation.csv'),
        ('no negative cash','PASS_ENGINE_AND_STANDALONE_FORMAL_P0_BLOCKED','test_starvation_no_financing_and_determinism'),
        ('NaN inf fail','PASS','test_nonfinite_or_negative_lot_state_fails; test_physical_nan_cannot_hide_in_quantity_comparison'),
        ('duplicate/missing dates fail','PASS','test_account_calendar_and_equation_fail_closed'),
        ('ATRDR prefix invariance','PASS_RAW_PATH_PROBES_CONTINUOUS_FULL_PATH_BLOCKED','atrdr_actual_prefix_probes.csv; test_atrdr_historical_prefix_entries_cash_positions_nav'),
        ('SMV6 future close perturbation','PASS','test_future_close_and_unfinished_open_bar_cannot_change_order'),
        ('IFCGR PIT B coverage','PASS_WITH_REVISION_LIMIT','ifcgr_data_coverage.csv; ifcgr_parent_window_coverage.csv; ifcgr_prefix_v06.csv'),
        ('P0 deterministic rerun','PASS_STANDALONE_AND_SYNTHETIC_FORMAL_P0_BLOCKED','v06_deterministic_rerun.csv; test_scheduler_native_clocks_ties_no_cross_sleeve_and_rerun'),
        ('frozen strategy/input hashes','PASS','v06_frozen_hash_verification.csv; v06_input_hash_verification.csv'),
        ('Gap action coverage through 2023','PASS_CAUSAL_CORRECTION','test_registered_gap_action_loader_includes_2023_without_changing_terms; p0_first_differences.csv'),
        ('OGR raw parent prefix','PASS','gap_raw_prefix_v06.csv'),
        ('IFCGR raw parent/fact prefix','PASS_WITH_PIT_B','ifcgr_prefix_v06.csv'),
        ('four formal common P0 comparisons','NOT_RUN','p0_reconciliation.csv'),
        ('mixed coordinate/raw physical symbol','FAIL_CLOSED_NOT_CONVERTED','test_incompatible_price_units_fail_before_cash_mutation'),
    ]
    pd.DataFrame([dict(requirement_id=i+1,requirement=r,status=s,evidence=e) for i,(r,s,e) in enumerate(checks)]).to_csv(OUT/'requirement_test_coverage.csv',index=False)
    status=dict(TASK_STATUS='PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE',ATRDR_CORPORATE_ACTION_DATA_STATUS='DATA_INPUT_MISSING',
        COMMON_SCHEDULER_STATUS='FIVE_ADAPTER_STREAMS_INTEGRATED_STANDALONE_VALIDATED_COMMON_P0_BLOCKED',
        PHYSICAL_VIRTUAL_ACCOUNT_STATUS='ENGINE_AND_STANDALONE_PASS_COMMON_PHYSICAL_PRICE_COORDINATE_CLOSURE_PENDING',
        P0_STATUS='NOT_RUN_NATIVE_INITIAL_STATES_UNRESOLVED',SHARED_SCENARIOS_RUN=0,
        first_blocker='600622.SH missing F025D/share_credit_date and tradability rule',
        remaining_engineering=['mixed native-coordinate/raw-price same-symbol conversion not established','four integrated common P0 independent multi-layer native comparisons not completed'],
        tests=tests,deterministic_files=len(deterministic),START_HEAD=START_HEAD)
    (OUT/'task_status_v06.json').write_text(json.dumps(status,indent=2)+'\n')
    return status


def reports(status):
    reportdir=HERE/'reports';reportdir.mkdir(exist_ok=True)
    states=pd.read_csv(OUT/'native_segment_initial_states.csv')
    table=states[['strategy','period','reset_or_continuation','initial_cash','initial_nav','position_count','validation_status']].to_csv(index=False)
    (reportdir/'native_state_closure.md').write_text('''# 原生初始状态 V0.6

股票 ATRDR/MCB 从 2014 原生账户连续重放。ATRDR 两个正式边界均不可达；缺失字段写 JSON null，绝不以最后有效日状态或重置百万现金替代。MCB 2018 边界已和冻结原生 replay_sleeves 独立对比，2022 被它自己的 603368 公司行动阻塞。

OGR/IFCGR 保留原生 _replay_board 的 2018 账户起点，行情从 2013 预热，2022 延续账户权益。两条连续 2018–2023 账户与独立原生参考现金/NAV/敞口最大差小于 1e-6，2021 截断账户重放与延长回放前缀一致。已重建边界实际均为空仓，这来自回放结果；2022 现金不是 100 万。信号层 Gap 生命周期与 IFCGR 120 天公告窗继续使用原生历史输入，不在边界重置。

SMV6 原生 _run_callbacks 在每个独立区间调用 init，因此保留原生 reset。JSON 保存实际 init 后 context、集合字段类型列表与空持仓；before_trading 仍读取当前日之前的全部已注册历史。该状态是本地原生适配语义，未验证平台等价。

状态哈希覆盖有效标记及所有保存字段，未来 exit_date、最终收益和 outcome status 不作为已知初始状态保存。未解决状态也有文件哈希，但它不是有效账户状态。后续新出现 pending/nontradable 边界必须有完整事件转换凭证才能恢复，当前 P0 启动器拒绝缺失凭证。

```csv
'''+table+'```\n')
    (reportdir/'common_scheduler_accounting.md').write_text('''# 统一调度与账户 V0.6

stock_p0 (ATRDR/MCB)、gap_p0 (OGR/IFCGR)、smv6_physical 均已调用 shared_account.scheduler.run_streams。流产生原生检查点，回调执行时读取实际资金/持仓并提交原生意图，不使用已接受交易作为生产入口。stock/gap 的 stream_only 与 SMV6 callback_stream 可绑定同一个 PhysicalAccount，common_p0_v06 提供四个 P0 启动入口。

按 timestamp → phase → strategy → identity 稳定调度。phase 为边界、公司行动、准备、已触发退出、SMV6 原生开盘回调、其他入场、信号、收盘。股票开盘 09:30/原生目标收盘 15:00，Gap 保留原始 minute bar_end_time，SMV6 保留 before_trading、09:30、14:57 信号及 15:00 尾卖。SMV6 原生开盘 callback 内有先卖后买及成员重置排序，为保留此资金反馈将其作为不可拆的原生批次；P0 下不跨袖融资。此安排未完成跨策略全退出/全入场阶段的共享政策验收，不能据此开放 P1/P2/P3。

真实股票/Gap适配器的四袖合成夹具与单独 SMV6 全段回放分别验证接线。公司行动只实现显式转换的 RECORD_DATE、ACCOUNTING_EFFECTIVE_DATE、SHARE_ARRIVAL_DATE、TRADABLE_DATE，记录日期没有自动变成到账日期。原持仓卖出后，已确认待到账权利保留独立 lot；arrival 后仍可不可卖；tradable 转换才允许出售。该引擎只接受外部逐时点明确证据，600622 的空日期没有接入合成规则。

账户对实际 physical positions 与 virtual lots 分别计算数量和 marked NAV；pending quantity 单独核对；P&L 按已实现及剩余成本独立核验。数量容差 1e-8，NAV/现金/P&L 容差 1e-6。拒绝负现金、非法数量、NaN/inf、缺失/重复交易日；P0 保留各袖现金及 home right，单袖不能借其他袖现金。继承持仓的区间 P&L 以边界市值起算，原始成本另存，不影响原生退出。

仍未闭合的工程：股票是 native coordinate units，Gap 是 raw price/shares，同证券混用必须先证明数量和现金公司行动表示一致；现在冲突会在成交前拒绝，不能把不同价格单位相加后宣称物理持仓通过。SMV6 原生开盘批次的全退出/全入场分阶段共享整合、四套共同 P0 的完整独立多层对账仍未完成。当前实际四套 P0 都在初始状态门前停止，尚无共同账户历史运行。工程欠项与 600622/603368 数据欠项分别列示。
''')
    (HERE/'REPORT.md').write_text(f'''# SHARED CAPITAL BASELINE CLOSURE V0.6

TASK_STATUS = {status['TASK_STATUS']}

本次没有达到 BASELINE_CLOSURE_COMPLETE。600622 公司行动到账/可交易状态仍缺，ATRDR 两段连续初始状态无效；MCB 也有独立的 603368 阻塞。统一调度、合成公司行动与各策略可达初始状态已有实际实现和验证，但跨价格单位物理表示、共享级全退出/全入场阶段与共同 P0 多层对账仍存在工程欠项，不能只报告成数据缺失。

P0 OGR/IFCGR × 2018–2021/2022–2023 均 NOT_RUN_INITIAL_STATE_UNRESOLVED。实际共享场景 0；未运行 P1/P2/P3，未打开新封存验证，未更改冻结策略/政策/退出规则，未推送。

## 600622 的精确结论

现有 CNInfo p_sysapi1139 官方 JSON F025D = null，raw「股份到账日」与 normalized.share_credit_date 也为空，已核对原始 body/receipt/manifest/封存 producer SHA256。2017-06-23 公告、2017-06-29 登记、2017-06-30 除权及派息、转增 30%。available_at/known_at 为 2017-06-24 的日期精度保守知识时点，并非完整历史 revision 流。缺少独立到账、会计股份生效、可交易日期或唯一冻结转换规则。除权日/派息日不代替这些状态。

ATRDR_CORPORATE_ACTION_DATA_STATUS = DATA_INPUT_MISSING。MCB 的 603368.SH 2020-06-24 同样 F025D 为空；它的阻塞不归咎于 ATRDR。

## 独立基线及实际修正

MCB 2018 边界现金/NAV 1,312,987.896579233、空仓，已独立对比原生账户；2022 不可达。OGR/IFCGR 2018 为原生账户起点，2022 延续现金分别 1,110,169.4677651073 / 1,105,177.2081431411，回放证明空仓。SMV6 保留原生每段 init reset，初始现金 100 万、完整历史预热及实际 context。

发现并修正研究适配层遗漏：公司行动输入仍截断 2022-03-31。修正后首个后段 NAV 差异在 2022-04-29，002727.SZ 每股 0.3 现金分红此前被漏掉；后续 301326.SZ 2023-05-18 除权位于信号与入场之间，依原生规则拒绝该笔。OGR/IFCGR 后段重置控制由 45 笔变 44 笔，末值 1,007,359.4066154053 → 1,016,086.3188282596。这是 corrected company action，不是共同 P0 收益。旧控制和修正控制单独保存，不拟合旧 NAV。

OGR/IFCGR 原生连续至 2023 末 NAV 分别 1,128,256.951844012 / 1,123,173.430234658；与独立原生参考差小于 1e-6。OGR 真实 raw daily 截断至 2021-06-30 重建 360 个父信号，与未来扩展输入的历史父信号全字段相同；IFCGR 同一原始父信号+公告知识前缀重建 352 kept / 8 rejected，12,837 条分类事实与扩展输入相同。PIT-B revision 限制保留。SMV6 两段通过统一调度器仍与原生修正回调对账，原未来 close 扰动回归保持通过。

## 测试与剩余门

聚焦及原单元测试 {status['tests']['passed']} passed；真实输入哈希及重跑层摘要见 v06_input_hash_verification.csv、v06_deterministic_rerun.csv。21 项用户要求及额外发现分行保存 requirement_test_coverage.csv，明确区分合成/独立账户通过和正式共同 P0 未运行。冻结策略和政策在本任务 START_HEAD {START_HEAD} 前后保持相同。

数据首阻塞是 600622 的 share_credit_date/F025D 与合法可交易状态。工程首欠项是不同原生价格/数量单位在共同证券下的物理表示，以及保留 SMV6 原生顺序的全退出/全入场整合；不能用 ATRDR 空仓替身绕过。待解决后仍须完整四套 P0 的独立多层比较才可关闭基线。

路径：reports/ca_600622_forensic.md、reports/native_state_closure.md、reports/common_scheduler_accounting.md。精确重跑及非零退出语义见 REPRODUCTION_COMMANDS.md。共享策略参数、HOME_BUDGET、原生费用/退出和 OGR/IFCGR 互斥均未修改。
''')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--regenerate',action='store_true');args=parser.parse_args()
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    if ROOT!=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1') or branch!='research/five-strategy-shared-capital-v1':raise ValueError('invalid environment')
    subprocess.run(['git','merge-base','--is-ancestor',START_HEAD,'HEAD'],cwd=ROOT,check=True)
    before_frozen=frozen_hashes()
    ca_forensic.run()
    print('Verify registered inputs before replay',flush=True);verify_inputs()
    if args.regenerate:
        for strategy in ('ATRDR','MCB','OGR'):module('build_inputs','--strategy',strategy)
    else:
        from research.shared_capital_v1.build_inputs import rebuild_gap_execution
        inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
        rebuild_gap_execution(inputs)
    select_issuer()
    for name in ('stock_p0','gap_p0','smv6_physical','initial_state','native_states_v06','prefix_probe','gap_prefix_v06','gap_action_control_v06'):module(name)
    from research.shared_capital_v1.gap_prefix_v06 import verify_ifcgr_prefix
    from research.shared_capital_v1.smv6_baseline import prefix_audit
    verify_ifcgr_prefix();prefix_audit()
    first=cache_hashes();first_states={p.name:sha256(p) for p in OUT.glob('*_initial_state_20*.json')}
    for name in ('stock_p0','gap_p0','smv6_physical','native_states_v06'):module(name)
    second=cache_hashes()
    deterministic=[dict(path=p,first_sha256=h,second_sha256=second.get(p),status='PASS' if h==second.get(p) else 'FAIL') for p,h in first.items()]
    deterministic += [dict(path='output/'+p,first_sha256=h,second_sha256=sha256(OUT/p),status='PASS' if h==sha256(OUT/p) else 'FAIL') for p,h in first_states.items()]
    pd.DataFrame(deterministic).to_csv(OUT/'v06_deterministic_rerun.csv',index=False)
    if any(r['status']!='PASS' for r in deterministic):raise ValueError('deterministic rerun failed')
    p0=common_p0_v06.run()
    test=subprocess.run([sys.executable,'-m','pytest','-q','research/shared_capital_v1/tests','tests/unit','--basetemp',str(HERE/'cache/pytest_v06'),'--junitxml',str(OUT/'focused_tests_v06.xml')],cwd=ROOT,capture_output=True,text=True)
    (OUT/'v06_focused.log').write_text(test.stdout+test.stderr)
    if test.returncode:raise ValueError('focused tests failed')
    tests=dict(passed=len(ET.parse(OUT/'focused_tests_v06.xml').findall('.//testcase')),failed=0)
    print('Final input and frozen verification',flush=True);count=verify_inputs()
    after_frozen=frozen_hashes()
    if before_frozen!=after_frozen:raise ValueError('frozen source drift')
    pd.DataFrame([dict(path=p,before_sha256=h,after_sha256=after_frozen[p],status='PASS') for p,h in before_frozen.items()]).to_csv(OUT/'v06_frozen_hash_verification.csv',index=False)
    status=evidence(tests,pd.read_csv(OUT/'native_segment_initial_states.csv'),p0,deterministic)
    reports(status)
    manifest=json.loads((HERE/'input_manifest.json').read_text())
    manifest.update(start_head=START_HEAD,current_run_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),evidence_stage='V06_BASELINE_CLOSURE_WITH_EXPLICIT_DATA_AND_ENGINEERING_GATES',common_p0_reconciled=False,consumed_input_count=count,consumed_input_hash_evidence='output/v06_input_hash_verification.csv',all_consumed_inputs_hash_verified=True,corporate_action_forensic='output/ca_forensic_input_hashes.csv',native_continuous_state_evidence='output/native_segment_initial_states.csv',task_status=status['TASK_STATUS'],v06_runtime_hashes={str(p.relative_to(ROOT)):sha256(p) for p in HERE.rglob('*.py') if 'cache' not in p.parts and not any(part.startswith('.') for part in p.relative_to(HERE).parts)},policy_sha256=sha256(POLICY))
    (HERE/'input_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    from research.shared_capital_v1.finalize_v06 import run as finalize
    finalize()
    print(json.dumps(status,indent=2),flush=True)
    return 2


if __name__=='__main__':raise SystemExit(main())
