#!/usr/bin/env python3
"""Bull post-first-limit-up inventory lock and relaunch research."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT=Path(__file__).resolve().parents[3]
OS=ROOT/"research/market_behavior_os_v2"
EXPERIMENT="ASHARE-BULL-POST-LIMITUP-INVENTORY-LOCK-RELAUNCH-V33"
EXT=Path("/Volumes/quant/CY_quant_research/ashare_bull_post_limitup_inventory_lock_relaunch_v33")
CONTRACT=OS/f"experiments/{EXPERIMENT}_contract.json";SPEC=OS/f"experiments/{EXPERIMENT}_spec.json";FREEZE=OS/f"artifacts/{EXPERIMENT}_stage_a_freeze.json";PROFILE_FREEZE=OS/f"artifacts/{EXPERIMENT}_profile_freeze.json";RESULT=OS/f"artifacts/{EXPERIMENT}_result.json";REPORT=OS/f"reports/{EXPERIMENT}_report.md"
CANDIDATES=EXT/"stage_a/candidates.parquet";BLIND_INDEX=EXT/"stage_a/blind_index.csv";BLIND_DIR=EXT/"stage_a/blind_charts";BLIND_PDF=ROOT/f"output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf"
DEV_OUTCOMES=EXT/"stage_b/development_outcomes.parquet";FORWARD_OUTCOMES=EXT/"stage_b/forward_outcomes.parquet";PROFILE_TABLE=EXT/"stage_b/profile_table.parquet";ACCEPTED=EXT/"stage_b/portfolio_accepted.parquet";SKIPPED=EXT/"stage_b/portfolio_skipped.parquet";NAV=EXT/"stage_b/portfolio_nav.parquet"
YEARS=tuple(range(2014,2024));DEV_YEARS=tuple(range(2014,2021));FORWARD_YEARS=(2021,2022,2023)
PROFILES={"H5_LOCK_FLOOR_FAILURE":{"horizon":5,"target":None},"H10_LOCK_FLOOR_FAILURE":{"horizon":10,"target":None},"T15_H10_LOCK_FLOOR_FAILURE":{"horizon":10,"target":.15},"T20_H15_LOCK_FLOOR_FAILURE":{"horizon":15,"target":.20}}


class ResearchError(RuntimeError):pass


def contract_value()->dict[str,Any]:
    return {
        "experiment":EXPERIMENT,"stage":"A_OUTCOME_BLIND_CONTRACT",
        "economic_hypothesis":"A first limit-up creates a new holder-cost cohort. If the next 2-15 completed sessions absorb turnover without another limit-up, preserve the first-limit-up body midpoint, and contract volume, a later high-location volume expansion through the shelf high in a PIT bull market and healthy industry represents a second price-discovery auction after weak holders have had time to exit.",
        "four_binding_conditions":{
            "FIRST_LIMITUP_INFORMATION_EVENT":"ignition closes at the historical price limit, exceeds the prior20 high, has no limit-up close in the prior20 completed stock sessions, and the pre-ignition prior20 return is not below -10%",
            "INVENTORY_LOCK_SHELF":"2-15 sessions after ignition; no intervening limit-up; shelf low >=95% of ignition body midpoint; shelf high/low range<=25%; shelf mean turnover<=1.2x ignition turnover",
            "PIT_BULL_AND_HEALTHY_INDUSTRY":"at completed relaunch close, frozen PIT market regime BULL; industry n20>=5, median ret20>0, positive-ret20 share>50%",
            "RELAUNCH_AUCTION":"completed close exceeds every intervening shelf high; signal return +1.5% to +8%; close location>=65%; turnover>=1.1x shelf mean",
        },
        "decision_clock":"completed daily relaunch close","entry":"first legal daily open after signal within three market sessions","profiles":PROFILES,
        "failure_exit":"after T+1, first completed daily close below the frozen ignition body midpoint; exit next legal open","cost":.004,
        "development":{"years":list(DEV_YEARS),"minimum_completed":400,"minimum_positive_years":5,"minimum_mean_net":.03,"maximum_mean_holding_sessions":15},
        "forward":{"years":list(FORWARD_YEARS),"opened_only_after_profile_freeze":True,"2024_q1_use":"late-2023 execution resolution only"},
        "portfolio":v1.contract_value()["portfolio"],"outcomes_opened":False,
    }


def persist_contract()->dict[str,str]:
    v1.write_json(CONTRACT,contract_value());v1.write_json(SPEC,{"experiment":EXPERIMENT,"status":"OUTCOME_BLIND_CONTRACT","contract_sha256":v1.sha256(CONTRACT),"sources":{"daily":v1.sha256(v1.DAILY),"regime":v1.sha256(v1.SOURCE_REGIME),"industry":v1.sha256(v1.INDUSTRY_PANEL)},"execution_dependency_sha256":v1.sha256(Path(v1.__file__))});return {"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC)}


def build_candidates()->pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True,exist_ok=True);con=duckdb.connect()
    con.execute(f"""COPY (
      WITH d0 AS (
        SELECT d.*,lag(coord_close) OVER w AS pre_ignition_close,
          lag(coord_close,20) OVER w AS lag20_coord_close,
          max(coord_high) OVER w20 AS prior20_high,
          count(*) OVER w20 AS prior20_n,
          sum((round(close*100)=round(up_limit_price*100))::INTEGER) OVER w20 AS prior20_limitups
        FROM read_parquet('{v1.DAILY}') d
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
          AND hard_valid AND history_valid AND current_valid
          AND corporate_action_valid AND NOT corporate_action_blocking
          AND current_day_data_tradable AND market_rule_valid AND trade_status=1
          AND NOT is_st AND causal_industry IS NOT NULL AND industry_valid
        WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
          w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
      ), ign AS (
        SELECT *,(coord_open+coord_close)/2 AS ignition_midpoint
        FROM d0 WHERE prior20_n=20 AND prior20_limitups=0
          AND round(close*100)=round(up_limit_price*100)
          AND coord_close>=prior20_high
          AND pre_ignition_close/NULLIF(lag20_coord_close,0)-1>=-0.10
      ), pairs AS (
        SELECT i.symbol,i.sleeve,i.causal_industry,i.trade_date AS ignition_date,
          i.cal_idx AS ignition_cal_idx,i.ignition_midpoint,i.coord_open AS ignition_open,
          i.coord_close AS ignition_close,i.turnover_fraction AS ignition_turnover,
          i.invalid_step_cum AS ignition_lineage,
          s.* EXCLUDE(symbol,sleeve,causal_industry)
        FROM ign i JOIN d0 s ON s.symbol=i.symbol AND s.cal_idx-i.cal_idx BETWEEN 2 AND 15
      ), shelf AS (
        SELECT p.*,count(*) AS shelf_sessions,min(h.coord_low) AS shelf_low,
          max(h.coord_high) AS shelf_high,avg(h.turnover_fraction) AS shelf_mean_turnover,
          sum((round(h.close*100)=round(h.up_limit_price*100))::INTEGER) AS intervening_limitups
        FROM pairs p JOIN d0 h ON h.symbol=p.symbol
          AND h.cal_idx>p.ignition_cal_idx AND h.cal_idx<p.cal_idx
        GROUP BY ALL
      ), joined AS (
        SELECT s.*,r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
          r.latest_source_timestamp AS market_latest_source,
          i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_median_ret60,
          i.industry_n20,i.industry_ret20_percentile,
          i.latest_source_timestamp AS industry_latest_source,
          (s.coord_close-greatest(s.coord_open,s.coord_low))/NULLIF(s.coord_high-s.coord_low,0) AS close_location,
          s.turnover_fraction/NULLIF(s.shelf_mean_turnover,0) AS turnover_expansion
        FROM shelf s JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
          JOIN read_parquet('{v1.INDUSTRY_PANEL}') i USING(trade_date,causal_industry)
      ), selected AS (
        SELECT *,'PLR33-'||strftime(trade_date,'%Y%m%d')||'-'||symbol||'-'||strftime(ignition_date,'%Y%m%d') AS event_id,
          trade_date AS signal_date,decision_at AS feature_latest_timestamp,
          ret20-industry_median_ret20 AS stock_minus_industry_ret20,
          'POST_LIMITUP_INVENTORY_LOCK_RELAUNCH' AS admission_lane,
          row_number() OVER(PARTITION BY symbol,trade_date ORDER BY ignition_date DESC) AS ignition_rank
        FROM joined
        WHERE market_regime='BULL' AND industry_n20>=5 AND industry_median_ret20>0
          AND industry_positive_ret20_share>0.50 AND intervening_limitups=0
          AND shelf_low>=0.95*ignition_midpoint AND shelf_high/NULLIF(shelf_low,0)-1<=0.25
          AND shelf_mean_turnover<=1.2*ignition_turnover
          AND turnover_fraction>=1.1*shelf_mean_turnover
          AND coord_close>shelf_high AND step_return BETWEEN 0.015 AND 0.08
          AND close_location>=0.65
      ) SELECT * EXCLUDE(ignition_rank) FROM selected WHERE ignition_rank=1 ORDER BY trade_date,symbol
    ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)""");con.close()
    x=v1.read_parquet_duckdb(CANDIDATES)
    for col in ("trade_date","signal_date","ignition_date","available_at","decision_at","market_latest_source","industry_latest_source","feature_latest_timestamp"):x[col]=pd.to_datetime(x[col])
    return x


def audit_candidates(x:pd.DataFrame)->dict[str,int|bool]:
    return {"duplicate_event_count":int(x.event_id.duplicated().sum()),"feature_after_decision_count":int(x[["available_at","market_latest_source","industry_latest_source","feature_latest_timestamp"]].max(axis=1).gt(x.decision_at).sum()),"ignition_not_before_signal_count":int(x.ignition_date.ge(x.signal_date).sum()),"intervening_limitup_count":int(x.intervening_limitups.gt(0).sum()),"candidate_after_2023_count":int(x.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),"outcomes_opened":False}


def blind_sample(x:pd.DataFrame,n:int=30)->pd.DataFrame:
    z=x.copy();z["year"]=z.signal_date.dt.year;z["hash_order"]=z.event_id.map(lambda s:hashlib.sha256(str(s).encode()).hexdigest());pieces=[g.sort_values("hash_order").head(3) for _,g in z.groupby("year")];s=pd.concat(pieces,ignore_index=True)
    if len(s)<n:s=pd.concat([s,z.loc[~z.event_id.isin(s.event_id)].sort_values("hash_order").head(n-len(s))])
    s=s.sort_values(["signal_date","symbol"]).head(n).reset_index(drop=True);s.insert(0,"chart_id",[f"V33-BLIND-{i:03d}" for i in range(1,len(s)+1)]);s.to_csv(BLIND_INDEX,index=False);return s


def render_blind(x:pd.DataFrame)->None:
    BLIND_DIR.mkdir(parents=True,exist_ok=True);BLIND_PDF.parent.mkdir(parents=True,exist_ok=True);symbols=pd.DataFrame({"symbol":sorted(x.symbol.unique())});con=duckdb.connect();con.register("symbols",symbols);d=con.execute(f"SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close,turnover_fraction FROM read_parquet('{v1.DAILY}') JOIN symbols USING(symbol) WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31' ORDER BY symbol,trade_date").fetchdf();con.close();d.trade_date=pd.to_datetime(d.trade_date);groups={s:g.reset_index(drop=True) for s,g in d.groupby('symbol')}
    with v1.PdfPages(BLIND_PDF) as pdf:
      for e in x.itertuples(index=False):
        g=groups[e.symbol];p=np.flatnonzero(g.trade_date.eq(e.signal_date).to_numpy())[0];view=g.iloc[max(0,p-109):p+1]
        fig,axes=v1.plt.subplots(2,1,figsize=(11.7,8.3),gridspec_kw={"height_ratios":[2.5,.7]});xx=v1.mdates.date2num(view.trade_date);colors=np.where(view.coord_close.ge(view.coord_open),'#dc2626','#059669');axes[0].vlines(xx,view.coord_low,view.coord_high,color=colors,lw=.6);axes[0].bar(xx,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65)
        axes[0].axvline(e.ignition_date,color='#7c3aed',ls='--',label='first limit-up ignition');axes[0].axvline(e.signal_date,color='#2563eb',ls='--',label='relaunch signal');axes[0].axhline(e.ignition_midpoint,color='#f59e0b',ls=':',label='ignition body midpoint');axes[0].axhline(e.shelf_high,color='#dc2626',ls=':',label='shelf high');axes[0].set_title(f"{e.chart_id} | {e.symbol} | {e.sleeve} | {e.causal_industry}",fontproperties=v1.CJK_FONT);axes[0].legend(fontsize=8,ncol=4);axes[0].grid(alpha=.2)
        axes[1].bar(view.trade_date,view.turnover_fraction,color=colors,width=.75);axes[1].axvline(e.ignition_date,color='#7c3aed',ls='--');axes[1].axvline(e.signal_date,color='#2563eb',ls='--');axes[1].grid(alpha=.2);axes[1].set_ylabel('Turnover')
        fig.text(.01,.01,"Outcome-blind; no post-signal bar. "f"shelf={e.shelf_sessions} sessions; shelf range={e.shelf_high/e.shelf_low-1:.1%}; shelf/ignition turnover={e.shelf_mean_turnover/e.ignition_turnover:.2f}; relaunch turnover={e.turnover_expansion:.2f}x.",fontsize=7);fig.tight_layout(rect=[0,.035,1,1]);pdf.savefig(fig,dpi=150);fig.savefig(BLIND_DIR/f"{e.chart_id}.png",dpi=135);v1.plt.close(fig)


def run_stage_a()->dict[str,Any]:
    hashes=persist_contract();x=build_candidates();audit=audit_candidates(x)
    if any(v for k,v in audit.items() if k!='outcomes_opened'):raise ResearchError(str(audit))
    s=blind_sample(x);render_blind(s);result={"experiment":EXPERIMENT,**hashes,"runner_sha256":v1.sha256(Path(__file__)),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"candidate_count":len(x),"annual_candidate_counts":x.groupby(x.signal_date.dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict(),"unique_signal_dates":int(x.signal_date.nunique()),"maximum_signals_on_one_date":int(x.groupby('signal_date').size().max()),"blind_chart_count":len(s),"audit":audit};v1.write_json(FREEZE,result);return result


def verify_stage_a()->dict[str,Any]:
    freeze=json.loads(FREEZE.read_text());expected={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"runner_sha256":v1.sha256(Path(__file__)),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF)};drift={k:[freeze.get(k),v] for k,v in expected.items() if freeze.get(k)!=v}
    if drift:raise ResearchError(str(drift))
    return freeze


def load_daily(symbols:list[str],through:str)->pd.DataFrame:
    registry=pd.DataFrame({"symbol":sorted(set(symbols))});con=duckdb.connect();con.register('registry',registry)
    if pd.Timestamp(through)<=pd.Timestamp('2023-12-31'):source=f"SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '{through}'"
    else:source=f"SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31' UNION ALL BY NAME SELECT * FROM read_parquet('{v1.DAILY_TAIL}') WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '{through}'"
    x=con.execute(f"WITH d AS ({source}) SELECT d.* FROM d JOIN registry USING(symbol) ORDER BY symbol,trade_date").fetchdf();con.close();x.trade_date=pd.to_datetime(x.trade_date);return x


def build_outcomes(candidates:pd.DataFrame,through:str,output:Path)->tuple[pd.DataFrame,dict[str,int]]:
    daily=load_daily(candidates.symbol.unique().tolist(),through);groups={s:g.reset_index(drop=True) for s,g in daily.groupby('symbol')};rows=[]
    for e in candidates.itertuples(index=False):
      part=groups[e.symbol];sp=np.flatnonzero(part.trade_date.eq(e.signal_date).to_numpy());
      if len(sp)!=1:raise ResearchError(f"missing signal {e.event_id}")
      entry_pos=None
      for pos in range(int(sp[0])+1,len(part)):
        if int(part.iloc[pos].cal_idx)>int(e.cal_idx)+3:break
        if v1.legal_buy(part.iloc[pos],float(e.invalid_step_cum)):entry_pos=pos;break
      for profile,setting in PROFILES.items():
        base={"event_id":e.event_id,"symbol":e.symbol,"sleeve":e.sleeve,"signal_date":e.signal_date,"signal_cal_idx":int(e.cal_idx),"profile":profile,"ignition_midpoint":float(e.ignition_midpoint)}
        if entry_pos is None:rows.append({**base,"status":"NO_LEGAL_ENTRY"});continue
        entry=part.iloc[entry_pos];price=float(entry.coord_open);target=None if setting['target'] is None else price*(1+setting['target']);horizon=int(entry.cal_idx)+setting['horizon'];exit_pos=exit_price=reason=decision_idx=None
        for pos in range(entry_pos+1,len(part)):
          row=part.iloc[pos]
          if not v1.legal_state(row,float(e.invalid_step_cum)):continue
          if target is not None and float(row.coord_high)>=target:exit_pos=pos;exit_price=target;reason=f"TARGET_{int(setting['target']*100)}";decision_idx=int(row.cal_idx);break
          if float(row.coord_close)<float(e.ignition_midpoint):
            decision_idx=int(row.cal_idx)
            for q in range(pos+1,len(part)):
              if v1.legal_sell_open(part.iloc[q],float(e.invalid_step_cum)):exit_pos=q;exit_price=float(part.iloc[q].coord_open);reason='LOCK_FLOOR_FAILURE';break
            break
          if int(row.cal_idx)>=horizon:
            decision_idx=int(row.cal_idx)
            for q in range(pos+1,len(part)):
              if v1.legal_sell_open(part.iloc[q],float(e.invalid_step_cum)):exit_pos=q;exit_price=float(part.iloc[q].coord_open);reason=f"H{setting['horizon']}_TIME_STOP";break
            break
        if exit_pos is None:rows.append({**base,"status":"UNRESOLVED"});continue
        er=part.iloc[int(exit_pos)];gross=float(exit_price)/price-1;rows.append({**base,"status":"COMPLETED","entry_date":entry.trade_date,"entry_cal_idx":int(entry.cal_idx),"entry_price":price,"exit_date":er.trade_date,"exit_cal_idx":int(er.cal_idx),"exit_price":float(exit_price),"exit_reason":reason,"exit_decision_cal_idx":decision_idx,"holding_sessions":int(er.cal_idx)-int(entry.cal_idx),"gross_return":gross,"net_return":gross-.004})
    x=pd.DataFrame(rows)
    for col in ('signal_date','entry_date','exit_date'):x[col]=pd.to_datetime(x[col])
    v1.write_parquet(x,output);return x,{"signal_bar_fill_count":int((x.entry_date.notna()&x.entry_date.le(x.signal_date)).sum()),"t1_same_day_exit_count":int((x.status.eq('COMPLETED')&x.exit_cal_idx.le(x.entry_cal_idx)).sum())}


def metrics(x:pd.DataFrame,target:float|None=None)->dict[str,Any]:
    z=x[x.status.eq('COMPLETED')]
    if z.empty:return {"completed_trades":0,"mean_net":None,"median_net":None,"win_rate":None,"severe_loss10":None,"target_hit_rate":None,"mean_holding_sessions":None,"median_holding_sessions":None}
    reason=None if target is None else f"TARGET_{int(target*100)}";return {"completed_trades":len(z),"mean_net":float(z.net_return.mean()),"median_net":float(z.net_return.median()),"win_rate":float(z.net_return.gt(0).mean()),"severe_loss10":float(z.net_return.le(-.10).mean()),"target_hit_rate":None if reason is None else float(z.exit_reason.eq(reason).mean()),"mean_holding_sessions":float(z.holding_sessions.mean()),"median_holding_sessions":float(z.holding_sessions.median())}


def make_profile_table(o:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for p,s in PROFILES.items():
      x=o[o.profile.eq(p)];annual={str(y):metrics(x[x.signal_date.dt.year.eq(y)],s['target']) for y in DEV_YEARS};means=[v['mean_net'] for v in annual.values() if v['mean_net'] is not None];rows.append({"profile":p,**metrics(x,s['target']),"positive_years":sum(v>0 for v in means),"median_annual_mean_net":float(np.median(means)),"annual_json":json.dumps(annual,sort_keys=True)})
    return pd.DataFrame(rows)


def run_stage_b()->dict[str,Any]:
    stage_a=verify_stage_a();c=v1.read_parquet_duckdb(CANDIDATES)
    for col in ('signal_date','decision_at'):c[col]=pd.to_datetime(c[col])
    dev=c[c.signal_date.dt.year.isin(DEV_YEARS)];o,audit=build_outcomes(dev,'2021-03-31',DEV_OUTCOMES);table=make_profile_table(o);v1.write_parquet(table,PROFILE_TABLE);eligible=table[(table.completed_trades>=400)&(table.positive_years>=5)&(table.mean_net>=.03)&(table.mean_holding_sessions<=15)]
    if eligible.empty:
      result={"experiment":EXPERIMENT,"verdict":"POST_LIMITUP_RELAUNCH_DEVELOPMENT_FAILED","stage_a":stage_a,"profile_table":table.replace({np.nan:None}).to_dict('records'),"development_audit":audit,"forward_years_opened":False};v1.write_json(RESULT,result);return result
    selected=eligible.sort_values(['median_annual_mean_net','mean_net','severe_loss10','mean_holding_sessions'],ascending=[False,False,True,True]).iloc[0];profile=str(selected.profile);v1.write_json(PROFILE_FREEZE,{"experiment":EXPERIMENT,"selected_profile":profile,"development_outcomes_sha256":v1.sha256(DEV_OUTCOMES),"profile_table_sha256":v1.sha256(PROFILE_TABLE),"forward_opened":False})
    fwd=c[c.signal_date.dt.year.isin(FORWARD_YEARS)];fo,fa=build_outcomes(fwd,'2024-03-31',FORWARD_OUTCOMES);chosen=pd.concat([o,fo]).loc[lambda x:x.profile.eq(profile)].merge(c[['event_id','industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion']],on='event_id',validate='one_to_one');accepted,skipped,nav=v1.replay_portfolio(chosen);v1.write_parquet(accepted,ACCEPTED);v1.write_parquet(skipped,SKIPPED);v1.write_parquet(nav,NAV);overall=metrics(accepted.assign(status='COMPLETED'),PROFILES[profile]['target']);annual={str(y):metrics(accepted[accepted.signal_date.dt.year.eq(y)].assign(status='COMPLETED'),PROFILES[profile]['target']) for y in YEARS};portfolio=v1.portfolio_metrics(nav,accepted);concentration=v1.concentration_metrics(accepted);gate={"completed_per_year_gt_50":len(accepted)/10>50,"mean_net_gt_5pct":overall['mean_net']>.05,"mean_hold_lt_15":overall['mean_holding_sessions']<15,"forward_each_positive":all(annual[str(y)]['mean_net'] is not None and annual[str(y)]['mean_net']>0 for y in FORWARD_YEARS),"at_least_8_positive_years":sum(v['mean_net'] is not None and v['mean_net']>0 for v in annual.values())>=8,"max_date_share_le_10pct":concentration['top_signal_date_share']<=.10};verdict='POST_LIMITUP_INVENTORY_LOCK_RELAUNCH_EDGE' if all(gate.values()) else 'POST_LIMITUP_RELAUNCH_FAILED_FORWARD_OR_TARGET';result={"experiment":EXPERIMENT,"verdict":verdict,"selected_profile":profile,"profile_table":table.replace({np.nan:None}).to_dict('records'),"capacity_accepted_completed_trades":len(accepted),"capacity_skips":len(skipped),"completed_per_year":len(accepted)/10,"overall_2014_2023":overall,"annual":annual,"portfolio":portfolio,"concentration":concentration,"gate":gate,"audit":{**audit,**{f'forward_{k}':v for k,v in fa.items()},"profile_selected_before_forward_open":True,"feature_after_decision_count":0,"2024_rows_for_2023_resolution_only":True,"2024_signal_count":0}};v1.write_json(RESULT,result);return result


def main()->None:
    p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
    if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
    elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
    else:p.error('choose --stage-a or --stage-b')


if __name__=='__main__':main()
