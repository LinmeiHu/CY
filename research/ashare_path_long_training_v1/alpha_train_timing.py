"""One source-verified 603880 timing supplement; exact unaffected-prefix check."""
import json
import pandas as pd
from common import HERE,OUT,sha

def validate_asset(p):
 d=HERE/'action_evidence/603880_2018';m=json.loads((d/'source.json').read_text());assert sha(d/'implementation.pdf')==m['pdf_sha256'];assert sha(p)==m['supplemented_asset_sha'];assert sha(d/'original_row.parquet')==m['row_file_sha256']
 f=pd.read_parquet(p);q=f[f.event_id==m['event_id']];assert len(q)==1;assert str(q.iloc[0].share_credit_date.date())==m['tradable_share_release_date'];assert q.iloc[0].row_hash==m['row_hash'];return f

def validate_prefix(policy):
 if policy!='CURRENT_ALPHA_TRAIN_DIAGNOSTIC_ONLY_ROOT_LOW':return
 b=OUT/'account_diversification_v1/alpha_held_risk_v2';history=b/'blocked_timing_603880_v0';meta=json.loads((OUT/'panel/axes.json').read_text());cut=meta['dates'].index('2018-06-20');checked=[]
 for old in history.glob(policy+'_funded_prefix_*.parquet'):
  if old.name.endswith('_lots.parquet'):continue # Mutable terminal lot records are not historical snapshots.
  new=OUT/'accounts'/old.name;a=pd.read_parquet(old);z=pd.read_parquet(new)
  if 't' not in a:continue
  pd.testing.assert_frame_equal(a[a.t<cut].reset_index(drop=True),z[z.t<cut].reset_index(drop=True),check_exact=True);checked.append(old.name)
 assert len(checked)>=8
 (HERE/'account_diversification_v1/alpha_held_risk_v2/TIMING_REPAIR_PREFIX_PARITY.json').write_text(json.dumps(dict(status='EXACT_PASS',before='2018-06-20',tables=checked,source_manifest=str(HERE/'action_evidence/603880_2018/source.json')),indent=2))
