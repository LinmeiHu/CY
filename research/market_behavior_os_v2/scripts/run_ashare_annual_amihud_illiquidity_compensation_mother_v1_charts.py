#!/usr/bin/env python3
"""Render every frozen annual-Amihud mother candidate for visual review."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
import run_ashare_panic_absorption_12m_chart_rule_discovery_v1 as charts


EXPERIMENT = "ASHARE-ANNUAL-AMIHUD-ILLIQUIDITY-COMPENSATION-MOTHER-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
STAGE_A_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_annual_amihud_illiquidity_compensation_mother_v1_stage_a.py"
)
STAGE_B_RUNNER = REPO / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_annual_amihud_illiquidity_compensation_mother_v1_stage_b.py"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_annual_amihud_illiquidity_compensation_mother_v1"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
CANDIDATES = OUTPUT_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = OUTPUT_ROOT / "stage_b/future_paths.parquet"
OUTCOMES = OUTPUT_ROOT / "stage_b/outcomes.parquet"
STAGE_B_MANIFEST = OUTPUT_ROOT / "stage_b/manifest.json"
CHART_ROOT = OUTPUT_ROOT / "stage_c_charts"
WINDOW_PANEL = CHART_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = CHART_ROOT / "review_ledger.parquet"
REVIEW_CSV = CHART_ROOT / "review_ledger.csv"
CHART_DIR = CHART_ROOT / "individual_charts"
CHART_INDEX = CHART_ROOT / "chart_index.csv"
SHEET_DIR = CHART_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = CHART_ROOT / "review_sheets_by_outcome"
MANIFEST = CHART_ROOT / "manifest.json"
EXPECTED_CANDIDATES = 2286
EXPECTED_HASHES = {
    SPEC: "91acf13d0cb0dd1995ed119ca65eba59f1e652b90ab93eaa5328eb47cb13969d",
    STAGE_A_RUNNER: "7e8b78b8a0b19a6eaa91fa900b2dd655cbe525f201668826abf9619bedd6a617",
    STAGE_B_RUNNER: "010d665ffb74060e222b1d6004c42c1fe96eeaa7f26b73c80aaf1938ebc2b2dd",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    STAGE_A_FREEZE: "a41649bbe985b075b9e76e485b84b736408596de6ffa79102a394ebeba028a5c",
    CANDIDATES: "575f0b7ebd22947b9b61729f91ef7182d492c2261c713bb1681c76aebe8e457e",
    PATHS: "24698655e68e0b9327e0261a1edab64dbf8f1f049e9437a21beb7e17e5cca3c1",
    OUTCOMES: "3f092bf761c70f5a206806fd7247b751b7fd9ab52f5c60b3e5d052fd4a1af620",
    STAGE_B_MANIFEST: "7266af9ddec79904776afbdbbf114de756eddbc17940cf034b0f5dd9e0f36b29",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or chart chronology drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str,str]:
    actual = {}
    for path,expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def write_parquet(frame: pd.DataFrame,path: Path) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect();con.register("frame",frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path,value: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")


def load_inputs() -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    candidates=pd.read_parquet(CANDIDATES);outcomes=pd.read_parquet(OUTCOMES)
    for column in ("formation_start_date","formation_end_date","signal_date","decision_at","available_at","market_latest_source_timestamp"):
        candidates[column]=pd.to_datetime(candidates[column])
    for column in ("signal_date","entry_date","exit_date"):
        outcomes[column]=pd.to_datetime(outcomes[column])
    if len(candidates)!=EXPECTED_CANDIDATES or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if len(outcomes)!=EXPECTED_CANDIDATES or outcomes.event_id.duplicated().any():
        raise ResearchError("outcome identity drift")
    con=duckdb.connect();con.register("keys",candidates[["event_id","symbol","signal_cal_idx","signal_date"]])
    windows=con.execute(f"""
      SELECT k.event_id,k.signal_date,d.symbol,d.trade_date,d.cal_idx,
        d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
        d.step_return,d.trade_status,d.current_day_data_tradable,
        d.current_valid,d.hard_valid,d.available_at,d.decision_at
      FROM read_parquet('{DAILY.as_posix()}') d
      JOIN keys k ON d.symbol=k.symbol
        AND d.cal_idx BETWEEN k.signal_cal_idx-126 AND k.signal_cal_idx+126
      WHERE d.trade_date<=DATE '2020-07-31'
      ORDER BY k.event_id,d.cal_idx
    """).fetch_df();con.close()
    for column in ("signal_date","trade_date","available_at","decision_at"):
        windows[column]=pd.to_datetime(windows[column])
    if windows.event_id.nunique()!=EXPECTED_CANDIDATES:
        raise ResearchError("chart window misses a candidate")
    if windows.trade_date.max()>pd.Timestamp("2020-07-31"):
        raise ResearchError("chart context crossed frozen cap")
    latest=candidates[["available_at","market_latest_source_timestamp"]].max(axis=1)
    if latest.gt(candidates.decision_at).any():
        raise ResearchError("signal annotation arrived after decision")
    return candidates,outcomes,windows


def outcome_bucket(status: str,net_return: float) -> str:
    if status!="COMPLETED" or not math.isfinite(net_return):
        return "NO_COMPLETED_TRADE"
    if net_return>=0.04:return "PROFIT_GE_4PCT"
    if net_return>=0:return "PROFIT_0_TO_4PCT"
    if net_return>-0.10:return "LOSS_0_TO_10PCT"
    return "SEVERE_LOSS"


def build_ledger(candidates: pd.DataFrame,outcomes: pd.DataFrame,windows: pd.DataFrame) -> pd.DataFrame:
    outcome_lookup={str(row.event_id):row for row in outcomes.itertuples(index=False)}
    window_lookup={key:part for key,part in windows.groupby("event_id",sort=False)}
    rows=[]
    ordered=candidates.sort_values(["portfolio_year","symbol","event_id"],kind="mergesort")
    within_year_rank=ordered.groupby("portfolio_year").annual_amihud.rank(method="first",ascending=False)
    within_year_count=ordered.groupby("portfolio_year").event_id.transform("size")
    rank_pct=(within_year_rank-1)/within_year_count.clip(lower=1)
    ordered=ordered.assign(high_illiquidity_rank_pct=rank_pct.to_numpy())
    for event in ordered.itertuples(index=False):
        frame=window_lookup[str(event.event_id)]
        valid=frame.loc[
            frame.current_valid.fillna(False)
            & frame[["coord_open","coord_high","coord_low","coord_close"]].notna().all(axis=1)
        ].sort_values("cal_idx",kind="mergesort")
        pre=valid.loc[valid.cal_idx.lt(int(event.signal_cal_idx))].tail(126)
        signal=valid.loc[valid.cal_idx.eq(int(event.signal_cal_idx))]
        if pre.empty or len(signal)!=1:
            raise ResearchError(f"{event.event_id}: incomplete chart history")
        signal_close=float(signal.iloc[0].coord_close)
        prior_high=float(pre.coord_high.max());prior_low=float(pre.coord_low.min())
        outcome=outcome_lookup[str(event.event_id)]
        net=charts.safe_float(outcome.net_return)
        rows.append({
            "event_id":str(event.event_id),"symbol":str(event.symbol),
            "sleeve":str(event.sleeve),"causal_industry":str(event.causal_industry),
            "portfolio_year":int(event.portfolio_year),"signal_date":pd.Timestamp(event.signal_date),
            "signal_cal_idx":int(event.signal_cal_idx),"chart_number":0,
            "annual_amihud":float(event.annual_amihud),
            "high_illiquidity_rank_pct":float(event.high_illiquidity_rank_pct),
            "valid_daily_observations":int(event.valid_daily_observations),
            "market_regime":str(event.market_regime),
            "market_median_ret20":float(event.market_median_ret20),
            "market_median_ret60":float(event.market_median_ret60),
            "ret20":charts.safe_float(event.ret20),"ret60":charts.safe_float(event.ret60),
            "pre126_return":signal_close/float(pre.coord_close.iloc[0])-1,
            "pre126_position":((signal_close-prior_low)/(prior_high-prior_low) if prior_high>prior_low else math.nan),
            "status":str(outcome.status),"entry_date":pd.Timestamp(outcome.entry_date),
            "entry_price":charts.safe_float(outcome.entry_price),
            "exit_date":pd.Timestamp(outcome.exit_date),"exit_price":charts.safe_float(outcome.exit_price),
            "holding_sessions":charts.safe_float(outcome.holding_sessions),"net_return":net,
            "outcome_bucket":outcome_bucket(str(outcome.status),net),
        })
    ledger=pd.DataFrame(rows);ledger["chart_number"]=np.arange(1,len(ledger)+1,dtype=int)
    return ledger


def render_chart(event: pd.Series,frame: pd.DataFrame,output: Path) -> None:
    signal_date=pd.Timestamp(event.signal_date);signal=frame.loc[frame.trade_date.eq(signal_date)]
    if len(signal)!=1:raise ResearchError(f"{event.event_id}: signal row not unique")
    signal_close=float(signal.iloc[0].coord_close)
    figure,(price_ax,volume_ax)=charts.plt.subplots(2,1,figsize=(13.2,7.4),gridspec_kw={"height_ratios":[4.4,1.0],"hspace":0.05},sharex=True)
    charts.draw_candles(price_ax,frame,signal_close)
    signal_x=charts.mdates.date2num(signal_date.to_pydatetime())
    price_ax.axvline(signal_x,color="#b45309",linewidth=1.4,label="year-end signal")
    for field,marker,color,label in (("entry_date","^","#7b2cbf","entry"),("exit_date","v","#111111","H120 exit")):
        date=getattr(event,field);price_field="entry_price" if field=="entry_date" else "exit_price"
        value=charts.safe_float(getattr(event,price_field))
        if pd.notna(date) and math.isfinite(value):
            x=charts.mdates.date2num(pd.Timestamp(date).to_pydatetime())
            price_ax.scatter(x,value*100/signal_close,marker=marker,s=65,color=color,zorder=8,label=label)
    status=str(event.outcome_bucket)
    if math.isfinite(float(event.net_return)):status+=f" | net {float(event.net_return):+.2%}"
    price_ax.set_title(
        f"{int(event.chart_number):04d} | {event.symbol} | PY{int(event.portfolio_year)} | {event.market_regime} | {status}\n"
        f"annual Amihud {float(event.annual_amihud):.2e} | high-illiquidity rank {float(event.high_illiquidity_rank_pct):.1%} | "
        f"stock r20/r60 {float(event.ret20):+.1%}/{float(event.ret60):+.1%} | market r20/r60 {float(event.market_median_ret20):+.1%}/{float(event.market_median_ret60):+.1%}",
        fontsize=9.5,
    )
    price_ax.set_ylabel("Coordinate price (signal close=100)");price_ax.grid(alpha=0.17,linewidth=0.5)
    handles,labels=price_ax.get_legend_handles_labels();by_label=dict(zip(labels,handles,strict=False))
    price_ax.legend(by_label.values(),by_label.keys(),loc="upper left",ncol=4,fontsize=7)
    valid_turn=frame.loc[frame.turnover_fraction.notna()]
    turn_dates=charts.mdates.date2num(pd.to_datetime(valid_turn.trade_date).to_numpy())
    volume_ax.bar(turn_dates,valid_turn.turnover_fraction*100,width=0.75,color="#8b8b8b",alpha=0.55)
    volume_ax.axvline(signal_x,color="#b45309",linewidth=1.0)
    volume_ax.set_ylabel("Turnover %");volume_ax.grid(alpha=0.12,linewidth=0.4)
    volume_ax.xaxis.set_major_locator(charts.mdates.MonthLocator(interval=2));volume_ax.xaxis.set_major_formatter(charts.mdates.DateFormatter("%Y-%m"))
    for label in volume_ax.get_xticklabels():label.set_rotation(25);label.set_horizontalalignment("right")
    figure.subplots_adjust(left=0.065,right=0.985,top=0.88,bottom=0.10)
    output.parent.mkdir(parents=True,exist_ok=True)
    figure.savefig(output,dpi=105,bbox_inches="tight",facecolor="white",metadata={"Creator":EXPERIMENT,"Title":str(event.event_id)})
    charts.plt.close(figure)


def render_worker(payload: tuple[dict[str,Any],pd.DataFrame,str]) -> dict[str,Any]:
    event_dict,frame,target=payload;event=pd.Series(event_dict);output=Path(target)
    render_chart(event,frame,output)
    return {"chart_number":int(event.chart_number),"event_id":str(event.event_id),"symbol":str(event.symbol),"signal_date":pd.Timestamp(event.signal_date),"portfolio_year":int(event.portfolio_year),"market_regime":str(event.market_regime),"outcome_bucket":str(event.outcome_bucket),"net_return":charts.safe_float(event.net_return),"chart_path":str(output)}


def build_nine_up(index: pd.DataFrame,root: Path,prefix: str) -> list[Path]:
    root.mkdir(parents=True,exist_ok=True);records=index.to_dict("records");paths=[]
    for start in range(0,len(records),9):
        group=records[start:start+9];canvas=Image.new("RGB",(3600,2130),"white");draw=ImageDraw.Draw(canvas)
        for offset,row in enumerate(group):
            source=Image.open(row["chart_path"]).convert("RGB");source.thumbnail((1180,680),Image.Resampling.LANCZOS)
            canvas.paste(source,(10+(offset%3)*1195,35+(offset//3)*695));source.close()
        number=start//9+1;draw.text((15,8),f"{prefix} | sheet {number:03d} | events {start+1}-{start+len(group)}",fill="black")
        target=root/f"sheet_{number:03d}.jpg";canvas.save(target,"JPEG",quality=90,optimize=True);paths.append(target)
    return paths


def run(workers: int,skip_render: bool) -> dict[str,Any]:
    source_hashes=verify_inputs();candidates,outcomes,windows=load_inputs();ledger=build_ledger(candidates,outcomes,windows)
    write_parquet(windows,WINDOW_PANEL);write_parquet(ledger,REVIEW_LEDGER);REVIEW_CSV.parent.mkdir(parents=True,exist_ok=True);ledger.to_csv(REVIEW_CSV,index=False,float_format="%.10g")
    contact=[];outcome_sheets=[]
    if not skip_render:
        groups={key:part for key,part in windows.groupby("event_id",sort=False)};tasks=[]
        for _,event in ledger.iterrows():
            target=CHART_DIR/f"{int(event.chart_number):04d}_{event.symbol.replace('.','_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            tasks.append((event.to_dict(),groups[str(event.event_id)],str(target)))
        with ProcessPoolExecutor(max_workers=max(1,workers)) as executor:
            index=pd.DataFrame(list(executor.map(render_worker,tasks,chunksize=1)))
        index.to_csv(CHART_INDEX,index=False,float_format="%.10g")
        contact=build_nine_up(index,SHEET_DIR,EXPERIMENT)
        for bucket in ("SEVERE_LOSS","LOSS_0_TO_10PCT","PROFIT_0_TO_4PCT","PROFIT_GE_4PCT","NO_COMPLETED_TRADE"):
            subset=index.loc[index.outcome_bucket.eq(bucket)].sort_values(["portfolio_year","symbol","event_id"],kind="mergesort")
            outcome_sheets.extend(build_nine_up(subset,OUTCOME_SHEET_ROOT/bucket.lower(),bucket))
    payload={
        "experiment":EXPERIMENT,"stage":"FULL_FROZEN_CANDIDATE_CHART_CORPUS",
        "source_hashes":source_hashes,"runner_sha256":sha256(Path(__file__)),
        "window_panel_sha256":sha256(WINDOW_PANEL),"review_ledger_sha256":sha256(REVIEW_LEDGER),
        "signals":len(candidates),"charts":0 if skip_render else len(candidates),
        "chronological_contact_sheets":len(contact),"outcome_contact_sheets":len(outcome_sheets),
        "outcome_buckets":{str(k):int(v) for k,v in ledger.outcome_bucket.value_counts().items()},
        "maximum_signal_date":str(candidates.signal_date.max().date()),"maximum_chart_bar_date":str(windows.trade_date.max().date()),
        "all_chronological_sheets_reviewed":False,"all_outcome_sheets_reviewed":False,
        "2022_2024_signal_or_outcome_read":"NO","future_market_function":False,
        "next_step":"REVIEW_ALL_CHRONOLOGICAL_AND_OUTCOME_SHEETS_BEFORE_RULE_FREEZE",
    }
    write_json(MANIFEST,payload);payload["manifest_sha256"]=sha256(MANIFEST);return payload


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--workers",type=int,default=6);parser.add_argument("--skip-render",action="store_true")
    args=parser.parse_args();print(json.dumps(run(args.workers,args.skip_render),ensure_ascii=False,indent=2))


if __name__=="__main__":main()
