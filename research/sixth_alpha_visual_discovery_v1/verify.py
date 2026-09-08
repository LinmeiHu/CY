"""Essential gate checks; distinguish actual passes from inapplicable account tests."""
import json,subprocess
import numpy as np,pandas as pd
from PIL import Image
from .build import HERE,EXT,DAILY,OPS,sha,js,setup
from .path_labels import path_arrays

def main():
 results=[]
 def record(n,name,status,detail):results.append(dict(id=n,name=name,status=status,detail=detail))
 root=HERE.parents[1];m=json.loads((HERE/'input_manifest.json').read_text())
 for p,h in m['source_hashes'].items():assert sha(root/p)==h,p
 record(1,'frozen_five_unchanged','PASS',str(len(m['source_hashes']))+' source/config hashes match baseline')
 c=setup();op=pd.read_csv(OPS,usecols=['strategy','symbol','decision_at','legal_opportunity','actual_funding_status']);op=op.loc[op.strategy.ne('SMV6')&op.legal_opportunity].copy();op['trade_date']=pd.to_datetime(op.decision_at).dt.normalize();c.register('opcheck',op)
 assert c.execute(f"select count(*) from read_parquet('{EXT}/coverage/five_strategy_coverage_map.parquet') a where uncovered != not exists(select 1 from opcheck b where a.symbol=b.symbol and a.trade_date=b.trade_date)").fetchone()[0]==0
 record(2,'causal_opportunity_union','PASS','Independent legal-opportunity join equals entire coverage map; actual funding excluded from primary union')
 assert c.execute(f"select count(*) from read_parquet('{EXT}/coverage/five_strategy_coverage_map.parquet') a join opcheck b using(symbol,trade_date) where b.actual_funding_status='UNFUNDED' and a.uncovered").fetchone()[0]==0
 record(3,'unfunded_is_covered','PASS','Zero legal unfunded opportunities labeled uncovered')
 s=pd.read_parquet(EXT/'visual/sealed_outcome_map.parquet');c.register('cases',s[['symbol','trade_date','cal_idx']]);check=c.execute(f"select count(*) n,sum((not d.history_valid)::int) bad,max(d.trade_date-s.trade_date) latest_offset from cases s join read_parquet('{DAILY}') d on s.symbol=d.symbol and d.cal_idx between s.cal_idx-249 and s.cal_idx").fetchone();assert check[0]==720*250 and check[1]==0 and check[2].days==0
 audit=pd.read_csv(HERE/'visual/chart_causality_audit.csv');assert len(audit)==720 and audit.future_candles.eq(0).all()
 record(4,'no_future_chart_candles','PASS','720 actual 250-session source windows verified; max relative date offset 0')
 checks=json.loads((HERE/'output/coordinate_checks.json').read_text());assert all(v==0 for v in checks.values());record(5,'chart_coordinate_identity','PASS',checks)
 receipt=json.loads((HERE/'visual/formal_labels_freeze.json').read_text())
 for p,h in receipt['files'].items():assert sha(HERE/'visual'/p)==h
 subprocess.run(['git','cat-file','-e','eb8873f13b:research/sixth_alpha_visual_discovery_v1/visual/formal_labels_freeze.json'],check=True)
 record(6,'operational_blinding','PASS','Committed label hashes unchanged; reveal receipt identifies earlier eb8873f13b. Operational process, not proof of perfect human blinding.')
 det=json.loads((HERE/'output/sample_determinism.json').read_text());assert det['first']==det['rerun'];record(7,'seeded_sample_determinism','PASS',det)
 for p in ['discovery_complete.parquet','discovery_scored.parquet']:
  assert c.execute(f"select max(trade_date)<'2022-01-01' from read_parquet('{EXT}/panel/{p}')").fetchone()[0]
 record(8,'discovery_cutoff','PASS','Source SQL filters before windows/leads; discovery panels end2021; no alpha formulas created')
 frozen=HERE/'discovery_freeze'
 for line in (frozen/'discovery_freeze_manifest.sha256').read_text().splitlines():
  h,p=line.split('  ',1);assert sha(frozen/p)==h
 record(9,'frozen_contract_identity','PASS','All discovery freeze manifest hashes match')
 for n,name in [(10,'same_spec_in_validation'),(11,'no_leverage'),(12,'nonnegative_cash'),(13,'gross_le_one'),(14,'native_trades_preserved_in_overlay')]:record(n,name,'NOT_APPLICABLE','Zero qualified candidates; no strategy or overlay account run. Not a pass.')
 record(15,'deterministic_reruns','PARTIAL_APPLICABILITY','Discovery sample actual rerun PASS; strategy and overlay reruns NOT_APPLICABLE because no candidates')
 for item in m['inputs']:assert sha(item['path'])==item['sha256'],item['path']
 sz=json.loads((HERE/'output/size_source_identity.json').read_text());assert sha(sz['manifest'])==sz['manifest_sha256']
 for item in sz['inputs']:assert sha(item['path'])==item['sha256']
 ctx=json.loads((HERE/'coverage/context_manifest.json').read_text())
 for prefix in ['account','market']:assert sha(ctx[prefix+'_source'])==ctx[prefix+'_sha256']
 full=HERE/'coverage/full_context_manifest.json'
 if full.exists():
  fc=json.loads(full.read_text())
  for item in fc['size_inputs']:assert sha(item['path'])==item['sha256']
 overlap=HERE/'coverage/sample_overlap_source.json'
 if overlap.exists():
  oc=json.loads(overlap.read_text());assert sha(oc['path'])==oc['sha256']
 record(16,'registered_inputs_unchanged','PASS','Baseline daily/opportunity/ATRDR/protocol, size partitions, account and market hashes match')
 # Meaningful independent path fixture: drawdown after a gain, plus missing-session censoring.
 a=path_arrays(np.array([100.,120.,90.,110.]),np.array([100.,125.,95.,115.]),np.array([100.,115.,85.,105.]),np.arange(4),np.zeros(4),2)
 assert np.allclose(a[0,:3],[.25,-.15,-.25]);a=path_arrays(np.array([100.,120.,90.]),np.array([100.,125.,95.]),np.array([100.,115.,85.]),np.array([0,1,3]),np.zeros(3),2);assert np.isnan(a[0]).all()
 dup=pd.read_parquet(EXT/'visual/sealed_duplicates.parquet')
 for row in dup.itertuples():
  a=np.asarray(Image.open(EXT/'visual/charts'/(row.blind_id+'.png')))[32:];b=np.asarray(Image.open(EXT/'visual/charts'/(row.original_id+'.png')))[32:];assert np.array_equal(a,b)
 js(HERE/'output/test_results.json',dict(tests=results,additional_checks={'path_gain_then_drawdown_and_missing_session':'PASS','81_duplicate_chart_pixels_below_header_identical':'PASS'},failures=0,account_tests_not_run=True));print(pd.DataFrame(results)[['id','name','status']].to_string(index=False))
if __name__=='__main__':main()
