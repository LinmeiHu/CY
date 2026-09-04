#!/usr/bin/env python3
"""Frozen bull quiet-platform dual-demand strategy research."""

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
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-QUIET-PLATFORM-DUAL-DEMAND-V24"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_quiet_platform_dual_demand_v24")
SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_repricing_long_translation_v2/"
    "stage_a/candidates_features_2014_2023_frozen.parquet"
)
SOURCE_FREEZE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_repricing_long_translation_v2/"
    "stage_a/stage_a_freeze.json"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
STATE = EXT / "stage_a/causal_daily_market_industry_state.parquet"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_60_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"
PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail-closed V24 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A frozen quiet forty-session inventory platform followed by an upward "
            "non-limit information gap and high-location volume expansion is a demand "
            "repricing event. In a causally known broad BULL market, it is admitted "
            "either when both the market and PIT industry show same-session majority "
            "participation, or, absent that synchronization, when the stock-specific "
            "opening information jump is at least 2%."
        ),
        "independence": (
            "No downward collapse gap, repair zone, V6/V7/V26/V27 event identity, "
            "feature, signal, or outcome is used."
        ),
        "base_signal": {
            "identity": "exact frozen ASHARE-QUIET-INVENTORY-INFORMATION-GAP-BREAKOUT-V1 candidates",
            "source_sha256": v1.sha256(SOURCE),
            "source_freeze_sha256": v1.sha256(SOURCE_FREEZE),
            "signal_clock": "completed daily close",
        },
        "causal_bull": v1.contract_value()["market_regime"],
        "pit_industry_health": "members>=5, median ret20>0, positive-ret20 share>50%",
        "admission": {
            "SYNCHRONIZED_MAJORITY_DEMAND": (
                "market daily median return>0 and positive-member share>50%; "
                "PIT industry daily median return>0 and positive-member share>50%"
            ),
            "IDIOSYNCRATIC_INFORMATION_JUMP": (
                "synchronized majority demand is false and frozen signal open_gap>=2%"
            ),
            "combination": "logical OR; the two lanes are mutually exclusive",
        },
        "entry": "first legal next daily open within three market sessions",
        "target": "+15% coordinate standing target from first T+1-sellable session",
        "time_stop": "completed H15 state, then next legal daily open",
        "failure_stop": "none",
        "round_trip_cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "collision_rank": v1.contract_value()["portfolio"]["collision_rank"],
        "required_gate": {
            "capacity_accepted_completed_trades_2014_2023_gt": 500,
            "mean_net_return_gt": 0.03,
            "mean_holding_sessions_le": 15,
            "each_2019_2023_mean_positive": True,
            "mean_excluding_best_five_signal_dates_positive": True,
            "top_five_signal_date_positive_pnl_share_le": 0.25,
        },
        "evidence_governance": {
            "2014_2018": "mechanism discovery period",
            "2019_2023": "post-discovery chronological stability; not pristine validation",
            "reason_not_pristine": "outcomes have been observed during autonomous iterative research",
            "signals_or_features_after_2023": False,
            "post_2023_data": "permitted only to resolve pre-2024 positions",
        },
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(SPEC, {
        "experiment": EXPERIMENT,
        "status": "FROZEN_CAUSAL_BULL_DUAL_DEMAND_CONTRACT",
        "contract_sha256": v1.sha256(CONTRACT),
        "runner_sha256": v1.sha256(Path(__file__)),
        "source_sha256": v1.sha256(SOURCE),
        "source_freeze_sha256": v1.sha256(SOURCE_FREEZE),
        "daily_sha256": v1.sha256(v1.DAILY),
        "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
        "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL),
        "execution_engine_sha256": v1.sha256(Path(v2.__file__)),
        "portfolio_engine_sha256": v1.sha256(Path(v1.__file__)),
    })
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_state() -> pd.DataFrame:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"""
          COPY (
            WITH d AS (
              SELECT trade_date,causal_industry,symbol,step_return,decision_at
              FROM read_parquet('{v1.DAILY}')
              WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
                AND hard_valid AND history_valid AND current_valid
                AND corporate_action_valid AND NOT corporate_action_blocking
                AND current_day_data_tradable AND market_rule_valid
                AND trade_status=1 AND NOT is_st
            ), m AS (
              SELECT trade_date,median(step_return) AS market_median_ret1,
                avg((step_return>0)::INT) AS market_positive_ret1_share,
                count(*) AS market_member_count,max(decision_at) AS market_state_latest
              FROM d GROUP BY trade_date
            ), i AS (
              SELECT trade_date,causal_industry,median(step_return) AS industry_median_ret1,
                avg((step_return>0)::INT) AS industry_positive_ret1_share,
                count(*) AS industry_member_count,max(decision_at) AS industry_state_latest
              FROM d WHERE causal_industry IS NOT NULL
              GROUP BY trade_date,causal_industry
            )
            SELECT * FROM m JOIN i USING(trade_date)
          ) TO '{STATE}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """)
    finally:
        con.close()
    return v1.read_parquet_duckdb(STATE)


