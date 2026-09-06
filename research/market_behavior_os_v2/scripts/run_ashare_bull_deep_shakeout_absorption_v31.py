#!/usr/bin/env python3
"""Outcome-blind bull leader deep-shakeout absorption research lane."""

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

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-DEEP-SHAKEOUT-ABSORPTION-V31"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_deep_shakeout_absorption_v31")
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
DAILY = v1.DAILY
REGIME = v1.SOURCE_REGIME
INDUSTRY = v1.INDUSTRY_PANEL
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
PROFILE_FREEZE = OS / f"artifacts/{EXPERIMENT}_profile_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
DAILY_MOTHER = EXT / "stage_a/daily_mother.parquet"
MINUTE_PARTS = EXT / "stage_a/minute_parts"
SIGNAL_MINUTES = EXT / "stage_a/signal_minutes.parquet"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf"
YEARS = tuple(range(2014, 2024))
DEVELOPMENT_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
PROFILE_TABLE = EXT / "stage_b/profile_table.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"
PROFILES = {
    "H5_RECLAIM_FAILURE": {"horizon": 5, "target": None},
    "H10_RECLAIM_FAILURE": {"horizon": 10, "target": None},
    "T10_H10_RECLAIM_FAILURE": {"horizon": 10, "target": 0.10},
    "T15_H10_RECLAIM_FAILURE": {"horizon": 10, "target": 0.15},
}


