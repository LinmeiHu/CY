"""Actual raw-daily prefix parent regeneration, without future outcome loading."""
import json
from pathlib import Path
import duckdb
import pandas as pd
from research.shared_capital_v1.build_inputs import ogr_inputs
from research.shared_capital_v1.run_shared_capital_v1 import HERE, sha256


def run():
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    out=HERE/'cache/ogr_prefix_v06';out.mkdir(exist_ok=True)
    cutoff='2021-06-30'
    bounded=out/'daily_prefix.parquet'
    con=duckdb.connect()
    con.read_parquet(str(inputs['daily_hist'])).filter(f"trade_date <= DATE '{cutoff}'").write_parquet(str(bounded))
    con.close()
    prefix=ogr_inputs({**inputs,'daily_hist':bounded},out,parents_only=True)
    full=pd.read_parquet(HERE/'cache/ogr/signals.parquet')
    full=full.loc[full.signal_date.le(cutoff)]
    # All parent decision fields must agree, not merely selected IDs/counts.
    if set(prefix.columns) != set(full.columns):raise ValueError("raw parent prefix schema mismatch")
    columns=sorted(prefix.columns)
    a=prefix[columns].sort_values('gap_id').reset_index(drop=True)
    b=full[columns].sort_values('gap_id').reset_index(drop=True)
    pd.testing.assert_frame_equal(a,b,check_dtype=False)
    pd.DataFrame([{'strategy':'OGR','cutoff':cutoff,'prefix_parents':len(a),'extended_parents_through_T':len(b),'compared_columns':len(columns),'status':'PASS','scope':'RAW_DAILY_REGENERATED_V13_V27_V28_V28R1_V28R2_PARENTS','source_sha256':sha256(inputs['daily_hist']),'prefix_sha256':sha256(bounded)}]).to_csv(HERE/'output/gap_raw_prefix_v06.csv',index=False)
    print('RAW GAP PREFIX PASS',len(a),flush=True)


if __name__=='__main__':run()


def verify_ifcgr_prefix():
    from five_strategy_bundle.strategies.ifcgr import select_issuer_facts
    inputs=json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs']
    prefix=pd.read_parquet(HERE/'cache/ogr_prefix_v06/signals.parquet')
    cutoff='2021-06-30'
    con=duckdb.connect()
    route=HERE/'cache/ogr_prefix_v06/issuer_routes.parquet'
    con.read_parquet(inputs['ifcgr_route_index']).filter(f"causal_available_at <= TIMESTAMP '{cutoff} 23:59:59'").write_parquet(str(route))
    con.close()
    short=select_issuer_facts(prefix,route,Path(inputs['ifcgr_sse_titles']),Path(inputs['ifcgr_szse_titles']))
    extended=select_issuer_facts(prefix,Path(inputs['ifcgr_route_index']),Path(inputs['ifcgr_sse_titles']),Path(inputs['ifcgr_szse_titles']))
    for a,b in zip(short,extended):
        pd.testing.assert_frame_equal(a.reset_index(drop=True),b.reset_index(drop=True))
    expected=pd.read_parquet(HERE/'cache/ifcgr/2018_2021/signals.parquet').loc[lambda f:f.signal_date.le(cutoff)]
    assert set(short[0].gap_id)==set(expected.gap_id)
    pd.DataFrame([{'strategy':'IFCGR','cutoff':cutoff,'raw_parent_count':len(prefix),'kept':len(short[0]),'rejected':len(short[1]),'classified_fact_rows':len(short[2]),'status':'PASS','scope':'REGENERATED_RAW_OGR_PARENTS_PLUS_STRICT_FACT_KNOWLEDGE_PREFIX','pit_grade':'PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE'}]).to_csv(HERE/'output/ifcgr_prefix_v06.csv',index=False)
