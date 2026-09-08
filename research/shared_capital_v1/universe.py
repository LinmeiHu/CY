"""Freeze registered security membership; never expand a producer's input universe.

This is a preflight assertion, not a replacement signal filter. Frozen source
retains all PIT validity, ST, history, price-limit and route-specific rules.
"""
import json
from pathlib import Path
import duckdb
import pandas as pd
from five_strategy_bundle.strategies.smv6 import raw_pool
from research.shared_capital_v1.run_shared_capital_v1 import HERE, ROOT, sha256

CONTRACT = HERE / 'contracts/strategy_universe_v1.json'


def assert_stock_membership(frame, registry):
    if frame[['symbol', 'sleeve']].isna().any().any():
        raise ValueError('null universe identity')
    pairs = set(map(tuple, frame[['symbol', 'sleeve']].drop_duplicates().to_numpy()))
    allowed = {(r['symbol'], r['sleeve']) for r in registry}
    if not pairs <= allowed:
        raise ValueError(f'outside frozen registered universe: {sorted(pairs-allowed)[:5]}')


def run():
    config = json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    path = Path(config['daily_hist'])
    con = duckdb.connect()
    registry = con.execute('SELECT DISTINCT symbol,sleeve FROM read_parquet(?) ORDER BY symbol,sleeve', [str(path)]).fetchdf()
    con.close()
    if registry.symbol.duplicated().any() or not set(registry.sleeve) == {'MAIN','CHINEXT'}:
        raise ValueError('registered universe board ambiguity')
    members = registry.to_dict('records')
    common = dict(security_type='STOCK', exchange='SSE;SZSE', board='MAIN;CHINEXT',
        included='Exact registered symbol/sleeve pairs; PIT eligibility remains native',
        excluded='STAR;BEIJING;ETF;B_SHARE;unregistered symbols',
        time_dependence='Per-date registered current_valid/history_valid/hard_valid and native completed-history gates; registry is a superset, not same-day eligibility',
        ST_rule='Excluded at native signal eligibility; no additional liquidation/filter added',
        suspension_rule='Native tradability/status gates; no invented sale',
        price_limit_rule='Registered PIT price limits and native raw-cent comparison; no constant board limit substituted',
        special_security_rule='Registered historical_identity_valid and native action validity; no extra screen',
        notes='Board scope is enforced by pinned input and MAIN/CHINEXT account loops. Some signal builders do not filter boards themselves; broadening input would change frozen economics.')
    routes = [
        ('ATRDR','BULL','atrdr.py','build_simple_bull','Native current_valid/hard_valid, lag60 and prior20 feature history; no added listing-age threshold'),
        ('ATRDR','FAST_BEAR','atrdr.py','build_oai_mother;select_fast_bear','20 preceding valid rows and unchanged lineage; no added listing-age threshold'),
        ('ATRDR','SLOW_BEAR','atrdr.py','build_slow_mother;route_v27_bear','60 preceding valid rows, exact cal_idx continuity and lineage; strict Bear execution requires zero action events'),
        ('MCB','V72','mcb.py','build_v53;build_v65;build_v72','Native prior20 and ret60 validity; no added listing-age threshold'),
        ('OGR','V28R2','ogr.py','build_all_true_gaps;build_v13_candidates;select_v28;replay_portfolio','120 valid pre-gap rows plus native lifecycle; non-ST applied at V28 signal, not all historical bars'),
        ('IFCGR','V29R2','ifcgr.py','select_issuer_facts','Exactly OGR parent including V28 non-ST gate; issuer facts may reject only'),
    ]
    rows=[]
    for s,r,f,fn,new in routes:
        rows.append(dict(common,strategy=s,route=r,universe_source_file='src/five_strategy_bundle/strategies/'+f,
                         universe_source_function=fn,new_listing_rule=new))
    rows.append(dict(strategy='SMV6',route='CI',security_type='ETF',exchange='SSE;SZSE',board='ETF',
        included='Frozen 152 raw codes intersect get_all_securities(etf); frozen static fallback on security-list failure',
        excluded='All stock symbols; ETFs outside frozen pool',universe_source_file='src/five_strategy_bundle/strategies/smv6_frozen.py',
        universe_source_function='init;get_active_pool',time_dependence='Local ShadowPlatform.get_all_securities: list_dates <= current_date; native completed history and availability',
        ST_rule='No stock ST rule',new_listing_rule='Active ETF listing + native completed history; static fallback is explicitly preserved',
        suspension_rule='Native minute availability and positive volume',price_limit_rule='Sealed local ETF execution contract',
        special_security_rule='000852.SH is signal anchor only; 588xxx ETFs are permitted funds, not STAR stocks',notes='LOCAL_SEMANTICS_REPLAY; native SuperMind equivalence UNVERIFIED'))
    sources = sorted({r['universe_source_file'] for r in rows} | {'src/five_strategy_bundle/strategies/smv6.py','src/five_strategy_bundle/execution/daily.py','configs/frozen/atrdr_v29.json','configs/frozen/mcb_v72.json','manifests/strategy_identity.json'})
    contract=dict(version='STRATEGY_UNIVERSE_V1',status='FROZEN_REGISTERED_SCOPE',scope='2013 warmup through 2023 only',
        stock_input=dict(path=str(path),sha256=sha256(path),members=members),etf_raw_pool=raw_pool(),
        source_hashes={f:sha256(ROOT/f) for f in sources},routes=rows,
        discrepancies=['README broad A-share label omits ETF and input board restriction.',
                       '302132.SZ is present as CHINEXT in registered historical data; preserve exact registered identity, do not replace with prefix guessing. This is input identity, not a new board.'])
    if CONTRACT.exists() and json.loads(CONTRACT.read_text()) != contract:
        raise ValueError('frozen universe drift; do not silently rewrite')
    CONTRACT.write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
    pd.DataFrame(rows).to_csv(HERE/'output/strategy_universe_audit.csv',index=False)
    print(f'Universe frozen: {len(members)} registered stock identities, {len(raw_pool())} ETFs')
    return contract


def verify(*, execution_hardening=None):
    contract=json.loads(CONTRACT.read_text())
    overrides = {} if execution_hardening is None else json.loads(Path(execution_hardening).read_text())
    if set(overrides) - {'src/five_strategy_bundle/execution/daily.py'}:
        raise ValueError('execution hardening cannot override frozen alpha/universe sources')
    for f,h in contract['source_hashes'].items():
        actual = sha256(ROOT/f)
        if actual != h:
            repair = overrides.get(f, {})
            if repair.get('parent_sha256') != h or repair.get('corrected_sha256') != actual:
                raise ValueError('frozen universe source changed: '+f)
    if sha256(Path(contract['stock_input']['path'])) != contract['stock_input']['sha256']:
        raise ValueError('frozen universe input changed')
    return contract


if __name__=='__main__':run()