class ResearchError(RuntimeError):
    """Fail-closed V31 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "stage": "A_OUTCOME_BLIND_SEMANTIC_PREFLIGHT",
        "economic_hypothesis": (
            "A stock with an established but non-euphoric positive trend can suffer "
            "a deep intraday liquidity shakeout while the causally known broad market "
            "and PIT industry close non-negative. If the stock recovers to the top of "
            "its daily range on expanded turnover, urgent supply has been absorbed by "
            "observable demand without requiring the buyer to chase a prior limit-up."
        ),
        "grouped_conditions": {
            "CAUSAL_BULL_ENVIRONMENT": (
                "frozen market_regime BULL; PIT industry n20>=5, median ret20>0, "
                "positive-ret20 share>50%; same-day executable-universe market median "
                "return>=0 and PIT-industry median return>=0"
            ),
            "ESTABLISHED_NONSATURATED_STRENGTH": (
                "prior completed 20-session return in [0%,50%] and prior20 high / "
                "prior60 low - 1 >=20%"
            ),
            "DEEP_INTRADAY_SHAKEOUT": (
                "(prior close-low)/(prior close-historical down-limit coordinate)>=50%"
            ),
            "SAME_DAY_ABSORPTION": (
                "close in top 25% of daily range, close return>=-2%, turnover>=1.2x "
                "prior completed 20-session mean"
            ),
            "MINUTE_PATH_CONFIRMATION": (
                "exact 241-minute session; first 50%-down-limit-depth touch occurs "
                "without price first rallying more than 3% above prior close; a later "
                "completed minute close reclaims 98% of prior close; at least 12 of "
                "the final 15 completed minute closes retain that reclaimed level"
            ),
        },
        "decision_clock": "completed daily close",
        "entry": "first legal daily open after signal within three market sessions",
        "translation_profiles": PROFILES,
        "failure_exit": (
            "after T+1, first completed daily close below 98% of the signal's prior "
            "close; exit at next legal open"
        ),
        "profit_target": "profile target standing from first T+1 session",
        "time_stop": "profile H5 or H10 decision, then next legal open",
        "round_trip_cost": 0.004,
        "profile_selection": {
            "years": list(DEVELOPMENT_YEARS),
            "minimum_completed": 700,
            "minimum_positive_years": 5,
            "minimum_mean_net": 0.03,
            "maximum_mean_holding_sessions": 15,
            "order": ["median annual mean net","pooled mean net","lower severe10","shorter horizon"],
        },
        "portfolio": v1.contract_value()["portfolio"],
        "outcomes_opened": False,
        "blind_chart": "130 completed sessions ending at signal; no post-signal bar",
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_HIGH_RECALL_CONTRACT",
            "contract_sha256": v1.sha256(CONTRACT),
            "source_hashes": {
                "daily": v1.sha256(DAILY),
                "regime": v1.sha256(REGIME),
                "industry": v1.sha256(INDUSTRY),
            },
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_daily_mother() -> pd.DataFrame:
    DAILY_MOTHER.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH eligible AS (
                SELECT * FROM read_parquet('{DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL AND industry_valid
              ), market_day AS (
                SELECT trade_date,median(step_return) AS market_step_median,
                  avg((step_return>0)::INTEGER) AS market_positive_step_share
                FROM eligible GROUP BY trade_date
              ), industry_day AS (
                SELECT trade_date,causal_industry,
                  median(step_return) AS industry_step_median,
                  avg((step_return>0)::INTEGER) AS industry_positive_step_share,
                  count(*) AS industry_step_n
                FROM eligible GROUP BY trade_date,causal_industry
              ), d0 AS (
                SELECT d.*,
                  lag(coord_close) OVER w AS prev_coord_close,
                  lag(coord_close,20) OVER w AS lag20_coord_close,
                  avg(turnover_fraction) OVER w20 AS prior20_turnover,
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w60 AS prior60_low,
                  count(*) OVER w60 AS prior60_n
                FROM eligible d
                WINDOW
                  w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                  w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
              ), features AS (
                SELECT d0.*,
                  prev_coord_close/NULLIF(lag20_coord_close,0)-1 AS prior_completed_ret20,
                  prior20_high/NULLIF(prior60_low,0)-1 AS prior_impulse,
                  (prior_coord_close-coord_low)/NULLIF(
                    prior_coord_close-down_limit_price*coordinate_factor,0
                  ) AS downside_limit_progress,
                  (coord_close-coord_low)/NULLIF(coord_high-coord_low,0) AS close_recovery_ratio,
                  coord_close/NULLIF(prior_coord_close,0)-1 AS signal_close_return,
                  turnover_fraction/NULLIF(prior20_turnover,0) AS turnover_expansion
                FROM d0
              )
              SELECT f.*,r.market_regime,
                r.market_median_ret20,r.market_positive_ret20_share,
                r.latest_source_timestamp AS market_latest_source,
                i.industry_median_ret20,i.industry_positive_ret20_share,
                i.industry_median_ret60,i.industry_n20,i.industry_ret20_percentile,
                i.latest_source_timestamp AS industry_latest_source,
                m.market_step_median,m.market_positive_step_share,
                id.industry_step_median,id.industry_positive_step_share,id.industry_step_n,
                'SHAKE31-'||strftime(f.trade_date,'%Y%m%d')||'-'||f.symbol AS event_id,
                f.trade_date AS signal_date,
                f.decision_at AS feature_latest_timestamp,
                f.coord_low AS structural_low,
                f.ret20-i.industry_median_ret20 AS stock_minus_industry_ret20,
                'BULL_DEEP_SHAKEOUT_ABSORPTION' AS admission_lane
              FROM features f
              JOIN read_parquet('{REGIME}') r USING(trade_date)
              JOIN read_parquet('{INDUSTRY}') i USING(trade_date,causal_industry)
              JOIN market_day m USING(trade_date)
              JOIN industry_day id USING(trade_date,causal_industry)
              WHERE f.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
                AND f.prior60_n=60
                AND r.market_regime='BULL'
                AND i.industry_n20>=5
                AND i.industry_median_ret20>0
                AND i.industry_positive_ret20_share>0.50
                AND m.market_step_median>=0
                AND id.industry_step_median>=0
                AND f.prior_completed_ret20 BETWEEN 0 AND 0.50
                AND f.prior_impulse>=0.20
                AND f.downside_limit_progress>=0.50
                AND f.close_recovery_ratio>=0.75
                AND f.signal_close_return>=-0.02
                AND f.turnover_expansion>=1.20
              ORDER BY f.trade_date,f.symbol
            ) TO '{DAILY_MOTHER}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(DAILY_MOTHER)
    for column in (
        "trade_date","signal_date","available_at","decision_at",
        "market_latest_source","industry_latest_source","feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    latest = frame[["available_at","market_latest_source","industry_latest_source","feature_latest_timestamp"]].max(axis=1)
    if frame.event_id.duplicated().any() or latest.gt(frame.decision_at).any():
        raise ResearchError("candidate identity or causal timestamp audit failed")
    return frame


def build_minute_contract(mother: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    MINUTE_PARTS.mkdir(parents=True,exist_ok=True)
    seed=mother[["event_id","symbol","signal_date","coordinate_factor","prior_coord_close","down_limit_price"]].copy()
    seed["qmt_code"]=seed.symbol
    seed["trade_date"]=pd.to_datetime(seed.signal_date).dt.date
    for year in YEARS:
        part=seed.loc[pd.to_datetime(seed.signal_date).dt.year.eq(year)].copy()
        output=MINUTE_PARTS/f"{year}.parquet"
        if part.empty:
            continue
        raw=RAW_ROOT/f"{year}_day_parquet_none.parquet"
        if not raw.is_file(): raise ResearchError(f"missing governed minute input {raw}")
        con=duckdb.connect();con.register("seed",part)
        con.execute(
            f"""COPY (
            SELECT s.event_id,s.symbol,s.signal_date,s.prior_coord_close,s.down_limit_price,
              s.coordinate_factor,m.bar_end_time,m.open*s.coordinate_factor AS coord_minute_open,
              m.high*s.coordinate_factor AS coord_minute_high,
              m.low*s.coordinate_factor AS coord_minute_low,
              m.close*s.coordinate_factor AS coord_minute_close,m.volume,m.amount
            FROM read_parquet('{raw}') m JOIN seed s
              ON m.qmt_code=s.qmt_code AND m.trade_date=s.trade_date
            WHERE m.period='1m' AND m.adjust='none'
            ORDER BY s.event_id,m.bar_end_time
            ) TO '{output}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
        );con.close()
    sources=sorted(MINUTE_PARTS.glob("*.parquet"))
    if not sources: raise ResearchError("no minute parts")
    source_sql=",".join(f"'{p}'" for p in sources)
    con=duckdb.connect()
    con.execute(
        f"""COPY (SELECT * FROM read_parquet([{source_sql}]) ORDER BY event_id,bar_end_time)
        TO '{SIGNAL_MINUTES}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    timing=con.execute(
        f"""
        WITH minute0 AS (
          SELECT *,prior_coord_close-0.50*(prior_coord_close-down_limit_price*coordinate_factor)
            AS deep_threshold,
            row_number() OVER(PARTITION BY event_id ORDER BY bar_end_time DESC) AS reverse_minute
          FROM read_parquet('{SIGNAL_MINUTES}')
        ), first_low AS (
          SELECT event_id,min(bar_end_time) FILTER(WHERE coord_minute_low<=deep_threshold)
            AS first_deep_time,count(*) AS minute_count
          FROM minute0 GROUP BY event_id
        ), path AS (
          SELECT m.*,f.first_deep_time,f.minute_count
          FROM minute0 m JOIN first_low f USING(event_id)
        )
        SELECT event_id,max(minute_count) AS minute_count,max(first_deep_time) AS first_deep_time,
          min(bar_end_time) FILTER(
            WHERE bar_end_time>first_deep_time AND coord_minute_close>=0.98*prior_coord_close
          ) AS first_reclaim_time,
          max(coord_minute_high) FILTER(WHERE bar_end_time<=first_deep_time)/max(prior_coord_close)-1
            AS pre_low_max_return,
          max(coord_minute_high) FILTER(WHERE bar_end_time>first_deep_time)/max(prior_coord_close)-1
            AS post_low_max_return,
          avg((coord_minute_close>=0.98*prior_coord_close)::INTEGER) FILTER(WHERE reverse_minute<=15)
            AS final15_acceptance_ratio
        FROM path GROUP BY event_id
        """
    ).fetchdf();con.close()
    for column in ("first_deep_time","first_reclaim_time"): timing[column]=pd.to_datetime(timing[column])
    frame=mother.merge(timing,on="event_id",how="left",validate="one_to_one")
    frame=frame.loc[
        frame.minute_count.eq(241)
        & frame.first_deep_time.notna()
        & frame.first_reclaim_time.notna()
        & frame.first_reclaim_time.gt(frame.first_deep_time)
        & frame.pre_low_max_return.le(0.03)
        & frame.post_low_max_return.ge(-0.02)
        & frame.final15_acceptance_ratio.ge(0.80)
    ].copy()
    frame=frame.sort_values(["signal_date","symbol"]).reset_index(drop=True)
    v1.write_parquet(frame,CANDIDATES)
    audit={
        "mother_rows":len(mother),
        "minute_identity_rows":int(timing.event_id.nunique()),
        "non_241_mother_count":int(timing.minute_count.ne(241).sum())+int(len(mother)-timing.event_id.nunique()),
        "retained_rows":len(frame),
        "first_reclaim_at_or_before_deep_count":int(frame.first_reclaim_time.le(frame.first_deep_time).sum()),
        "pre_low_acceleration_violation_count":int(frame.pre_low_max_return.gt(.03).sum()),
        "final_acceptance_violation_count":int(frame.final15_acceptance_ratio.lt(.80).sum()),
    }
    return frame,audit


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    work = frame.copy()
    work["year"] = work.signal_date.dt.year
    work["hash_order"] = work.event_id.map(lambda x: hashlib.sha256(str(x).encode()).hexdigest())
    chosen = pd.concat(
        [part.sort_values("hash_order").head(3) for _, part in work.groupby("year")],
        ignore_index=True,
    )
    if len(chosen) < count:
        rest = work.loc[~work.event_id.isin(chosen.event_id)]
        chosen = pd.concat([chosen,rest.sort_values("hash_order").head(count-len(chosen))],ignore_index=True)
    chosen = chosen.sort_values(["signal_date","symbol"]).head(count).reset_index(drop=True)
    chosen.insert(0,"chart_id",[f"V31-BLIND-{i:03d}" for i in range(1,len(chosen)+1)])
    chosen.to_csv(BLIND_INDEX,index=False)
    return chosen


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True,exist_ok=True)
    BLIND_PDF.parent.mkdir(parents=True,exist_ok=True)
    symbols = pd.DataFrame({"symbol":sorted(sample.symbol.unique())})
    con=duckdb.connect();con.register("symbols",symbols)
    daily=con.execute(
        f"""SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close,
        d.turnover_fraction,d.ret20 FROM read_parquet('{DAILY}') d JOIN symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date"""
    ).fetchdf();con.close()
    daily["trade_date"]=pd.to_datetime(daily.trade_date)
    groups={str(s):g.reset_index(drop=True) for s,g in daily.groupby("symbol")}
    minute=v1.read_parquet_duckdb(SIGNAL_MINUTES);minute["bar_end_time"]=pd.to_datetime(minute.bar_end_time)
    minute=minute.loc[minute.event_id.isin(sample.event_id)]
    minute_groups={str(e):g.sort_values("bar_end_time") for e,g in minute.groupby("event_id")}
    regime=v1.read_parquet_duckdb(REGIME);regime["trade_date"]=pd.to_datetime(regime.trade_date)
    industry=v1.read_parquet_duckdb(INDUSTRY);industry["trade_date"]=pd.to_datetime(industry.trade_date)
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            g=groups[str(event.symbol)];pos=np.flatnonzero(g.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
            if len(pos)!=1: raise ResearchError(f"chart row missing {event.event_id}")
            view=g.iloc[max(0,int(pos[0])-129):int(pos[0])+1]
            start=view.trade_date.min();m=regime.loc[regime.trade_date.between(start,event.signal_date)]
            ind=industry.loc[industry.causal_industry.eq(event.causal_industry)&industry.trade_date.between(start,event.signal_date)]
            fig,axes=v1.plt.subplots(5,1,figsize=(11.7,8.3),gridspec_kw={"height_ratios":[2.2,.65,1.0,.8,.8]})
            xx=v1.mdates.date2num(view.trade_date);colors=np.where(view.coord_close>=view.coord_open,"#dc2626","#059669")
            axes[0].vlines(xx,view.coord_low,view.coord_high,color=colors,lw=.6)
            axes[0].bar(xx,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65,lw=0)
            axes[0].axvline(pd.Timestamp(event.signal_date),color="#dc2626",ls="--",label="Deep shakeout absorption close")
            axes[0].axhline(float(event.structural_low),color="#2563eb",ls=":",label="Signal structural low")
            axes[0].set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",fontproperties=v1.CJK_FONT)
            axes[0].legend(loc="upper left",fontsize=8);axes[0].grid(alpha=.2)
            axes[1].bar(view.trade_date,view.turnover_fraction,color=colors,width=.75);axes[1].grid(alpha=.2);axes[1].set_ylabel("Turnover")
            intr=minute_groups[str(event.event_id)];axes[2].plot(intr.bar_end_time,intr.coord_minute_close,color="#334155",label="Minute close");axes[2].axhline(.98*event.prior_coord_close,color="#f59e0b",ls=":",label="98% reclaim");axes[2].axvline(pd.Timestamp(event.first_deep_time),color="#059669",ls="--",label="First deep low");axes[2].axvline(pd.Timestamp(event.first_reclaim_time),color="#dc2626",ls="--",label="Later reclaim");axes[2].legend(fontsize=7,ncol=4);axes[2].grid(alpha=.2)
            axes[3].plot(m.trade_date,m.market_median_ret20,label="Market median20",color="#166534");axes[3].plot(m.trade_date,m.market_positive_ret20_share,label="Market breadth20",color="#0f766e");axes[3].axhline(0,color="black",lw=.6);axes[3].legend(fontsize=7,ncol=2);axes[3].grid(alpha=.2)
            axes[4].plot(ind.trade_date,ind.industry_median_ret20,label="Industry median20",color="#7c3aed");axes[4].plot(view.trade_date,view.ret20,label="Stock ret20",color="#b45309");axes[4].axhline(0,color="black",lw=.6);axes[4].legend(fontsize=7,ncol=2);axes[4].grid(alpha=.2)
            fig.text(.01,.01,"Outcome-blind; no post-signal bar. "f"down-limit progress={event.downside_limit_progress:.0%}; recovery={event.close_recovery_ratio:.0%}; turnover={event.turnover_expansion:.2f}x; market day={event.market_step_median:+.1%}; industry day={event.industry_step_median:+.1%}.",fontsize=7)
            fig.tight_layout(rect=[0,0.035,1,1]);pdf.savefig(fig,dpi=150);fig.savefig(BLIND_DIR/f"{event.chart_id}.png",dpi=135);v1.plt.close(fig)
    for page,start in enumerate(range(0,len(sample),10),1):
        chunk=sample.iloc[start:start+10];fig=v1.plt.figure(figsize=(20,24));grid=fig.add_gridspec(5,4,wspace=.18,hspace=.35)
        for offset,event in enumerate(chunk.itertuples(index=False)):
            ax=fig.add_subplot(grid[offset//2,(offset%2)*2]);axm=fig.add_subplot(grid[offset//2,(offset%2)*2+1])
            g=groups[str(event.symbol)];pos=int(np.flatnonzero(g.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())[0]);view=g.iloc[max(0,pos-99):pos+1]
            xx=v1.mdates.date2num(view.trade_date);colors=np.where(view.coord_close>=view.coord_open,"#dc2626","#059669")
            ax.vlines(xx,view.coord_low,view.coord_high,color=colors,lw=.5);ax.bar(xx,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65,lw=0)
            ax.axvline(pd.Timestamp(event.signal_date),color="#dc2626",ls="--");ax.set_title(f"{event.chart_id} {event.symbol} {event.causal_industry} dp={event.downside_limit_progress:.0%} rec={event.close_recovery_ratio:.0%}",fontsize=9,fontproperties=v1.CJK_FONT);ax.grid(alpha=.2)
            intr=minute_groups[str(event.event_id)];axm.plot(intr.bar_end_time.dt.strftime('%H:%M'),intr.coord_minute_close,color="#334155",lw=1);axm.axhline(.98*event.prior_coord_close,color="#f59e0b",ls=":");axm.axvline(pd.Timestamp(event.first_deep_time).strftime('%H:%M'),color="#059669",ls="--");axm.axvline(pd.Timestamp(event.first_reclaim_time).strftime('%H:%M'),color="#dc2626",ls="--");axm.set_xticks([0,60,120,180,240]);axm.tick_params(axis='x',labelrotation=30,labelsize=6);axm.grid(alpha=.2);axm.set_title(f"minute accept={event.final15_acceptance_ratio:.0%}",fontsize=8)
        fig.tight_layout();fig.savefig(BLIND_DIR/f"CONTACT_{page:02d}.png",dpi=145);v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes=persist_contract();mother=build_daily_mother();frame,minute_audit=build_minute_contract(mother);sample=blind_sample(frame);render_blind_charts(sample)
    audit={
        "duplicate_event_count":int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count":int(frame[["available_at","market_latest_source","industry_latest_source","feature_latest_timestamp"]].max(axis=1).gt(frame.decision_at).sum()),
        "post_2023_candidate_count":int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count":0,
        "outcomes_opened":False,
    }
    if any(v for k,v in audit.items() if k!="outcomes_opened"): raise ResearchError(str(audit))
    result={"experiment":EXPERIMENT,**hashes,"runner_sha256":v1.sha256(Path(__file__)),"daily_mother_sha256":v1.sha256(DAILY_MOTHER),"signal_minutes_sha256":v1.sha256(SIGNAL_MINUTES),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"candidate_count":len(frame),"annual_candidate_counts":frame.groupby(frame.signal_date.dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict(),"unique_signal_dates":int(frame.signal_date.nunique()),"maximum_signals_on_one_date":int(frame.groupby("signal_date").size().max()),"blind_chart_count":len(sample),"minute_audit":minute_audit,"audit":audit}
    v1.write_json(FREEZE,result);return result


def verify_stage_a() -> dict[str, Any]:
    frozen=json.loads(FREEZE.read_text(encoding="utf-8"))
    expected={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"runner_sha256":v1.sha256(Path(__file__)),"daily_mother_sha256":v1.sha256(DAILY_MOTHER),"signal_minutes_sha256":v1.sha256(SIGNAL_MINUTES),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF)}
    drift={k:[frozen.get(k),v] for k,v in expected.items() if frozen.get(k)!=v}
    if drift: raise ResearchError(f"Stage-A drift {drift}")
    return frozen


def load_trade_daily_bounded(symbols: list[str],through: str) -> pd.DataFrame:
    end=pd.Timestamp(through);registry=pd.DataFrame({"symbol":sorted(set(map(str,symbols)))})
    con=duckdb.connect();con.register("registry",registry)
    if end<=pd.Timestamp("2023-12-31"):
        query=f"SELECT d.* FROM read_parquet('{DAILY}') d JOIN registry r USING(symbol) WHERE d.trade_date BETWEEN DATE '2014-01-01' AND DATE '{end.date()}' ORDER BY d.symbol,d.trade_date"
    else:
        query=f"""WITH old AS(SELECT * FROM read_parquet('{DAILY}') WHERE trade_date<DATE '2024-01-01'),tail AS(SELECT * FROM read_parquet('{v1.DAILY_TAIL}') WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '{end.date()}'),d AS(SELECT * FROM old UNION ALL BY NAME SELECT * FROM tail) SELECT d.* FROM d JOIN registry r USING(symbol) ORDER BY d.symbol,d.trade_date"""
    frame=con.execute(query).fetchdf();con.close();frame["trade_date"]=pd.to_datetime(frame.trade_date);return frame


def build_outcomes(candidates: pd.DataFrame,through: str,output: Path) -> tuple[pd.DataFrame,dict[str,int]]:
    daily=load_trade_daily_bounded(candidates.symbol.unique().tolist(),through)
    groups={str(s):g.sort_values("trade_date").reset_index(drop=True) for s,g in daily.groupby("symbol",sort=False)}
    rows=[]
    for event in candidates.itertuples(index=False):
        part=groups[str(event.symbol)];positions=np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
        if len(positions)!=1: raise ResearchError(f"missing signal {event.event_id}")
        signal_pos=int(positions[0]);lineage=float(event.invalid_step_cum);entry_pos=None
        for pos in range(signal_pos+1,len(part)):
            row=part.iloc[pos]
            if int(row.cal_idx)>int(event.cal_idx)+3: break
            if v1.legal_buy(row,lineage): entry_pos=pos;break
        for profile,settings in PROFILES.items():
            base={"event_id":event.event_id,"symbol":event.symbol,"sleeve":event.sleeve,"signal_date":event.signal_date,"signal_cal_idx":int(event.cal_idx),"profile":profile,"reclaim_floor":.98*float(event.prior_coord_close)}
            if entry_pos is None: rows.append({**base,"status":"NO_LEGAL_ENTRY"});continue
            entry=part.iloc[entry_pos];entry_price=float(entry.coord_open);target=None if settings["target"] is None else entry_price*(1+settings["target"]);horizon_idx=int(entry.cal_idx)+settings["horizon"]
            exit_pos=None;exit_price=None;exit_reason=None;decision_idx=None
            for pos in range(entry_pos+1,len(part)):
                row=part.iloc[pos]
                if not v1.legal_state(row,lineage): continue
                if target is not None and float(row.coord_high)>=target:
                    exit_pos=pos;exit_price=target;exit_reason=f"TARGET_{int(settings['target']*100)}";decision_idx=int(row.cal_idx);break
                if float(row.coord_close)<.98*float(event.prior_coord_close):
                    decision_idx=int(row.cal_idx)
                    for sell in range(pos+1,len(part)):
                        if v1.legal_sell_open(part.iloc[sell],lineage): exit_pos=sell;exit_price=float(part.iloc[sell].coord_open);exit_reason="RECLAIM_LOST_FAILURE";break
                    break
                if int(row.cal_idx)>=horizon_idx:
                    decision_idx=int(row.cal_idx)
                    for sell in range(pos+1,len(part)):
                        if v1.legal_sell_open(part.iloc[sell],lineage): exit_pos=sell;exit_price=float(part.iloc[sell].coord_open);exit_reason=f"H{settings['horizon']}_TIME_STOP";break
                    break
            if exit_pos is None:
                rows.append({**base,"status":"INCOMPLETE_OUTCOME_TAIL","entry_date":entry.trade_date,"entry_cal_idx":int(entry.cal_idx),"entry_price":entry_price});continue
            exit=part.iloc[exit_pos];path=part.iloc[entry_pos:exit_pos+1]
            if path.invalid_step_cum.ne(lineage).any(): rows.append({**base,"status":"INVALID_COORDINATE_LINEAGE_AFTER_ENTRY","entry_date":entry.trade_date,"entry_cal_idx":int(entry.cal_idx),"entry_price":entry_price});continue
            gross=exit_price/entry_price-1
            rows.append({**base,"status":"COMPLETED","entry_date":entry.trade_date,"entry_cal_idx":int(entry.cal_idx),"entry_price":entry_price,"exit_date":exit.trade_date,"exit_cal_idx":int(exit.cal_idx),"exit_price":exit_price,"exit_reason":exit_reason,"exit_decision_cal_idx":decision_idx,"holding_sessions":int(exit.cal_idx)-int(entry.cal_idx),"gross_return":gross,"net_return":gross-.004})
    outcomes=pd.DataFrame(rows)
    for col in ("signal_date","entry_date","exit_date"): outcomes[col]=pd.to_datetime(outcomes[col])
    v1.write_parquet(outcomes,output)
    audit={"signal_bar_fill_count":int((outcomes.entry_date.notna()&outcomes.entry_date.le(outcomes.signal_date)).sum()),"t1_same_day_exit_count":int((outcomes.status.eq("COMPLETED")&outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)).sum())}
    return outcomes,audit


def metrics(frame: pd.DataFrame,target: float|None=None) -> dict[str,Any]:
    x=frame.loc[frame.status.eq("COMPLETED")]
    if x.empty:return {"completed_trades":0,"mean_net":None,"median_net":None,"win_rate":None,"severe_loss10":None,"target_hit_rate":None,"mean_holding_sessions":None,"median_holding_sessions":None}
    reason=None if target is None else f"TARGET_{int(target*100)}"
    return {"completed_trades":len(x),"mean_net":float(x.net_return.mean()),"median_net":float(x.net_return.median()),"win_rate":float(x.net_return.gt(0).mean()),"severe_loss10":float(x.net_return.le(-.10).mean()),"target_hit_rate":None if reason is None else float(x.exit_reason.eq(reason).mean()),"mean_holding_sessions":float(x.holding_sessions.mean()),"median_holding_sessions":float(x.holding_sessions.median())}


def make_profile_table(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for profile,settings in PROFILES.items():
        x=outcomes.loc[outcomes.profile.eq(profile)];annual={str(y):metrics(x.loc[x.signal_date.dt.year.eq(y)],settings["target"]) for y in DEVELOPMENT_YEARS};means=[v["mean_net"] for v in annual.values() if v["mean_net"] is not None]
        rows.append({"profile":profile,**metrics(x,settings["target"]),"positive_years":sum(v>0 for v in means),"median_annual_mean_net":float(np.median(means)),"annual_json":json.dumps(annual,sort_keys=True)})
    table=pd.DataFrame(rows);v1.write_parquet(table,PROFILE_TABLE);return table


def select_profile(table: pd.DataFrame) -> pd.Series|None:
    x=table.loc[table.completed_trades.ge(700)&table.positive_years.ge(5)&table.mean_net.ge(.03)&table.mean_holding_sessions.le(15)].copy()
    if x.empty:return None
    x["order"]=x.profile.map({p:i for i,p in enumerate(PROFILES)});return x.sort_values(["median_annual_mean_net","mean_net","severe_loss10","order"],ascending=[False,False,True,True],kind="mergesort").iloc[0]


def run_stage_b() -> dict[str,Any]:
    stage_a=verify_stage_a();candidates=v1.read_parquet_duckdb(CANDIDATES)
    for col in ("signal_date","decision_at","feature_latest_timestamp"):candidates[col]=pd.to_datetime(candidates[col])
    dev=candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT_YEARS)];dev_o,audit=build_outcomes(dev,"2021-03-31",DEV_OUTCOMES)
    if any(audit.values()):raise ResearchError(str(audit))
    table=make_profile_table(dev_o);selected=select_profile(table)
    if selected is None:
        result={"experiment":EXPERIMENT,"verdict":"BULL_DEEP_SHAKEOUT_DEVELOPMENT_FAILED","stage_a":stage_a,"profile_table":table.replace({np.nan:None}).to_dict("records"),"development_audit":audit,"forward_years_opened":False,"post_2023_rows_opened":False};v1.write_json(RESULT,result);return result
    profile=str(selected.profile);v1.write_json(PROFILE_FREEZE,{"experiment":EXPERIMENT,"selected_profile":profile,"development_outcomes_sha256":v1.sha256(DEV_OUTCOMES),"profile_table_sha256":v1.sha256(PROFILE_TABLE),"contract_sha256":v1.sha256(CONTRACT),"forward_opened":False})
    forward=candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)];fwd_o,fwd_audit=build_outcomes(forward,"2024-03-31",FORWARD_OUTCOMES)
    if any(fwd_audit.values()):raise ResearchError(str(fwd_audit))
    outcomes=pd.concat([dev_o,fwd_o],ignore_index=True);chosen=outcomes.loc[outcomes.profile.eq(profile)].merge(candidates[["event_id","industry_positive_ret20_share","stock_minus_industry_ret20","turnover_expansion"]],on="event_id",validate="one_to_one")
    daily=load_trade_daily_bounded(chosen.symbol.unique().tolist(),"2024-03-31");old=(v1.ACCEPTED,v1.SKIPPED,v1.NAV)
    try:v1.ACCEPTED,v1.SKIPPED,v1.NAV=ACCEPTED,SKIPPED,NAV;accepted,skipped,_nav,portfolio=v1.replay_portfolio(chosen,daily)
    finally:v1.ACCEPTED,v1.SKIPPED,v1.NAV=old
    for col in ("signal_date","entry_date","exit_date"):accepted[col]=pd.to_datetime(accepted[col])
    target=PROFILES[profile]["target"];overall=metrics(accepted.assign(status="COMPLETED"),target);annual={str(y):metrics(accepted.loc[accepted.signal_date.dt.year.eq(y)].assign(status="COMPLETED"),target) for y in YEARS};concentration=v1.concentration_metrics(accepted)
    gate={"capacity_completed_per_year_gt_50":len(accepted)/10>50,"mean_net_gt_5pct":overall["mean_net"]>.05,"mean_holding_lt_15":overall["mean_holding_sessions"]<15,"2021_2023_each_positive":all(annual[str(y)]["mean_net"] is not None and annual[str(y)]["mean_net"]>0 for y in FORWARD_YEARS),"at_least_8_positive_years":sum(annual[str(y)]["mean_net"] is not None and annual[str(y)]["mean_net"]>0 for y in YEARS)>=8,"mean_excluding_best5_dates_positive":concentration["mean_excluding_best_five_signal_dates"]>0,"top5_date_positive_pnl_share_le_25pct":concentration["top_five_signal_date_positive_pnl_share"]<=.25}
    verdict="BULL_DEEP_SHAKEOUT_ABSORPTION_EDGE" if all(gate.values()) else "BULL_DEEP_SHAKEOUT_ABSORPTION_FAILS_TARGET"
    result={"experiment":EXPERIMENT,"verdict":verdict,"selected_profile":profile,"profile_table":table.replace({np.nan:None}).to_dict("records"),"capacity_accepted_completed_trades":len(accepted),"capacity_skips":len(skipped),"completed_per_year":len(accepted)/10,"overall_2014_2023":overall,"annual":annual,"portfolio":portfolio,"concentration":concentration,"gate":gate,"audit":{**audit,**{f"forward_{k}":v for k,v in fwd_audit.items()},"profile_selected_before_forward_open":True,"feature_after_decision_count":0},"hashes":{"profile_freeze":v1.sha256(PROFILE_FREEZE),"development_outcomes":v1.sha256(DEV_OUTCOMES),"forward_outcomes":v1.sha256(FORWARD_OUTCOMES),"accepted":v1.sha256(ACCEPTED),"skipped":v1.sha256(SKIPPED),"nav":v1.sha256(NAV)}};v1.write_json(RESULT,result)
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(f"# {EXPERIMENT}\n\n`{verdict}`\n\nSelected `{profile}`.\n\n```json\n{json.dumps(gate,indent=2)}\n```\n",encoding="utf-8");return result


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--stage-a",action="store_true");parser.add_argument("--stage-b",action="store_true");args=parser.parse_args()
    if args.stage_a: print(json.dumps(run_stage_a(),indent=2,default=str))
    elif args.stage_b: print(json.dumps(run_stage_b(),indent=2,default=str))
    else: parser.error("choose --stage-a")


if __name__=="__main__": main()
