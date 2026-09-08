"""Final immutable file inventory and explicit completion grades."""
import json,platform,subprocess,sys
from pathlib import Path
import duckdb,numpy,pandas,pyarrow
from .common import HERE,OUT,INV,sha,dump

def entry(p):return dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size)
def run():
    summary=pandas.read_csv(HERE/'scenario_summary.csv');completed=summary[summary.status=='NEWLY_EXECUTED'];assert len(completed)==62
    repeat=json.loads((HERE/'repeat_execution.json').read_text());assert repeat['status']=='PASS' and repeat['accounts']==62 and repeat['source_hash']==sha(HERE/'replay.py')
    for name in ['accounting_checks','share_flow_checks','repeated_execution_checks']:
        d=pandas.read_csv(HERE/(name+'.csv'));assert len(d)==62
    assert json.loads((HERE/'raw_prefix_checks.json').read_text())['status']=='PASS'
    inputs={Path(r['absolute_path']) for r in json.loads((HERE/'input_binding.json').read_text())['files']}
    inputs.add(INV/'CY-006-pit-b-daily-v2-2018-2026-20260821.json')
    binding=json.loads((HERE/'execution_input_binding.json').read_text())
    inputs.update(Path(r['path']) for r in binding['actions'])
    inputs.update(Path(r['path']) for r in json.loads((HERE/'five_strategy_source_index.json').read_text()))
    inputs.add(HERE.parents[1]/'configs/data_asset_registry.json')
    sources=set(HERE.glob('*.py'))|set(HERE.glob('*.sh'))|{HERE/'PROMPT_V2.md',HERE/'SPEC.md',HERE/'input_binding.json',HERE/'execution_input_binding.json',HERE/'scenarios.json',HERE/'official_sources.json',HERE/'action_backfill.csv'}
    outputs={p for p in OUT.iterdir() if p.is_file() and p.suffix in ['.npy','.parquet','.csv','.json'] and p.name!='publication_status.json'}
    for s in completed.itertuples():outputs.update(p for p in (OUT/s.id).iterdir() if p.suffix in ['.parquet','.json'])
    outputs.update(p for p in (OUT/'official_ca').rglob('*') if p.is_file())
    # Archive identities plus all core artifacts, never an entire runtime/environment directory.
    for name in ['provisional_before_legal_submission','provisional_after_upper_cap','provisional_before_universe_correction','provisional_before_preopen_coordinate','provisional_before_industry_history_completeness']:
        for d in (OUT/name).iterdir():
            if d.is_dir():outputs.update(p for p in d.iterdir() if p.suffix in ['.parquet','.json'])
            elif d.suffix in ['.py','.json','.csv','.parquet','.npy']:outputs.add(d)
    dump(HERE/'artifact_manifest.json',dict(inputs=[entry(p) for p in sorted(inputs)],sources=[entry(p) for p in sorted(sources)],outputs=[entry(p) for p in sorted(outputs)],scope='authorized local research inputs and deterministic outputs; no runtime binaries; post-commit publication record excluded'))
    dump(HERE/'runtime_versions.json',dict(python=sys.version,executable=sys.executable,platform=platform.platform(),numpy=numpy.__version__,pandas=pandas.__version__,duckdb=duckdb.__version__,pyarrow=pyarrow.__version__,plot_runtime=str(OUT/'plot_runtime/bin/python')))
    effects=pandas.read_csv(HERE/'correction_effects.csv');changed=effects[(effects.archive=='provisional_before_universe_correction')&(effects.nav_max_abs_delta>1e-8)].scenario.tolist()
    state=dict(ENVIRONMENT_VALID=True,REPO=str(HERE.parents[1]),BRANCH='research/minervini-ashare-clean-ascent-v2',BASE_HEAD='c5e3ec548e93df15f4ef492d2aef2dcdd5063df1',START_HEAD='c5e3ec548e93df15f4ef492d2aef2dcdd5063df1',END_HEAD='resolved after commit in external publication_status.json',TASK_STATUS='COMPLETED_WITH_CONDITIONAL_DATA_GATES',V1_SOURCE_STATUS='NOT_FOUND_IN_AUDITED_GIT_WORKTREES_AND_REGISTERED_ARTIFACTS; APPENDIX_A_NEW_IMPLEMENTATION',V1_RESULTS_REUSED_AND_VERIFIED=0,SAMPLE_PERMISSION_STATUS='CY-006_CONSUMED_2018_2023_ONLY',HISTORY_ACTUALLY_USED='2018-2019 warmup; 2020-2023 cash accounts',NEW_SEALED_VALIDATION_OPENED='NO',FROZEN_FIVE_STRATEGIES_MODIFIED='NO',METHOD_LABEL='MINERVINI_INSPIRED_MECHANICAL_A_SHARE_PROXY',CORE_SCENARIOS_EXPECTED=58,CORE_SCENARIOS_COMPLETED=58,CONDITIONAL_SCENARIOS_MAX=12,CONDITIONAL_SCENARIOS_COMPLETED=4,SCENARIOS_NEWLY_EXECUTED=62,SCENARIOS_VERIFIED_REUSED=0,SCENARIOS_NOT_RUN_WITH_REASON=json.loads(summary[summary.status!='NEWLY_EXECUTED'][['id','status','reason']].to_json(orient='records')),SCENARIOS_INVALIDATED_BY_BUG=dict(superseded_provisional_identities=62,final_invalid_scenarios=0,universe_correction_changed_NAV_count=len(changed),universe_correction_changed_NAV_scenarios=changed,details='correction_effects.csv'),VCP_PIVOT_ASOF_CHECK='PASS_500_ACTUAL_SNAPSHOTS_AND_SYNTHETIC_CASES',TEMPORAL_LEAKAGE_CHECK='PASS_SCOPED_4_RAW_PREFIX_FULL_CROSS_SECTIONS_PLUS_500_PIVOT_PATH; NOT_FULL_PIT_A_CERTIFICATION',PORTFOLIO_ACCOUNTING_CHECK='PASS_62_CASH_AND_SHARE_FLOW_RECONCILIATIONS',EXECUTION_EVIDENCE_GRADE='PIT_B_DAILY_OPEN_PROXY_WITH_OFFICIAL_ACTION_DATES_AND_EXPLICIT_FRACTIONAL_LOWER_BOUND',INDUSTRY_DATA_GATE='PASS_PIT_B_MATCHED_4',CATALYST_DATA_GATE='FAIL_PURPOSE_PERMISSION_AND_FIRST_VERSION_COVERAGE',FUNDAMENTALS_DATA_GATE='FAIL_FIRST_RELEASE_REVISION_LINEAGE',RESEARCH_VERDICT='NO_INCREMENTAL_EDGE',EXECUTION_VERDICT='EXECUTION_FRAGILE',DEPLOYMENT_VERDICT='REJECT',FIVE_STRATEGY_COMPARISON_STATUS='PARTIAL_ALIGNED_RESEARCH_NAV; STOCK_AND_TRADE_DATE_OVERLAP_NOT_ASSESSED',REPORT_PATH=str(HERE/'REPORT.md'),REPRODUCE_COMMAND='bash '+str(HERE/'reproduce.sh')+' verify',TESTS_ACTUALLY_RUN=['23 unittest cases','500 chronological VCP/Path snapshots','4 raw-prefix complete N cross-sections','all 4 feature caches listing-age check','62 cash/share/price/lot/CAP10 audits','62 repeated accounts / 310 byte-identical artifacts'],UNRESOLVED_ISSUES=['PIT-B source archival limits','daily-open queue and opening-volume proxies','hypothetical fractional share allocation lower bound','event regression excludes action paths','no independent sealed validation','catalyst and fundamentals data gates','five-strategy aligned holdings/trades overlap'],COMMIT='resolved after commit in publication_status.json',PUSH='resolved after push and ls-remote in publication_status.json',PUBLICATION_STATUS_PATH=str(OUT/'publication_status.json'),scenario_registry=json.loads(summary.to_json(orient='records')),artifact_manifest_sha256=sha(HERE/'artifact_manifest.json'))
    dump(HERE/'manifest.json',state)
    print('SEALED',len(inputs),'inputs',len(sources),'sources',len(outputs),'outputs',flush=True)
if __name__=='__main__':run()