def build_candidates() -> pd.DataFrame:
    con = duckdb.connect()
    try:
        con.execute(f"""
          COPY (
            WITH x AS (
              SELECT c.*,r.market_regime,r.market_median_ret20,
                r.market_positive_ret20_share,r.market_median_ret60,
                r.market_positive_ret60_share,
                r.latest_source_timestamp AS market_latest_source,
                i.industry_median_ret20,i.industry_positive_ret20_share,
                i.industry_ret20_percentile,i.industry_n20,
                i.latest_source_timestamp AS industry_latest_source,
                s.market_median_ret1,s.market_positive_ret1_share,s.market_member_count,
                s.industry_median_ret1,s.industry_positive_ret1_share,s.industry_member_count,
                s.market_state_latest,s.industry_state_latest,
                c.ret20-i.industry_median_ret20 AS stock_minus_industry_ret20,
                greatest(c.decision_at,r.latest_source_timestamp,i.latest_source_timestamp,
                  s.market_state_latest,s.industry_state_latest,c.formation_known_at)
                  AS feature_latest_timestamp,
                r.market_regime='BULL' AND i.industry_n20>=5
                  AND i.industry_median_ret20>0 AND i.industry_positive_ret20_share>0.50
                  AS pass_base_bull_industry,
                s.market_median_ret1>0 AND s.market_positive_ret1_share>0.50
                  AND s.industry_median_ret1>0 AND s.industry_positive_ret1_share>0.50
                  AS pass_SYNCHRONIZED_MAJORITY_DEMAND
              FROM read_parquet('{SOURCE}') c
              JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
              JOIN read_parquet('{v1.INDUSTRY_PANEL}') i USING(trade_date,causal_industry)
              JOIN read_parquet('{STATE}') s USING(trade_date,causal_industry)
              WHERE c.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
            ), y AS (
              SELECT *,pass_base_bull_industry AND NOT pass_SYNCHRONIZED_MAJORITY_DEMAND
                AND open_gap>=0.02 AS pass_IDIOSYNCRATIC_INFORMATION_JUMP
              FROM x
            )
            SELECT *,pass_base_bull_industry AS pass_BULL_ONLY,
              CASE WHEN pass_SYNCHRONIZED_MAJORITY_DEMAND THEN 'SYNCHRONIZED_MAJORITY_DEMAND'
                   ELSE 'IDIOSYNCRATIC_INFORMATION_JUMP' END AS admission_lane
            FROM y
            WHERE pass_base_bull_industry AND
              (pass_SYNCHRONIZED_MAJORITY_DEMAND OR pass_IDIOSYNCRATIC_INFORMATION_JUMP)
            ORDER BY trade_date,symbol
          ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """)
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("trade_date", "signal_date", "decision_at", "available_at",
                   "formation_known_at", "market_latest_source", "industry_latest_source",
                   "market_state_latest", "industry_state_latest", "feature_latest_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    causal = (frame.available_at.le(frame.decision_at)
              & frame.formation_known_at.le(frame.decision_at)
              & frame.feature_latest_timestamp.le(frame.decision_at))
    exclusive = frame.pass_SYNCHRONIZED_MAJORITY_DEMAND.astype(int) + frame.pass_IDIOSYNCRATIC_INFORMATION_JUMP.astype(int)
    if frame.event_id.duplicated().any() or not causal.all() or not exclusive.eq(1).all():
        raise ResearchError("candidate identity, exclusivity, or causal timestamp failure")
    return frame


