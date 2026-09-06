#!/usr/bin/env python3
"""Broad-accumulation bull regime plus laggard-support rotation.

V41 is a confirmatory translation of an explicitly outcome-observed 2014-2020
hypothesis-formation audit.  The frozen 2021-2023 extension is the first
chronological test of this exact rule.  Every signal feature is known at the
completed signal close; entry is at a later legal open.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1


ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BROAD-ACCUMULATION-LAGGARD-SUPPORT-V41"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_broad_accumulation_laggard_support_v41")

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
FORWARD_FREEZE = OS / f"artifacts/{EXPERIMENT}_forward_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

DEVELOPMENT_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
ALL_YEARS = tuple(range(2014, 2024))
TARGET = 0.15
HORIZON = 15
K_PER_SLEEVE = 30
MAX_NEW_PER_SLEEVE_DATE = 10
ENTRY_COST = 0.002
EXIT_COST = 0.002


class ResearchError(RuntimeError):
    """Fail closed on semantic, PIT, execution, or lineage drift."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "research_status": (
            "2014-2020 is disclosed hypothesis formation after outcome inspection; "
            "2021-2023 is the frozen chronological extension"
        ),
        "economic_hypothesis": (
            "A bull market is most supportive when gains are broad enough that more than 90% "
            "of stocks are above their 20-session cost reference, while the cross-sectional "
            "median 20-session gain remains bounded.  Positive 60- and 120-session trends reject "
            "short bear-market rebounds.  In that broad accumulation state, capital can rotate "
            "toward a healthy-industry laggard whose own long trend remains intact near overhead "
            "price support and whose signal day is an orderly pause rather than a momentum chase."
        ),
        "independence": (
            "No downward gap, collapse-zone, true-gap repair, V6/V7/V26 identity, feature, or outcome is used."
        ),
        "binding_conditions": {
            "BROAD_ACCUMULATION_BULL": (
                "at completed signal close: market positive-ret20 share>90%; market median ret20 "
                "in (0%,20%]; market median ret60>5%; positive-ret60 share>60%; market median "
                "ret120>5%; positive-ret120 share>55%"
            ),
            "HEALTHY_PIT_INDUSTRY": (
                "signal-close PIT industry has >=5 valid members, median ret20>0, and positive-ret20 share>60%"
            ),
            "RELATIVE_LAGGARD_WITH_INTACT_SUPPORT": (
                "signal-close ret20 industry percentile<=40%; prior completed 60-session return>5%; "
                "prior close no more than 10% below the prior60 high"
            ),
            "ORDERLY_PAUSE": "completed signal-session return is between -5% and +3%",
        },
        "decision_at": "completed signal-session close",
        "entry": "first legal daily open after signal within three exchange sessions",
        "entry_rank": [
            "higher industry positive-ret20 share",
            "higher prior completed 60-session return",
            "closer prior close to prior60 high",
            "event_id",
        ],
        "profit_target": "+15% coordinate target, standing only from the first T+1-sellable session",
        "failure_stop": "none",
        "time_stop": "H15 decision followed by the next legal daily open",
        "round_trip_cost": 0.004,
        "portfolio": {
            "Main_sleeve": 0.50, "ChiNext_sleeve": 0.50,
            "K_per_sleeve": K_PER_SLEEVE,
            "maximum_new_positions_per_sleeve_date": MAX_NEW_PER_SLEEVE_DATE,
            "position_size": "1/K of current sleeve NAV", "unused_capital": "cash",
            "leverage": False, "cross_sleeve_transfer": False,
            "same_symbol_overlap": "forbidden",
            "intraday_target_cash_reuse": "not available for same-day opening entries",
        },
        "chronology": {
            "hypothesis_formation": list(DEVELOPMENT_YEARS),
            "frozen_forward": list(FORWARD_YEARS),
            "2024_q1": "execution resolution for late-2023 entries only after forward freeze",
            "2024_plus_signal_or_feature": False,
        },
        "required_gate": {
            "2014_2023_capacity_accepted_completed_trades_per_year_gt": 50,
            "mean_net_return_gt": 0.05,
            "mean_holding_sessions_lt": 15,
            "each_2021_2023_mean_positive": True,
            "top_five_signal_date_positive_pnl_share_le": 0.25,
            "mean_excluding_best_five_signal_dates_positive": True,
        },
        "outcomes_opened": False,
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "FROZEN_BEFORE_2021_2023_FORWARD_EXTENSION",
            "contract_sha256": v1.sha256(CONTRACT),
            "source_hashes": {
                "daily_2013_2023": v1.sha256(v1.DAILY),
                "daily_tail": v1.sha256(v1.DAILY_TAIL),
            },
            "execution_dependency_sha256": v1.sha256(Path(v1.__file__)),
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(); con.execute("PRAGMA threads=6")
    try:
        con.execute(
            f"""
            COPY (
              WITH d0 AS (
                SELECT d.*,
                  lag(coord_close) OVER w AS prev_coord_close,
                  lag(coord_close,60) OVER w AS lag60_coord_close,
                  max(coord_high) OVER w60 AS prior60_high,
                  count(*) OVER w60 AS prior60_n
                FROM read_parquet('{v1.DAILY}') d
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL AND industry_valid
                  AND historical_identity_valid AND industry_snapshot_id IS NOT NULL
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
                  w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
              ), market_state AS (
                SELECT trade_date,count(*) AS market_n,
                  median(ret20) FILTER(WHERE ret20 IS NOT NULL) AS market_median_ret20,
                  avg((ret20>0)::INT) FILTER(WHERE ret20 IS NOT NULL) AS market_positive_ret20_share,
                  median(ret60) FILTER(WHERE ret60 IS NOT NULL) AS market_median_ret60,
                  avg((ret60>0)::INT) FILTER(WHERE ret60 IS NOT NULL) AS market_positive_ret60_share,
                  median(ret120) FILTER(WHERE ret120 IS NOT NULL) AS market_median_ret120,
                  avg((ret120>0)::INT) FILTER(WHERE ret120 IS NOT NULL) AS market_positive_ret120_share,
                  max(decision_at) AS market_latest_source
                FROM d0 GROUP BY trade_date
              ), ranked AS (
                SELECT d0.*,
                  cume_dist() OVER(PARTITION BY trade_date,causal_industry ORDER BY ret20)
                    AS industry_ret20_percentile
                FROM d0 WHERE ret20 IS NOT NULL
              ), industry_state AS (
                SELECT trade_date,causal_industry,count(*) AS industry_n20,
                  median(ret20) AS industry_median_ret20,
                  avg((ret20>0)::INT) AS industry_positive_ret20_share,
                  max(decision_at) AS industry_latest_source
                FROM ranked GROUP BY trade_date,causal_industry
              ), joined AS (
                SELECT r.*,m.* EXCLUDE(trade_date),i.* EXCLUDE(trade_date,causal_industry),
                  prev_coord_close/NULLIF(lag60_coord_close,0)-1 AS prior60_return,
                  prev_coord_close/NULLIF(prior60_high,0)-1 AS prior60_high_distance,
                  ret20-i.industry_median_ret20 AS stock_minus_industry_ret20
                FROM ranked r JOIN market_state m USING(trade_date)
                JOIN industry_state i USING(trade_date,causal_industry)
              )
              SELECT *,
                'BA41-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,decision_at AS feature_latest_timestamp,
                'BROAD_ACCUMULATION_LAGGARD_SUPPORT' AS admission_lane,
                turnover_fraction AS turnover_expansion
              FROM joined
              WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
                AND prior60_n=60
                AND market_positive_ret20_share>0.90
                AND market_median_ret20>0 AND market_median_ret20<=0.20
                AND market_median_ret60>0.05 AND market_positive_ret60_share>0.60
                AND market_median_ret120>0.05 AND market_positive_ret120_share>0.55
                AND industry_n20>=5
                AND industry_median_ret20>0 AND industry_positive_ret20_share>0.60
                AND industry_ret20_percentile<=0.40
                AND prior60_return>0.05
                AND prior60_high_distance>=-0.10
                AND step_return BETWEEN -0.05 AND 0.03
              ORDER BY trade_date,symbol
            ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for col in ("trade_date", "signal_date", "decision_at", "feature_latest_timestamp",
                "market_latest_source", "industry_latest_source"):
        frame[col] = pd.to_datetime(frame[col])
    return frame


def candidate_audit(frame: pd.DataFrame) -> dict[str, int]:
    required = [
        "market_median_ret20", "market_positive_ret20_share", "market_median_ret60",
        "market_positive_ret60_share", "market_median_ret120", "market_positive_ret120_share",
        "industry_median_ret20", "industry_positive_ret20_share", "industry_ret20_percentile",
        "prior60_return", "prior60_high_distance", "step_return", "invalid_step_cum",
    ]
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "missing_required_feature_count": int(frame[required].isna().any(axis=1).sum()),
        "feature_after_decision_count": int(
            (frame.market_latest_source.gt(frame.decision_at)
             | frame.industry_latest_source.gt(frame.decision_at)
             | frame.feature_latest_timestamp.gt(frame.decision_at)).sum()
        ),
        "candidate_after_2023_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "wrong_admission_count": int((
            frame.market_positive_ret20_share.le(.90)
            | frame.market_median_ret20.le(0) | frame.market_median_ret20.gt(.20)
            | frame.market_median_ret60.le(.05) | frame.market_positive_ret60_share.le(.60)
            | frame.market_median_ret120.le(.05) | frame.market_positive_ret120_share.le(.55)
            | frame.industry_median_ret20.le(0) | frame.industry_positive_ret20_share.le(.60)
            | frame.industry_ret20_percentile.gt(.40) | frame.prior60_return.le(.05)
            | frame.prior60_high_distance.lt(-.10) | ~frame.step_return.between(-.05,.03)
        ).sum()),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    return audit


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    x = frame.copy(); x["year"] = x.signal_date.dt.year
    x["hash_order"] = x.event_id.map(lambda z: hashlib.sha256(z.encode()).hexdigest())
    pieces = [g.sort_values("hash_order").head(3) for _, g in x.groupby("year")]
    chosen = pd.concat(pieces, ignore_index=True) if pieces else x.head(0)
    if len(chosen) < count:
        rest = x.loc[~x.event_id.isin(chosen.event_id)].sort_values("hash_order")
        chosen = pd.concat([chosen, rest.head(count-len(chosen))], ignore_index=True)
    chosen = chosen.sort_values(["signal_date", "symbol"]).head(count).reset_index(drop=True)
    chosen.insert(0, "chart_id", [f"V41-BLIND-{i:03d}" for i in range(1,len(chosen)+1)])
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True); chosen.to_csv(BLIND_INDEX,index=False)
    return chosen


def render_blind_charts(sample: pd.DataFrame) -> None:
    if sample.empty:
        return
    BLIND_DIR.mkdir(parents=True, exist_ok=True); BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())}); con=duckdb.connect();con.register("s",symbols)
    daily=con.execute(f"""SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close
      FROM read_parquet('{v1.DAILY}') d JOIN s USING(symbol)
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
      ORDER BY symbol,trade_date""").fetchdf();con.close();daily.trade_date=pd.to_datetime(daily.trade_date)
    groups={s:g.reset_index(drop=True) for s,g in daily.groupby("symbol")}
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            stock=groups[event.symbol];pos=np.flatnonzero(stock.trade_date.eq(event.signal_date).to_numpy())[0]
            view=stock.iloc[max(0,pos-130):pos+1].copy();x=v1.mdates.date2num(view.trade_date)
            colors=np.where(view.coord_close.ge(view.coord_open),"#dc2626","#059669")
            fig,ax=v1.plt.subplots(figsize=(11.7,8.3));ax.vlines(x,view.coord_low,view.coord_high,color=colors,lw=.7)
            ax.bar(x,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65)
            ax.axvline(event.signal_date,color="#2563eb",ls="--",label="completed signal close")
            ax.axhline(event.prior60_high,color="#f59e0b",ls=":",label="frozen prior-60 high")
            ax.set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",fontproperties=v1.CJK_FONT)
            ax.grid(alpha=.2);ax.legend(fontsize=8)
            fig.text(.01,.035,(f"Outcome-blind. Market ret20 breadth={event.market_positive_ret20_share:.1%}, med20={event.market_median_ret20:.1%}, med60={event.market_median_ret60:.1%}, med120={event.market_median_ret120:.1%}. "f"Industry breadth={event.industry_positive_ret20_share:.1%}; stock industry percentile={event.industry_ret20_percentile:.1%}."),fontsize=8)
            fig.text(.01,.015,(f"Prior60 return={event.prior60_return:+.1%}; distance to prior60 high={event.prior60_high_distance:+.1%}; signal pause={event.step_return:+.1%}. Entry and all post-signal bars are hidden."),fontsize=8)
            fig.tight_layout(rect=[0,.055,1,1]);pdf.savefig(fig,dpi=150);fig.savefig(BLIND_DIR/f"{event.chart_id}.png",dpi=135);v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes=persist_contract();frame=build_candidates();audit=candidate_audit(frame);sample=blind_sample(frame);render_blind_charts(sample)
    counts=frame.groupby(frame.signal_date.dt.year).size().reindex(ALL_YEARS,fill_value=0).astype(int).to_dict()
    result={"experiment":EXPERIMENT,**hashes,"runner_sha256":v1.sha256(Path(__file__)),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"candidate_count":len(frame),"annual_candidate_counts":counts,"unique_signal_dates":int(frame.signal_date.nunique()),"max_candidates_one_date":int(frame.groupby('signal_date').size().max()),"blind_chart_count":len(sample),"audit":{**audit,"outcomes_opened":False,"2021_2023_forward_outcomes_opened":False,"2024_plus_signal_or_feature_opened":False}}
    v1.write_json(FREEZE,result);return result


def verify_stage_a() -> dict[str, Any]:
    freeze=json.loads(FREEZE.read_text());expected={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"runner_sha256":v1.sha256(Path(__file__)),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF)}
    drift={k:[freeze.get(k),v] for k,v in expected.items() if freeze.get(k)!=v}
    if drift:raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def load_daily(symbols: list[str], include_tail: bool) -> pd.DataFrame:
    registry=pd.DataFrame({"symbol":sorted(set(symbols))});con=duckdb.connect();con.register("s",registry)
    tail=(f"UNION ALL BY NAME SELECT * FROM read_parquet('{v1.DAILY_TAIL}') WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '2024-03-31'" if include_tail else "")
    frame=con.execute(f"""WITH d AS (SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31' {tail}) SELECT d.* FROM d JOIN s USING(symbol) ORDER BY symbol,trade_date""").fetchdf();con.close();frame.trade_date=pd.to_datetime(frame.trade_date);return frame


def build_outcomes(candidates: pd.DataFrame, output: Path, include_tail: bool) -> tuple[pd.DataFrame,dict[str,int],pd.DataFrame]:
    daily=load_daily(candidates.symbol.astype(str).unique().tolist(),include_tail);rows=[]
    for symbol,events in candidates.groupby("symbol",sort=False):
        g=daily.loc[daily.symbol.eq(symbol)].sort_values("trade_date").reset_index(drop=True)
        dates=g.trade_date.to_numpy();cal=g.cal_idx.to_numpy(dtype=int);coord_open=g.coord_open.to_numpy(float);coord_high=g.coord_high.to_numpy(float)
        raw_open=g.open.to_numpy(float);up=g.up_limit_price.to_numpy(float);down=g.down_limit_price.to_numpy(float);lineage=g.invalid_step_cum.to_numpy(float)
        state=(g.hard_valid.fillna(False).to_numpy(bool)&g.history_valid.fillna(False).to_numpy(bool)&g.current_valid.fillna(False).to_numpy(bool)&g.corporate_action_valid.fillna(False).to_numpy(bool)&~g.corporate_action_blocking.fillna(True).to_numpy(bool)&g.current_day_data_tradable.fillna(False).to_numpy(bool)&g.market_rule_valid.fillna(False).to_numpy(bool)&g.trade_status.fillna(0).eq(1).to_numpy(bool))
        date_pos={pd.Timestamp(value):i for i,value in enumerate(dates)}
        for event in events.itertuples(index=False):
            base={"event_id":event.event_id,"symbol":event.symbol,"sleeve":event.sleeve,"causal_industry":event.causal_industry,"signal_date":event.signal_date,"signal_cal_idx":int(event.cal_idx),"industry_positive_ret20_share":float(event.industry_positive_ret20_share),"stock_minus_industry_ret20":float(event.stock_minus_industry_ret20),"turnover_expansion":float(event.turnover_expansion),"prior60_return":float(event.prior60_return),"prior60_high_distance":float(event.prior60_high_distance)}
            pos=date_pos.get(pd.Timestamp(event.signal_date));lin=float(event.invalid_step_cum)
            if pos is None:raise ResearchError(f"missing signal row {event.event_id}")
            entry=None
            for j in range(pos+1,len(g)):
                if cal[j]>int(event.cal_idx)+3:break
                if state[j] and lineage[j]==lin and round(raw_open[j]*100)<round(up[j]*100):entry=j;break
            if entry is None:rows.append({**base,"status":"NO_LEGAL_ENTRY"});continue
            target=coord_open[entry]*(1+TARGET);hit=None;decision=None;invalid=False
            for j in range(entry+1,len(g)):
                if lineage[j]!=lin:invalid=True;break
                if state[j] and coord_high[j]>=target:hit=j;break
                if state[j] and cal[j]>=cal[entry]+HORIZON:decision=j;break
            if invalid:rows.append({**base,"status":"INVALID_COORDINATE_LINEAGE_AFTER_ENTRY","entry_date":dates[entry],"entry_cal_idx":cal[entry],"entry_price":coord_open[entry]});continue
            if hit is not None:
                exit_pos=hit;exit_price=target;reason="TARGET_15";exit_at_open=False;decision_idx=cal[entry]
            else:
                if decision is None:rows.append({**base,"status":"INCOMPLETE_OUTCOME_TAIL","entry_date":dates[entry],"entry_cal_idx":cal[entry],"entry_price":coord_open[entry]});continue
                exit_pos=None
                for j in range(decision+1,len(g)):
                    if lineage[j]!=lin:invalid=True;break
                    if state[j] and round(raw_open[j]*100)>round(down[j]*100):exit_pos=j;break
                if invalid:rows.append({**base,"status":"INVALID_COORDINATE_LINEAGE_AFTER_ENTRY","entry_date":dates[entry],"entry_cal_idx":cal[entry],"entry_price":coord_open[entry]});continue
                if exit_pos is None:rows.append({**base,"status":"INCOMPLETE_OUTCOME_TAIL","entry_date":dates[entry],"entry_cal_idx":cal[entry],"entry_price":coord_open[entry]});continue
                exit_price=coord_open[exit_pos];reason="H15_TIME_STOP";exit_at_open=True;decision_idx=cal[decision]
            gross=float(exit_price/coord_open[entry]-1)
            rows.append({**base,"status":"COMPLETED","entry_date":dates[entry],"entry_cal_idx":int(cal[entry]),"entry_price":float(coord_open[entry]),"exit_date":dates[exit_pos],"exit_cal_idx":int(cal[exit_pos]),"exit_price":float(exit_price),"exit_reason":reason,"exit_at_open":exit_at_open,"exit_decision_cal_idx":int(decision_idx),"holding_sessions":int(cal[exit_pos]-cal[entry]),"gross_return":gross,"net_return":gross-ENTRY_COST-EXIT_COST})
    frame=pd.DataFrame(rows)
    for col in ("signal_date","entry_date","exit_date"):frame[col]=pd.to_datetime(frame[col])
    v1.write_parquet(frame,output);audit={"signal_bar_fill_count":int((frame.entry_date.notna()&frame.entry_date.le(frame.signal_date)).sum()),"t1_same_day_exit_count":int((frame.status.eq('COMPLETED')&frame.exit_cal_idx.le(frame.entry_cal_idx)).sum()),"target_on_entry_day_count":int((frame.status.eq('COMPLETED')&~frame.exit_at_open.fillna(False)&frame.exit_cal_idx.le(frame.entry_cal_idx)).sum())}
    if any(audit.values()):raise ResearchError(str(audit))
    return frame,audit,daily


def summarize(frame: pd.DataFrame) -> dict[str,Any]:
    x=frame.loc[frame.status.eq("COMPLETED")]
    if x.empty:return {"completed_trades":0,"mean_net":None,"median_net":None,"win_rate":None,"target_hit_rate":None,"severe_loss10":None,"mean_holding_sessions":None,"median_holding_sessions":None}
    return {"completed_trades":len(x),"mean_net":float(x.net_return.mean()),"median_net":float(x.net_return.median()),"win_rate":float(x.net_return.gt(0).mean()),"target_hit_rate":float(x.exit_reason.eq('TARGET_15').mean()),"severe_loss10":float(x.net_return.le(-.10).mean()),"mean_holding_sessions":float(x.holding_sessions.mean()),"median_holding_sessions":float(x.holding_sessions.median())}


def replay(trades: pd.DataFrame,daily: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame,dict[str,Any]]:
    x=trades.loc[trades.status.eq('COMPLETED')].sort_values(['entry_date','industry_positive_ret20_share','prior60_return','prior60_high_distance','event_id'],ascending=[True,False,False,False,True],kind='mergesort');by_date={d:g for d,g in x.groupby('entry_date')};groups={s:g.sort_values('trade_date').set_index('trade_date') for s,g in daily.groupby('symbol')};dates=sorted(pd.Timestamp(d) for d in daily.trade_date.unique());states={'MAIN':{'cash':.5,'active':{},'last':{}},'CHINEXT':{'cash':.5,'active':{},'last':{}}};accepted=[];skipped=[];nav=[];negative=max_k=duplicate=intraday_reuse=0
    def mark(symbol,date,field):
        g=groups.get(symbol)
        if g is None or date not in g.index:return None
        value=g.loc[date,field];value=value.iloc[-1] if isinstance(value,pd.Series) else value
        return None if pd.isna(value) else float(value)
    if x.empty:return pd.DataFrame(),pd.DataFrame(),pd.DataFrame(),{}
    for date in dates:
        if date<x.entry_date.min() or date>x.exit_date.max():continue
        for sleeve,state in states.items():
            # Only exits genuinely executable at the open release cash before new opens.
            open_exits=[p for p in state['active'].values() if pd.Timestamp(p['exit_date'])==date and bool(p['exit_at_open'])]
            for p in sorted(open_exits,key=lambda z:z['symbol']):state['cash']+=p['qty']*p['exit_price']*(1-EXIT_COST);del state['active'][p['symbol']]
            open_value=sum(p['qty']*(mark(s,date,'coord_open') or state['last'].get(s,p['entry_price'])) for s,p in state['active'].items());sleeve_nav=state['cash']+open_value;cand=by_date.get(date,pd.DataFrame());cand=cand.loc[cand.sleeve.eq(sleeve)] if len(cand) else cand;new=0
            for row in cand.itertuples(index=False):
                reason=None
                if row.symbol in state['active']:reason='DUPLICATE_SYMBOL';duplicate+=1
                elif len(state['active'])>=K_PER_SLEEVE:reason='MAX_K'
                elif new>=MAX_NEW_PER_SLEEVE_DATE:reason='DAILY_CAP'
                budget=sleeve_nav/K_PER_SLEEVE
                if reason is None and state['cash']+1e-12<budget:reason='INSUFFICIENT_CASH'
                if reason is not None:skipped.append({**row._asdict(),'skip_reason':reason});continue
                qty=budget/(row.entry_price*(1+ENTRY_COST));state['cash']-=budget;state['active'][row.symbol]={**row._asdict(),'qty':qty,'entry_outlay':budget};accepted.append({**row._asdict(),'qty':qty,'entry_outlay':budget});new+=1
            # Intraday target exits release cash only after all opening entries are settled.
            target_exits=[p for p in state['active'].values() if pd.Timestamp(p['exit_date'])==date and not bool(p['exit_at_open'])]
            for p in sorted(target_exits,key=lambda z:z['symbol']):state['cash']+=p['qty']*p['exit_price']*(1-EXIT_COST);del state['active'][p['symbol']]
            close_value=0.0
            for symbol,p in state['active'].items():
                price=mark(symbol,date,'coord_close')
                if price is not None:state['last'][symbol]=price
                close_value+=p['qty']*state['last'].get(symbol,p['entry_price'])
            nav.append({'trade_date':date,'sleeve':sleeve,'nav':state['cash']+close_value,'cash':state['cash'],'active':len(state['active'])});negative+=int(state['cash']< -1e-10);max_k+=int(len(state['active'])>K_PER_SLEEVE)
    accepted=pd.DataFrame(accepted);skipped=pd.DataFrame(skipped);nav=pd.DataFrame(nav);combined=nav.pivot(index='trade_date',columns='sleeve',values='nav').ffill().sum(axis=1);returns=combined.pct_change();returns.iloc[0]=combined.iloc[0]-1;dd=combined/combined.cummax().clip(lower=1)-1;years=max((combined.index.max()-combined.index.min()).days/365.25,1/252);metrics={'total_return':float(combined.iloc[-1]-1),'cagr':float(combined.iloc[-1]**(1/years)-1),'max_drawdown':float(dd.min()),'sharpe':float(returns.mean()/returns.std(ddof=1)*math.sqrt(252)) if returns.std(ddof=1)>0 else 0.0,'average_utilization':float((1-nav.cash/nav.nav).mean()),'negative_cash_count':negative,'max_k_violation_count':max_k,'duplicate_position_skip_count':duplicate,'same_day_intraday_target_cash_reuse_count':intraday_reuse};return accepted,skipped,combined.rename('combined_nav').reset_index(),metrics


def concentration(frame: pd.DataFrame) -> dict[str,Any]:
    x=frame.copy();x['pnl']=x.entry_outlay*x.net_return;by=x.groupby(x.signal_date.dt.normalize()).pnl.sum().sort_values(ascending=False);pos=float(by.clip(lower=0).sum());best=by.head(5).index;rest=x.loc[~x.signal_date.dt.normalize().isin(best)];return {'signal_date_count':int(x.signal_date.nunique()),'top_five_signal_date_positive_pnl_share':None if pos<=0 else float(by.head(5).clip(lower=0).sum()/pos),'mean_excluding_best_five_signal_dates':float(rest.net_return.mean()),'top_signal_date_trade_share':float(x.signal_date.value_counts(normalize=True).iloc[0])}


def run_stage_b() -> dict[str,Any]:
    stage_a=verify_stage_a();c=v1.read_parquet_duckdb(CANDIDATES);c.signal_date=pd.to_datetime(c.signal_date);dev=c.loc[c.signal_date.dt.year.isin(DEVELOPMENT_YEARS)];dev_o,dev_audit,dev_daily=build_outcomes(dev,DEV_OUTCOMES,False);dev_acc,dev_skip,dev_nav,dev_port=replay(dev_o,dev_daily);dev_summary=summarize(dev_acc.assign(status='COMPLETED'));dev_annual={str(y):summarize(dev_acc.loc[dev_acc.signal_date.dt.year.eq(y)].assign(status='COMPLETED')) for y in DEVELOPMENT_YEARS};dev_gate={'accepted_completed_ge_500':len(dev_acc)>=500,'mean_net_gt_5pct':dev_summary['mean_net']>.05,'mean_hold_lt_15':dev_summary['mean_holding_sessions']<15,'every_active_year_positive':all(v['mean_net'] is None or v['mean_net']>0 for v in dev_annual.values())}
    if not all(dev_gate.values()):
        result={'experiment':EXPERIMENT,'verdict':'BROAD_ACCUMULATION_LAGGARD_SUPPORT_DEVELOPMENT_FAILED','stage_a':stage_a,'development':dev_summary,'development_annual':dev_annual,'development_portfolio':dev_port,'development_gate':dev_gate,'development_audit':dev_audit,'forward_opened':False,'2024_plus_signal_or_feature_opened':False};v1.write_json(RESULT,result);return result
    v1.write_json(FORWARD_FREEZE,{'experiment':EXPERIMENT,'contract_sha256':v1.sha256(CONTRACT),'candidate_sha256':v1.sha256(CANDIDATES),'development_outcomes_sha256':v1.sha256(DEV_OUTCOMES),'target':TARGET,'horizon':HORIZON,'forward_opened':False})
    fwd=c.loc[c.signal_date.dt.year.isin(FORWARD_YEARS)];fwd_o,fwd_audit,fwd_daily=build_outcomes(fwd,FORWARD_OUTCOMES,True);all_o=pd.concat([dev_o,fwd_o],ignore_index=True);all_daily=pd.concat([dev_daily,fwd_daily],ignore_index=True).drop_duplicates(['trade_date','symbol'],keep='last');accepted,skipped,nav,portfolio=replay(all_o,all_daily);v1.write_parquet(accepted,ACCEPTED);v1.write_parquet(skipped,SKIPPED);v1.write_parquet(nav,NAV);overall=summarize(accepted.assign(status='COMPLETED'));annual={str(y):summarize(accepted.loc[accepted.signal_date.dt.year.eq(y)].assign(status='COMPLETED')) for y in ALL_YEARS};conc=concentration(accepted);gate={'completed_per_year_gt_50':len(accepted)/10>50,'mean_net_gt_5pct':overall['mean_net']>.05,'mean_hold_lt_15':overall['mean_holding_sessions']<15,'forward_each_positive':all(annual[str(y)]['mean_net'] is not None and annual[str(y)]['mean_net']>0 for y in FORWARD_YEARS),'top5_date_share_le_25pct':conc['top_five_signal_date_positive_pnl_share']<=.25,'mean_ex_best5_positive':conc['mean_excluding_best_five_signal_dates']>0};verdict='BROAD_ACCUMULATION_LAGGARD_SUPPORT_EDGE' if all(gate.values()) else 'BROAD_ACCUMULATION_LAGGARD_SUPPORT_FAILED_FORWARD_OR_TARGET';result={'experiment':EXPERIMENT,'verdict':verdict,'development':dev_summary,'development_annual':dev_annual,'development_gate':dev_gate,'capacity_accepted_completed_trades':len(accepted),'capacity_skips':len(skipped),'completed_per_year':len(accepted)/10,'overall_2014_2023':overall,'annual':annual,'portfolio':portfolio,'concentration':conc,'gate':gate,'audit':{**dev_audit,**{f'forward_{k}':v for k,v in fwd_audit.items()},'feature_after_decision_count':0,'forward_freeze_before_open':True,'2024_rows_used_only_for_pre2024_execution_resolution':True,'2024_plus_signal_or_feature_opened':False},'hashes':{'forward_freeze':v1.sha256(FORWARD_FREEZE),'development_outcomes':v1.sha256(DEV_OUTCOMES),'forward_outcomes':v1.sha256(FORWARD_OUTCOMES),'accepted':v1.sha256(ACCEPTED),'skipped':v1.sha256(SKIPPED),'nav':v1.sha256(NAV)}};v1.write_json(RESULT,result);return result


def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
    if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
    elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
    else:p.error('choose --stage-a or --stage-b')


if __name__=='__main__':main()
