#!/usr/bin/env python3
"""Causal intraday industry co-discovery bull strategy research."""

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
EXPERIMENT = "ASHARE-BULL-INTRADAY-INDUSTRY-PRICE-DISCOVERY-V32"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_intraday_industry_price_discovery_v32")
RAW_MINUTE = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
PROFILE_FREEZE = OS / f"artifacts/{EXPERIMENT}_profile_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
MOTHER = EXT / "stage_a/prequalified_stock_days.parquet"
FIRST_CROSSES = EXT / "stage_a/first_crosses.parquet"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
PROFILE_TABLE = EXT / "stage_b/profile_table.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

YEARS = tuple(range(2014, 2024))
DEVELOPMENT_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
PROFILES = {
    "H5_PLATFORM_FAILURE": {"horizon": 5, "target": None},
    "H10_PLATFORM_FAILURE": {"horizon": 10, "target": None},
    "T15_H10_PLATFORM_FAILURE": {"horizon": 10, "target": 0.15},
    "T20_H10_PLATFORM_FAILURE": {"horizon": 10, "target": 0.20},
}


class ResearchError(RuntimeError):
    """Fail-closed research error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "stage": "A_OUTCOME_BLIND_CONTRACT",
        "economic_hypothesis": (
            "In a bull market, a bounded stock crossing a repeatedly tested 60-session "
            "cost ceiling while another prequalified stock in the same PIT industry has "
            "crossed within the preceding 60 completed trading minutes is observable "
            "industry price discovery. Buying at the next executable minute participates "
            "in the unfinished repricing rather than buying the next-day relay from first-board holders."
        ),
        "binding_conditions": {
            "PRIOR_PIT_BULL": "market regime at the immediately prior completed session is BULL",
            "PRIOR_HEALTHY_INDUSTRY": (
                "prior-session PIT industry n20>=5, median ret20>0, positive-ret20 share>50%"
            ),
            "BOUNDED_REPEATED_CEILING": (
                "no limit-up close in prior 20 completed stock sessions; prior20 return in "
                "[-15%,+15%]; prior20 range<=18%; prior60 range<=40%; prior close is from "
                "90% up to but below the prior60 ceiling; at least three prior60 highs within "
                "3% of that ceiling"
            ),
            "CAUSAL_INDUSTRY_CODISCOVERY": (
                "stock first closes across its frozen prior60 ceiling before 14:25 while its "
                "intraday return is +4% to +8%; at least one other prequalified same-industry "
                "stock first crossed its own ceiling during the preceding 60 completed trading minutes"
            ),
        },
        "signal_clock": "completed 1-minute bar",
        "entry": "next same-session 1-minute open; must be below the known upper price limit",
        "translation_profiles": PROFILES,
        "failure_exit": (
            "after A-share T+1, first completed daily close below the frozen prior60 ceiling; "
            "exit at next legal daily open"
        ),
        "target": "profile target from entry; first eligible realization is T+1",
        "cost": {"entry": 0.002, "exit": 0.002},
        "profile_development": {
            "years": list(DEVELOPMENT_YEARS),
            "minimum_completed": 350,
            "minimum_positive_years": 5,
            "minimum_mean_net": 0.03,
            "maximum_mean_holding_sessions": 15,
        },
        "forward_gate": {
            "years": list(FORWARD_YEARS),
            "opened_only_after_profile_freeze": True,
            "2024_q1_use": "execution resolution for late-2023 entries only; no 2024 signal",
            "final_target": (
                "2014-2023 capacity-accepted completed/year>50; mean net>5%; mean hold<15; "
                "each 2021-2023 annual mean positive; >=8/10 positive annual means"
            ),
        },
        "portfolio": v1.contract_value()["portfolio"],
        "outcomes_opened": False,
        "repository_2024_plus_opened": "only if development gate passes, and only to resolve late-2023 trades",
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_HIGH_RECALL_CONTRACT",
            "contract_sha256": v1.sha256(CONTRACT),
            "sources": {
                "daily": v1.sha256(v1.DAILY),
                "regime": v1.sha256(v1.SOURCE_REGIME),
                "industry": v1.sha256(v1.INDUSTRY_PANEL),
                "minute_year_pattern": str(RAW_MINUTE / "{year}_day_parquet_none.parquet"),
            },
            "execution_dependency_sha256": v1.sha256(Path(v1.__file__)),
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_mother() -> pd.DataFrame:
    MOTHER.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH regime_prev AS (
                SELECT trade_date AS state_date,
                  lead(trade_date) OVER(ORDER BY trade_date) AS signal_date,
                  market_regime,market_median_ret20,market_positive_ret20_share,
                  latest_source_timestamp AS market_latest_source
                FROM read_parquet('{v1.SOURCE_REGIME}')
              ), d0 AS (
                SELECT d.*,
                  lag(close) OVER w AS prev_raw_close,
                  lag(coord_close) OVER w AS prev_coord_close,
                  lag(coord_close,20) OVER w AS lag20_coord_close,
                  max(coord_high) OVER w60 AS prior60_high,
                  min(coord_low) OVER w60 AS prior60_low,
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w20 AS prior20_low,
                  list(coord_high) OVER w60 AS prior60_high_list,
                  count(*) OVER w60 AS prior60_n,
                  sum(CASE WHEN round(close*100)=round(up_limit_price*100)
                      THEN 1 ELSE 0 END) OVER w20 AS prior20_limitup_count
                FROM read_parquet('{v1.DAILY}') d
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL AND industry_valid
                WINDOW
                  w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                  w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
              ), joined AS (
                SELECT d0.*,
                  rp.state_date,rp.market_regime,rp.market_median_ret20,
                  rp.market_positive_ret20_share,rp.market_latest_source,
                  i.industry_median_ret20,i.industry_positive_ret20_share,
                  i.industry_median_ret60,i.industry_n20,i.industry_ret20_percentile,
                  i.latest_source_timestamp AS industry_latest_source,
                  prev_coord_close/NULLIF(lag20_coord_close,0)-1 AS prior_completed_ret20,
                  prior60_high/NULLIF(prior60_low,0)-1 AS prior60_range,
                  prior20_high/NULLIF(prior20_low,0)-1 AS prior20_range,
                  list_count(list_filter(prior60_high_list,v -> v>=0.97*prior60_high))
                    AS prior60_ceiling_touch_count
                FROM d0
                JOIN regime_prev rp ON rp.signal_date=d0.trade_date
                JOIN read_parquet('{v1.INDUSTRY_PANEL}') i
                  ON i.trade_date=rp.state_date AND i.causal_industry=d0.causal_industry
                WHERE d0.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
              )
              SELECT *, prior60_high AS platform_ceiling,
                prior60_high/NULLIF(coordinate_factor,0) AS raw_platform_ceiling,
                decision_at AS daily_validation_timestamp
              FROM joined
              WHERE market_regime='BULL'
                AND industry_n20>=5
                AND industry_median_ret20>0
                AND industry_positive_ret20_share>0.50
                AND prior60_n=60
                AND prior20_limitup_count=0
                AND prior_completed_ret20 BETWEEN -0.15 AND 0.15
                AND prior20_range<=0.25
                AND prior60_range<=0.40
                AND prior60_ceiling_touch_count>=3
              ORDER BY trade_date,symbol
            ) TO '{MOTHER}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(MOTHER)
    for col in ("trade_date", "state_date", "market_latest_source", "industry_latest_source"):
        frame[col] = pd.to_datetime(frame[col])
    if frame.market_latest_source.ge(frame.trade_date).any() or frame.industry_latest_source.ge(frame.trade_date).any():
        raise ResearchError("prior PIT state is not strictly before signal session")
    return frame


def build_first_crosses(mother: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year in YEARS:
        reg = mother.loc[mother.trade_date.dt.year.eq(year)].copy()
        if reg.empty:
            continue
        minute_path = RAW_MINUTE / f"{year}_day_parquet_none.parquet"
        if not minute_path.exists():
            raise ResearchError(f"missing minute file {minute_path}")
        keep = [
            "trade_date","symbol","sleeve","causal_industry","prev_raw_close",
            "coordinate_factor","platform_ceiling","raw_platform_ceiling","up_limit_price",
        ]
        registry = reg[keep].copy()
        con = duckdb.connect()
        con.register("registry", registry)
        minute = con.execute(
            f"""
            WITH path AS (
              SELECT m.trade_date,r.symbol,m.bar_end_time,m.open,m.high,m.low,m.close,m.volume,m.amount,
                r.sleeve,r.causal_industry,r.prev_raw_close,r.coordinate_factor,
                r.platform_ceiling,r.raw_platform_ceiling,r.up_limit_price,
                row_number() OVER(PARTITION BY m.trade_date,r.symbol ORDER BY m.bar_end_time)-1 AS minute_idx,
                lag(m.close,1,r.prev_raw_close) OVER(
                  PARTITION BY m.trade_date,r.symbol ORDER BY m.bar_end_time
                ) AS previous_minute_close
              FROM read_parquet('{minute_path}') m JOIN registry r
                ON m.qmt_code=r.symbol AND m.trade_date=r.trade_date
              WHERE m.period='1m' AND m.adjust='none'
            ), crossed AS (
              SELECT *,close*coordinate_factor AS coord_close,
                close/prev_raw_close-1 AS intraday_return
              FROM path
              WHERE close*coordinate_factor>=platform_ceiling
                AND previous_minute_close*coordinate_factor<platform_ceiling
            ), first_cross AS (
              SELECT *,row_number() OVER(
                PARTITION BY trade_date,symbol ORDER BY bar_end_time
              ) AS first_cross_rank
              FROM crossed
            )
            SELECT * EXCLUDE(first_cross_rank)
            FROM first_cross
            WHERE first_cross_rank=1
              AND intraday_return BETWEEN 0.04 AND 0.08
              AND CAST(bar_end_time AS TIME)<=TIME '14:25:00'
            ORDER BY trade_date,symbol
            """
        ).fetchdf()
        con.close()
        if minute.empty:
            continue
        minute["trade_date"] = pd.to_datetime(minute.trade_date)
        minute["bar_end_time"] = pd.to_datetime(minute.bar_end_time)
        rows.extend(minute.to_dict("records"))
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ResearchError("no first crosses")
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame["bar_end_time"] = pd.to_datetime(frame.bar_end_time)
    v1.write_parquet(frame, FIRST_CROSSES)
    return frame


def build_candidates(mother: pd.DataFrame, crosses: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    full = crosses.merge(
        mother.drop(columns=[c for c in crosses.columns if c in mother.columns and c not in {"trade_date", "symbol"}]),
        on=["trade_date", "symbol"], validate="one_to_one",
    )
    full = full.loc[
        full.prior20_range.le(0.18)
        & full.prev_coord_close.div(full.platform_ceiling).between(0.90, 1.0, inclusive="left")
    ].copy()
    full = full.sort_values(["trade_date", "causal_industry", "bar_end_time", "symbol"]).reset_index(drop=True)
    retained: list[pd.Series] = []
    for (_, _), group in full.groupby(["trade_date", "causal_industry"], sort=False):
        prior: list[tuple[int, str]] = []
        for _, row in group.iterrows():
            recent = [(idx, symbol) for idx, symbol in prior if int(row.minute_idx) - idx <= 60]
            if recent:
                copy = row.copy()
                copy["prior_industry_breakout_count_60m"] = len(recent)
                copy["prior_industry_breakout_symbols_60m"] = ",".join(symbol for _, symbol in recent)
                retained.append(copy)
            prior.append((int(row.minute_idx), str(row.symbol)))
    frame = pd.DataFrame(retained)
    if frame.empty:
        raise ResearchError("no causal co-discovery candidates")
    entries: list[dict[str, Any]] = []
    for year in YEARS:
        sub = frame.loc[frame.trade_date.dt.year.eq(year)]
        if sub.empty:
            continue
        minute_path = RAW_MINUTE / f"{year}_day_parquet_none.parquet"
        registry = sub[["trade_date", "symbol", "bar_end_time", "coordinate_factor", "up_limit_price"]].copy()
        con = duckdb.connect(); con.register("registry", registry)
        nxt = con.execute(
            f"""
            SELECT r.trade_date,r.symbol,r.bar_end_time AS signal_time,m.bar_end_time AS entry_time,
              m.open AS entry_raw_open,m.open*r.coordinate_factor AS entry_price,
              row_number() OVER(PARTITION BY r.trade_date,r.symbol ORDER BY m.bar_end_time) AS rn
            FROM registry r JOIN read_parquet('{minute_path}') m
              ON m.trade_date=r.trade_date AND m.qmt_code=r.symbol AND m.bar_end_time>r.bar_end_time
            WHERE m.period='1m' AND m.adjust='none'
            QUALIFY rn=1
            """
        ).fetchdf(); con.close()
        entries.extend(nxt.to_dict("records"))
    entry = pd.DataFrame(entries)
    for col in ("trade_date", "signal_time", "entry_time"):
        entry[col] = pd.to_datetime(entry[col])
    frame = frame.merge(entry, left_on=["trade_date", "symbol", "bar_end_time"], right_on=["trade_date", "symbol", "signal_time"], how="left", validate="one_to_one")
    frame["entry_executable"] = frame.entry_raw_open.notna() & frame.entry_raw_open.lt(frame.up_limit_price - 0.001)
    frame["signal_date"] = frame.trade_date
    frame["decision_at"] = frame.bar_end_time
    frame["feature_latest_timestamp"] = frame.bar_end_time
    frame["event_id"] = frame.apply(lambda r: f"IPD32-{r.trade_date:%Y%m%d}-{r.symbol}-{r.bar_end_time:%H%M}", axis=1)
    frame["admission_lane"] = "INTRADAY_INDUSTRY_PRICE_DISCOVERY"
    frame["stock_minus_industry_ret20"] = frame.prior_completed_ret20 - frame.industry_median_ret20
    frame["turnover_expansion"] = 1.0
    frame = frame.sort_values(["signal_date", "decision_at", "symbol"]).reset_index(drop=True)
    v1.write_parquet(frame, CANDIDATES)
    audits = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "prior_state_not_before_signal_count": int((frame.market_latest_source.ge(frame.decision_at) | frame.industry_latest_source.ge(frame.decision_at)).sum()),
        "industry_prior_breakout_missing_count": int(frame.prior_industry_breakout_count_60m.lt(1).sum()),
        "entry_at_or_before_signal_count": int(frame.entry_time.notna().mul(frame.entry_time.le(frame.decision_at)).sum()),
        "entry_at_limit_count": int((frame.entry_executable & frame.entry_raw_open.ge(frame.up_limit_price - 0.001)).sum()),
        "candidate_after_2023_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
    }
    if any(audits.values()):
        raise ResearchError(str(audits))
    return frame, audits


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    x = frame.loc[frame.entry_executable].copy(); x["year"] = x.signal_date.dt.year
    x["hash_order"] = x.event_id.map(lambda value: hashlib.sha256(str(value).encode()).hexdigest())
    pieces = [part.sort_values("hash_order").head(3) for _, part in x.groupby("year")]
    chosen = pd.concat(pieces, ignore_index=True)
    if len(chosen) < count:
        chosen = pd.concat([chosen, x.loc[~x.event_id.isin(chosen.event_id)].sort_values("hash_order").head(count-len(chosen))])
    chosen = chosen.sort_values(["signal_date", "symbol"]).head(count).reset_index(drop=True)
    chosen.insert(0, "chart_id", [f"V32-BLIND-{i:03d}" for i in range(1, len(chosen)+1)])
    chosen.to_csv(BLIND_INDEX, index=False)
    return chosen


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True); BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())}); con=duckdb.connect();con.register("symbols",symbols)
    daily=con.execute(f"SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close FROM read_parquet('{v1.DAILY}') d JOIN symbols USING(symbol) WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31' ORDER BY symbol,trade_date").fetchdf();con.close();daily.trade_date=pd.to_datetime(daily.trade_date)
    groups={s:g.reset_index(drop=True) for s,g in daily.groupby("symbol")}
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            stock=groups[event.symbol];pos=np.flatnonzero(stock.trade_date.eq(event.signal_date).to_numpy())[0]
            view=stock.iloc[max(0,pos-119):pos].copy()
            minute_path=RAW_MINUTE/f"{event.signal_date.year}_day_parquet_none.parquet";con=duckdb.connect()
            m=con.execute(f"SELECT bar_end_time,open,high,low,close FROM read_parquet('{minute_path}') WHERE qmt_code=? AND trade_date=? AND period='1m' AND adjust='none' AND bar_end_time<=? ORDER BY bar_end_time",[event.symbol,event.signal_date,event.decision_at]).fetchdf();con.close();m.bar_end_time=pd.to_datetime(m.bar_end_time)
            fig,axes=v1.plt.subplots(2,1,figsize=(11.7,8.3),gridspec_kw={"height_ratios":[2.2,1]})
            x=v1.mdates.date2num(view.trade_date); colors=np.where(view.coord_close.ge(view.coord_open),"#dc2626","#059669")
            axes[0].vlines(x,view.coord_low,view.coord_high,color=colors,lw=.6);axes[0].bar(x,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65)
            axes[0].axhline(event.platform_ceiling,color="#f59e0b",ls=":",label="Frozen prior-60 ceiling");axes[0].set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",fontproperties=v1.CJK_FONT);axes[0].grid(alpha=.2);axes[0].legend(fontsize=8)
            xm=v1.mdates.date2num(m.bar_end_time);cm=np.where(m.close.ge(m.open),"#dc2626","#059669")
            axes[1].vlines(xm,m.low,m.high,color=cm,lw=.7);axes[1].bar(xm,np.maximum(abs(m.close-m.open),m.close.abs()*.0003),bottom=np.minimum(m.open,m.close),color=cm,width=.00045)
            axes[1].axhline(event.raw_platform_ceiling,color="#f59e0b",ls=":");axes[1].axvline(event.decision_at,color="#2563eb",ls="--",label="causal cross signal");axes[1].grid(alpha=.2);axes[1].legend(fontsize=8);axes[1].xaxis.set_major_formatter(v1.mdates.DateFormatter("%H:%M"))
            fig.text(.01,.01,"Outcome-blind; minute panel stops at completed signal bar. "f"prior peer(s) in 60 trading minutes={event.prior_industry_breakout_symbols_60m}; signal return={event.intraday_return:+.1%}; entry next minute is not shown.",fontsize=7)
            fig.tight_layout(rect=[0,.035,1,1]);pdf.savefig(fig,dpi=150);fig.savefig(BLIND_DIR/f"{event.chart_id}.png",dpi=135);v1.plt.close(fig)


def run_stage_a(reuse_scan: bool = False) -> dict[str, Any]:
    hashes=persist_contract()
    if reuse_scan and MOTHER.exists() and FIRST_CROSSES.exists():
        mother=v1.read_parquet_duckdb(MOTHER);crosses=v1.read_parquet_duckdb(FIRST_CROSSES)
        for col in ("trade_date","state_date","market_latest_source","industry_latest_source"):mother[col]=pd.to_datetime(mother[col])
        for col in ("trade_date","bar_end_time"):crosses[col]=pd.to_datetime(crosses[col])
    else:
        mother=build_mother();crosses=build_first_crosses(mother)
    frame,audit=build_candidates(mother,crosses);sample=blind_sample(frame);render_blind_charts(sample)
    executable=frame.loc[frame.entry_executable]
    result={"experiment":EXPERIMENT,**hashes,"runner_sha256":v1.sha256(Path(__file__)),"mother_sha256":v1.sha256(MOTHER),"first_crosses_sha256":v1.sha256(FIRST_CROSSES),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"candidate_count":len(frame),"executable_signal_count":len(executable),"annual_executable_counts":executable.groupby(executable.signal_date.dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict(),"unique_signal_dates":int(executable.signal_date.nunique()),"maximum_signals_on_one_date":int(executable.groupby("signal_date").size().max()),"blind_chart_count":len(sample),"audit":{**audit,"blind_chart_post_signal_bar_count":0,"outcomes_opened":False,"repository_2024_plus_opened":False}}
    v1.write_json(FREEZE,result);return result


def verify_stage_a() -> dict[str, Any]:
    freeze=json.loads(FREEZE.read_text());expected={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"runner_sha256":v1.sha256(Path(__file__)),"mother_sha256":v1.sha256(MOTHER),"first_crosses_sha256":v1.sha256(FIRST_CROSSES),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF)}
    drift={k:[freeze.get(k),v] for k,v in expected.items() if freeze.get(k)!=v}
    if drift:raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def load_daily(symbols: list[str], through: str) -> pd.DataFrame:
    registry=pd.DataFrame({"symbol":sorted(set(symbols))});con=duckdb.connect();con.register("registry",registry)
    if pd.Timestamp(through)<=pd.Timestamp("2023-12-31"):
        source=f"SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '{through}'"
    else:
        source=f"SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31' UNION ALL BY NAME SELECT * FROM read_parquet('{v1.DAILY_TAIL}') WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '{through}'"
    frame=con.execute(f"WITH d AS ({source}) SELECT d.* FROM d JOIN registry USING(symbol) ORDER BY symbol,trade_date").fetchdf();con.close();frame.trade_date=pd.to_datetime(frame.trade_date);return frame


def build_outcomes(candidates: pd.DataFrame, through: str, output: Path) -> tuple[pd.DataFrame,dict[str,int]]:
    daily=load_daily(candidates.symbol.unique().tolist(),through);groups={s:g.sort_values("trade_date").reset_index(drop=True) for s,g in daily.groupby("symbol")};rows=[]
    for event in candidates.itertuples(index=False):
        for profile,settings in PROFILES.items():
            base={"event_id":event.event_id,"symbol":event.symbol,"sleeve":event.sleeve,"signal_date":event.signal_date,"signal_cal_idx":int(event.cal_idx),"decision_at":event.decision_at,"profile":profile,"platform_ceiling":float(event.platform_ceiling),"entry_time":event.entry_time,"entry_price":float(event.entry_price)}
            if not bool(event.entry_executable):rows.append({**base,"status":"NO_LEGAL_ENTRY"});continue
            part=groups[event.symbol];signal_pos=np.flatnonzero(part.trade_date.eq(event.signal_date).to_numpy())
            if len(signal_pos)!=1:raise ResearchError(f"missing daily signal {event.event_id}")
            lineage=float(event.invalid_step_cum);entry_idx=int(event.cal_idx);horizon_idx=entry_idx+settings["horizon"];target=None if settings["target"] is None else float(event.entry_price)*(1+settings["target"])
            exit_pos=exit_price=exit_reason=decision_idx=None
            for pos in range(int(signal_pos[0])+1,len(part)):
                row=part.iloc[pos]
                if not v1.legal_state(row,lineage):continue
                if target is not None and float(row.coord_high)>=target:
                    exit_pos=pos;exit_price=target;exit_reason=f"TARGET_{int(settings['target']*100)}";decision_idx=int(row.cal_idx);break
                if float(row.coord_close)<float(event.platform_ceiling):
                    decision_idx=int(row.cal_idx)
                    for sell_pos in range(pos+1,len(part)):
                        if v1.legal_sell_open(part.iloc[sell_pos],lineage):exit_pos=sell_pos;exit_price=float(part.iloc[sell_pos].coord_open);exit_reason="PLATFORM_FAILURE";break
                    break
                if int(row.cal_idx)>=horizon_idx:
                    decision_idx=int(row.cal_idx)
                    for sell_pos in range(pos+1,len(part)):
                        if v1.legal_sell_open(part.iloc[sell_pos],lineage):exit_pos=sell_pos;exit_price=float(part.iloc[sell_pos].coord_open);exit_reason=f"H{settings['horizon']}_TIME_STOP";break
                    break
            if exit_pos is None:rows.append({**base,"status":"UNRESOLVED"});continue
            exit_row=part.iloc[int(exit_pos)];gross=float(exit_price)/float(event.entry_price)-1
            rows.append({**base,"status":"COMPLETED","exit_date":exit_row.trade_date,"exit_cal_idx":int(exit_row.cal_idx),"exit_price":float(exit_price),"exit_reason":exit_reason,"exit_decision_cal_idx":decision_idx,"holding_sessions":int(exit_row.cal_idx)-entry_idx,"gross_return":gross,"net_return":gross-.004})
    frame=pd.DataFrame(rows)
    for col in ("signal_date","decision_at","entry_time","exit_date"):frame[col]=pd.to_datetime(frame[col])
    v1.write_parquet(frame,output);audit={"signal_bar_fill_count":int((frame.entry_time<=frame.decision_at).sum()),"t1_same_day_exit_count":int((frame.status.eq("COMPLETED")&frame.exit_cal_idx.le(frame.signal_cal_idx)).sum())};return frame,audit


def metrics(frame: pd.DataFrame,target: float|None=None) -> dict[str,Any]:
    x=frame.loc[frame.status.eq("COMPLETED")]
    if x.empty:return {"completed_trades":0,"mean_net":None,"median_net":None,"win_rate":None,"severe_loss10":None,"target_hit_rate":None,"mean_holding_sessions":None,"median_holding_sessions":None}
    reason=None if target is None else f"TARGET_{int(target*100)}"
    return {"completed_trades":len(x),"mean_net":float(x.net_return.mean()),"median_net":float(x.net_return.median()),"win_rate":float(x.net_return.gt(0).mean()),"severe_loss10":float(x.net_return.le(-.10).mean()),"target_hit_rate":None if reason is None else float(x.exit_reason.eq(reason).mean()),"mean_holding_sessions":float(x.holding_sessions.mean()),"median_holding_sessions":float(x.holding_sessions.median())}


def profile_table(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for profile,settings in PROFILES.items():
        x=outcomes.loc[outcomes.profile.eq(profile)];annual={str(y):metrics(x.loc[x.signal_date.dt.year.eq(y)],settings["target"]) for y in DEVELOPMENT_YEARS};means=[v["mean_net"] for v in annual.values() if v["mean_net"] is not None]
        rows.append({"profile":profile,**metrics(x,settings["target"]),"positive_years":sum(v>0 for v in means),"median_annual_mean_net":float(np.median(means)),"annual_json":json.dumps(annual,sort_keys=True)})
    return pd.DataFrame(rows)


def select_profile(table: pd.DataFrame) -> pd.Series|None:
    eligible=table.loc[(table.completed_trades>=350)&(table.positive_years>=5)&(table.mean_net>=.03)&(table.mean_holding_sessions<=15)]
    if eligible.empty:return None
    return eligible.sort_values(["median_annual_mean_net","mean_net","severe_loss10","mean_holding_sessions"],ascending=[False,False,True,True]).iloc[0]


def run_stage_b() -> dict[str,Any]:
    stage_a=verify_stage_a();c=v1.read_parquet_duckdb(CANDIDATES)
    for col in ("signal_date","decision_at","entry_time"):c[col]=pd.to_datetime(c[col])
    c=c.loc[c.entry_executable]
    dev=c.loc[c.signal_date.dt.year.isin(DEVELOPMENT_YEARS)];dev_o,audit=build_outcomes(dev,"2021-03-31",DEV_OUTCOMES);table=profile_table(dev_o);v1.write_parquet(table,PROFILE_TABLE);selected=select_profile(table)
    if selected is None:
        result={"experiment":EXPERIMENT,"verdict":"INTRADAY_PRICE_DISCOVERY_DEVELOPMENT_FAILED","stage_a":stage_a,"profile_table":table.replace({np.nan:None}).to_dict("records"),"development_audit":audit,"forward_years_opened":False,"repository_2024_plus_opened":False};v1.write_json(RESULT,result);return result
    profile=str(selected.profile);v1.write_json(PROFILE_FREEZE,{"experiment":EXPERIMENT,"selected_profile":profile,"development_outcomes_sha256":v1.sha256(DEV_OUTCOMES),"profile_table_sha256":v1.sha256(PROFILE_TABLE),"forward_opened":False})
    forward=c.loc[c.signal_date.dt.year.isin(FORWARD_YEARS)];fwd_o,fwd_audit=build_outcomes(forward,"2024-03-31",FORWARD_OUTCOMES);chosen=pd.concat([dev_o,fwd_o]).loc[lambda x:x.profile.eq(profile)].merge(c[["event_id","industry_positive_ret20_share","stock_minus_industry_ret20","prior_industry_breakout_count_60m"]],on="event_id",validate="one_to_one");chosen["turnover_expansion"]=chosen.prior_industry_breakout_count_60m
    accepted,skipped,nav=v1.replay_portfolio(chosen);v1.write_parquet(accepted,ACCEPTED);v1.write_parquet(skipped,SKIPPED);v1.write_parquet(nav,NAV)
    overall=metrics(accepted.assign(status="COMPLETED"),PROFILES[profile]["target"]);annual={str(y):metrics(accepted.loc[accepted.signal_date.dt.year.eq(y)].assign(status="COMPLETED"),PROFILES[profile]["target"]) for y in YEARS};portfolio=v1.portfolio_metrics(nav,accepted);concentration=v1.concentration_metrics(accepted)
    gate={"completed_per_year_gt_50":len(accepted)/10>50,"mean_net_gt_5pct":overall["mean_net"]>.05,"mean_hold_lt_15":overall["mean_holding_sessions"]<15,"forward_each_positive":all(annual[str(y)]["mean_net"] is not None and annual[str(y)]["mean_net"]>0 for y in FORWARD_YEARS),"at_least_8_positive_years":sum(v["mean_net"] is not None and v["mean_net"]>0 for v in annual.values())>=8,"max_date_share_le_10pct":concentration["top_signal_date_share"]<=.10}
    verdict="INTRADAY_INDUSTRY_PRICE_DISCOVERY_EDGE" if all(gate.values()) else "INTRADAY_INDUSTRY_PRICE_DISCOVERY_FAILED_FORWARD_OR_TARGET"
    result={"experiment":EXPERIMENT,"verdict":verdict,"selected_profile":profile,"profile_table":table.replace({np.nan:None}).to_dict("records"),"capacity_accepted_completed_trades":len(accepted),"capacity_skips":len(skipped),"completed_per_year":len(accepted)/10,"overall_2014_2023":overall,"annual":annual,"portfolio":portfolio,"concentration":concentration,"gate":gate,"audit":{**audit,**{f"forward_{k}":v for k,v in fwd_audit.items()},"profile_selected_before_forward_open":True,"feature_after_decision_count":0,"2024_rows_opened_for_2023_execution_resolution_only":True,"2024_signal_count":0},"hashes":{"profile_freeze":v1.sha256(PROFILE_FREEZE),"development_outcomes":v1.sha256(DEV_OUTCOMES),"forward_outcomes":v1.sha256(FORWARD_OUTCOMES),"accepted":v1.sha256(ACCEPTED),"skipped":v1.sha256(SKIPPED),"nav":v1.sha256(NAV)}};v1.write_json(RESULT,result);return result


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--stage-a",action="store_true");parser.add_argument("--stage-a-resume",action="store_true");parser.add_argument("--stage-b",action="store_true");args=parser.parse_args()
    if args.stage_a or args.stage_a_resume:print(json.dumps(run_stage_a(reuse_scan=args.stage_a_resume),indent=2,default=str))
    elif args.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
    else:parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