def blind_sample(frame: pd.DataFrame, count: int = 60) -> pd.DataFrame:
    work = frame.copy(); work["year"] = work.signal_date.dt.year
    work["hash_order"] = work.event_id.map(lambda x: hashlib.sha256(str(x).encode()).hexdigest())
    pieces = [part.sort_values("hash_order").head(1)
              for _, part in work.groupby(["year", "sleeve", "admission_lane"], sort=True)]
    sample = pd.concat(pieces, ignore_index=True).sort_values("hash_order").head(count)
    if len(sample) < count:
        rest = work.loc[~work.event_id.isin(sample.event_id)]
        sample = pd.concat([sample, rest.sort_values("hash_order").head(count-len(sample))], ignore_index=True)
    sample = sample.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    if len(sample) != count:
        raise ResearchError(f"blind sample has {len(sample)} rows")
    sample.insert(0, "chart_id", [f"BULL-DUAL-{i:03d}" for i in range(1, count+1)])
    sample.to_csv(BLIND_INDEX, index=False)
    return sample


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())})
    con = duckdb.connect(); con.register("symbols", symbols)
    daily = con.execute(f"""SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,
      d.coord_close,d.turnover_fraction,d.ret20 FROM read_parquet('{v1.DAILY}')d
      JOIN symbols USING(symbol) WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
      ORDER BY d.symbol,d.trade_date""").fetchdf(); con.close()
    daily.trade_date = pd.to_datetime(daily.trade_date)
    groups = {k:p.reset_index(drop=True) for k,p in daily.groupby("symbol", sort=False)}
    regime = pd.read_parquet(v1.SOURCE_REGIME); regime.trade_date = pd.to_datetime(regime.trade_date)
    state = pd.read_parquet(STATE); state.trade_date = pd.to_datetime(state.trade_date)
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            part = groups[str(event.symbol)]
            pos = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
            if len(pos) != 1: raise ResearchError(f"missing chart signal {event.event_id}")
            stock = part.iloc[max(0,int(pos[0])-119):int(pos[0])+1].copy(); start = stock.trade_date.min()
            market = regime.loc[regime.trade_date.between(start,event.signal_date)]
            st = state.loc[state.trade_date.between(start,event.signal_date)]
            market1 = st.groupby("trade_date",as_index=False).first()
            ind = st.loc[st.causal_industry.eq(event.causal_industry)].sort_values("trade_date")
            fig,axes=v1.plt.subplots(4,1,figsize=(11.7,8.3),gridspec_kw={"height_ratios":[2.5,.7,1,1]})
            x=v1.mdates.date2num(stock.trade_date); colors=np.where(stock.coord_close.ge(stock.coord_open),'#dc2626','#059669')
            axes[0].vlines(x,stock.coord_low,stock.coord_high,color=colors,linewidth=.65)
            body_low=np.minimum(stock.coord_open,stock.coord_close);body_h=np.maximum(abs(stock.coord_close-stock.coord_open),stock.coord_close.abs()*.0005)
            axes[0].bar(x,body_h,bottom=body_low,width=.65,color=colors,edgecolor=colors,linewidth=.3,label='Daily candle')
            axes[0].axvline(pd.Timestamp(event.signal_date),color='#dc2626',linestyle='--',label='Signal close')
            axes[0].axhline(float(event.platform_high),color='#ea580c',linestyle=':',label='Frozen platform ceiling')
            axes[0].set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry} | {event.admission_lane}",fontproperties=v1.CJK_FONT)
            axes[0].legend(loc='upper left',fontsize=8,ncol=3);axes[0].grid(alpha=.2)
            axes[1].bar(stock.trade_date,stock.turnover_fraction,color=colors,width=.75,alpha=.7);axes[1].axvline(pd.Timestamp(event.signal_date),color='#dc2626',linestyle='--');axes[1].set_ylabel('Turnover');axes[1].grid(alpha=.2)
            axes[2].plot(market.trade_date,market.market_median_ret20,color='#166534',label='Market median ret20')
            ax2=axes[2].twinx();ax2.plot(market1.trade_date,market1.market_positive_ret1_share,color='#0284c7',alpha=.7,label='Market daily breadth');ax2.axhline(.5,color='#0284c7',linestyle=':',linewidth=.7)
            axes[2].axhline(0,color='black',linewidth=.7);axes[2].set_ylabel('Market');axes[2].grid(alpha=.2);axes[2].legend(loc='upper left',fontsize=8);ax2.legend(loc='upper right',fontsize=8)
            axes[3].plot(ind.trade_date,ind.industry_positive_ret1_share,color='#7c3aed',label='Industry daily breadth');axes[3].plot(stock.trade_date,stock.ret20,color='#b45309',label='Stock ret20');axes[3].axhline(.5,color='#7c3aed',linestyle=':',linewidth=.7);axes[3].axhline(0,color='black',linewidth=.7);axes[3].set_ylabel('Industry / stock');axes[3].legend(loc='upper left',fontsize=8,ncol=2);axes[3].grid(alpha=.2);axes[3].xaxis.set_major_formatter(v1.mdates.DateFormatter('%Y-%m'))
            fig.text(.01,.01,f"Outcome-blind. open gap {event.open_gap:+.2%}; market daily breadth {event.market_positive_ret1_share:.1%}; industry daily breadth {event.industry_positive_ret1_share:.1%}. No post-signal bar.",fontsize=8)
            fig.tight_layout(rect=[0,.035,1,1]);pdf.savefig(fig,dpi=160);v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract(); state = build_state(); frame = build_candidates(); sample = blind_sample(frame); render_blind_charts(sample)
    audit = {
        "candidate_identity_duplicate_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),
        "formation_after_decision_count": int(frame.formation_known_at.gt(frame.decision_at).sum()),
        "admission_overlap_count": int((frame.pass_SYNCHRONIZED_MAJORITY_DEMAND & frame.pass_IDIOSYNCRATIC_INFORMATION_JUMP).sum()),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
    }
    if any(audit.values()): raise ResearchError(str(audit))
    freeze = {"experiment": EXPERIMENT, **hashes, "runner_sha256": v1.sha256(Path(__file__)),
        "state_sha256": v1.sha256(STATE), "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF), "source_sha256": v1.sha256(SOURCE),
        "state_rows": len(state), "candidate_count": len(frame), "blind_chart_count": len(sample),
        "lane_counts": frame.admission_lane.value_counts().sort_index().astype(int).to_dict(),
        "annual_counts": frame.groupby(frame.signal_date.dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict(),
        "audit": audit, "outcomes_opened": False}
    v1.write_json(FREEZE, freeze); return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze=json.loads(FREEZE.read_text());expected={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"runner_sha256":v1.sha256(Path(__file__)),"state_sha256":v1.sha256(STATE),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"source_sha256":v1.sha256(SOURCE)}
    drift={k:[freeze.get(k),v]for k,v in expected.items()if freeze.get(k)!=v}
    if drift:raise ResearchError(f"Stage-A drift {drift}")
    return freeze


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:return {"completed_trades":0,"mean_net":None,"median_net":None,"win_rate":None,"severe_loss10":None,"mean_holding_sessions":None}
    return {"completed_trades":len(frame),"mean_net":float(frame.net_return.mean()),"median_net":float(frame.net_return.median()),"win_rate":float(frame.net_return.gt(0).mean()),"severe_loss10":float(frame.net_return.le(-.10).mean()),"mean_holding_sessions":float(frame.holding_sessions.mean())}


def render_report(result: dict[str, Any]) -> None:
    f=result["full_2014_2023"];lines=[f"# {EXPERIMENT}","","## Frozen strategy","",f"- Spec hash: `{result['contract_sha256']}`","- Base: frozen quiet-inventory upward information-gap breakout.","- Admission A: same-day market and PIT-industry majority demand.","- Admission B: if A is absent, stock-specific open gap >=2%.","- Entry: next legal daily open; target +15%; H15; 40 bp round trip.","","## Capacity-constrained result","",f"- Completed trades: {f['completed_trades']} ({result['average_trades_per_year']:.1f}/year)",f"- Mean / median net: {f['mean_net']:.4%} / {f['median_net']:.4%}",f"- Win / severe10: {f['win_rate']:.2%} / {f['severe_loss10']:.2%}",f"- Mean holding: {f['mean_holding_sessions']:.2f} sessions",f"- CAGR / MaxDD / Sharpe: {result['portfolio']['cagr']:.2%} / {result['portfolio']['max_drawdown']:.2%} / {result['portfolio']['sharpe']:.3f}","","## Annual evidence","","|Year|Trades|Mean net|Median net|Mean hold|","|---:|---:|---:|---:|---:|"]
    for y,m in result['annual'].items():lines.append(f"|{y}|{m['completed_trades']}|{m['mean_net']:.2%}|{m['median_net']:.2%}|{m['mean_holding_sessions']:.2f}|")
    lines += ["","## Governance","","2014–2018 is the iterative discovery period. 2019–2023 is a chronological stability check, not pristine external validation, because outcomes were observed during this research lane.","",f"Verdict: **{result['verdict']}**","",f"Blind chart PDF: `{BLIND_PDF.relative_to(ROOT)}`"]
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text("\n".join(lines)+"\n",encoding="utf-8")


def run_stage_b() -> dict[str, Any]:
    freeze=verify_stage_a();frame=v1.read_parquet_duckdb(CANDIDATES)
    old_profiles,old_outcomes=v2.PROFILES,v2.OUTCOMES
    try:v2.PROFILES={PROFILE:{"horizon":15,"target":.15}};v2.OUTCOMES=OUTCOMES;outcomes,outcome_audit=v2.build_outcomes(frame)
    finally:v2.PROFILES, v2.OUTCOMES=old_profiles,old_outcomes
    features=frame[["event_id","admission_lane","industry_positive_ret20_share","stock_minus_industry_ret20","turnover_expansion"]]
    trades=outcomes.loc[outcomes.profile.eq(PROFILE)].merge(features,on="event_id",how="left",validate="one_to_one")
    daily=v1.load_trade_daily(trades.loc[trades.status.eq("COMPLETED"),"symbol"].astype(str).unique().tolist())
    old_paths=(v1.ACCEPTED,v1.SKIPPED,v1.NAV)
    try:v1.ACCEPTED,v1.SKIPPED,v1.NAV=ACCEPTED,SKIPPED,NAV;accepted,skipped,nav,portfolio=v1.replay_portfolio(trades,daily)
    finally:v1.ACCEPTED,v1.SKIPPED,v1.NAV=old_paths
    accepted.signal_date=pd.to_datetime(accepted.signal_date);accepted.entry_date=pd.to_datetime(accepted.entry_date);accepted.exit_date=pd.to_datetime(accepted.exit_date)
    full=_summary(accepted);annual={str(y):_summary(accepted.loc[accepted.signal_date.dt.year.eq(y)])for y in YEARS};concentration=v1.concentration_metrics(accepted)
    lanes={lane:_summary(part) for lane,part in accepted.groupby("admission_lane",sort=True)}
    gate={"capacity_accepted_completed_trades_gt_500":len(accepted)>500,"mean_net_gt_3pct":full['mean_net']>.03,"mean_holding_le_15":full['mean_holding_sessions']<=15,"2019_2023_each_positive":all(annual[str(y)]['mean_net'] is not None and annual[str(y)]['mean_net']>0 for y in range(2019,2024)),"mean_ex_best5_positive":concentration['mean_excluding_best_five_signal_dates']>0,"top5_positive_pnl_share_le_25pct":concentration['top_five_signal_date_positive_pnl_share']<=.25}
    audit={**outcome_audit,"candidate_feature_after_decision_count":int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),"post_2023_signal_or_feature_row_count":int(frame.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),"negative_cash_count":portfolio['negative_cash_count'],"max_k_violation_count":portfolio['max_k_violation_count']}
    if any(audit.values()):raise ResearchError(f"audit failed {audit}")
    result={"experiment":EXPERIMENT,"contract_sha256":freeze['contract_sha256'],"spec_sha256":freeze['spec_sha256'],"profile":PROFILE,"capacity_accepted_completed_trades":len(accepted),"capacity_skips":len(skipped),"average_trades_per_year":len(accepted)/10,"full_2014_2023":full,"annual":annual,"admission_lanes":lanes,"portfolio":portfolio,"concentration":concentration,"gate":gate,"audit":audit,"repository_2024_plus_rows_used_for_signal_or_feature":0,"post_2023_rows_used_only_for_pre_2024_trade_resolution":True,"verdict":"BULL_QUIET_PLATFORM_DUAL_DEMAND_TARGET_MET"if all(gate.values())else"BULL_QUIET_PLATFORM_DUAL_DEMAND_FAILS_TARGET","hashes":{"outcomes":v1.sha256(OUTCOMES),"accepted":v1.sha256(ACCEPTED),"skipped":v1.sha256(SKIPPED),"nav":v1.sha256(NAV),"blind_pdf":v1.sha256(BLIND_PDF)}}
    v1.write_json(RESULT,result);render_report(result);return result


def main()->None:
    p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
    if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
    elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
    else:p.error('choose --stage-a or --stage-b')


if __name__=='__main__':main()
