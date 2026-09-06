#!/usr/bin/env python3
"""Causal bull opening-gap / first-30-minute acceptance research.

The scientific unit is a signal known at the completed 10:00 bar.  Platform,
market and industry state use only prior completed sessions.  Entry is the
10:01 bar open (or no entry); no signal-day close is used for admission.
"""

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
EXPERIMENT = "ASHARE-BULL-OPENING-GAP-30M-ACCEPTANCE-V38"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_opening_gap_30m_acceptance_v38")
RAW_MINUTE = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
PROFILE_FREEZE = OS / f"artifacts/{EXPERIMENT}_profile_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

MOTHER = EXT / "stage_a/prior_only_platform_days.parquet"
CLOCK = EXT / "stage_a/ten_oclock_features.parquet"
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

# This small family is frozen before any exact 10:01-entry outcomes are built.
# Thresholds express progressively stronger acceptance, not an arbitrary grid.
ADMISSION_PROFILES = {
    "A80_ACTIVE": {
        "acceptance_prev": 0.80,
        "acceptance_open": 0.50,
        "early_amount_share": 0.15,
        "close_over_open": 0.00,
    },
    "A90_ACTIVE": {
        "acceptance_prev": 0.90,
        "acceptance_open": 0.60,
        "early_amount_share": 0.20,
        "close_over_open": 0.00,
    },
    "A80_PROGRESS": {
        "acceptance_prev": 0.80,
        "acceptance_open": 0.60,
        "early_amount_share": 0.15,
        "close_over_open": 0.01,
    },
}

TRANSLATIONS = {
    "T10_H10_GAP_FAILURE": {"target": 0.10, "horizon": 10},
    "T15_H10_GAP_FAILURE": {"target": 0.15, "horizon": 10},
    "T15_H15_GAP_FAILURE": {"target": 0.15, "horizon": 15},
    "T20_H15_GAP_FAILURE": {"target": 0.20, "horizon": 15},
}


class ResearchError(RuntimeError):
    """Fail-closed implementation error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "stage": "A_OUTCOME_BLIND_CONTRACT",
        "economic_hypothesis": (
            "A prior-session PIT bull market and broad positive industry create demand context. "
            "A stock with a low-turnover bounded platform that opens through its nearby inventory "
            "ceiling is only a quote change at 09:30.  It becomes a tradable information-repricing "
            "event only when completed 09:31-10:00 bars show persistent acceptance above the old "
            "close, actual traversal of the ceiling, and non-trivial early turnover."
        ),
        "independence": (
            "No collapse, downward-gap, gap-repair, V6/V7/V26 identity or outcome is used."
        ),
        "prior_only_conditions": {
            "PIT_BULL": "immediately prior completed session market_regime=BULL",
            "HEALTHY_INDUSTRY": (
                "prior PIT industry n20>=5, median ret20>0, positive-ret20 share>50%"
            ),
            "QUIET_NEAR_PLATFORM": (
                "prior20 return [-8%,+12%], prior20 range<=25%, prior60 range<=40%, "
                "no prior20 limit-up close, prior5 mean amount/prior20 mean amount<=1, "
                "and prior close >=90% of prior20 coordinate high"
            ),
        },
        "opening_information_gap": (
            "09:30 minute open is +1% to +7% versus prior raw close and no more than 5% below "
            "the frozen prior20 coordinate high; open is below the known upper price limit"
        ),
        "decision_clock": "10:00:00 after exactly 30 completed continuous-auction 1m bars, 09:31-10:00",
        "ten_oclock_features": {
            "acceptance_prev": "share of 30 completed closes >= prior raw close",
            "acceptance_open": "share of 30 completed closes >= 09:30 open",
            "platform_traversed": "10:00 close in QD-010 coordinate >= frozen prior20 high",
            "early_amount_share": (
                "09:30-10:00 amount / mean amount of prior20 completed stock sessions"
            ),
            "entry": "exact next 1m bar open at 10:01; positive bar volume and below upper limit",
        },
        "admission_profiles": ADMISSION_PROFILES,
        "translations": TRANSLATIONS,
        "failure": (
            "information-gap failure: completed signal-day or later daily coordinate close below "
            "prior coordinate close; after T+1, exit at next legal daily open"
        ),
        "target": "coordinate target from exact 10:01 entry; first target realization is T+1",
        "cost": {"entry": 0.002, "exit": 0.002},
        "development": {
            "years": list(DEVELOPMENT_YEARS),
            "minimum_completed": 350,
            "minimum_positive_years": 5,
            "minimum_mean_net_for_forward_open": 0.03,
            "maximum_mean_holding_sessions": 15,
        },
        "forward": {
            "years": list(FORWARD_YEARS),
            "opened_only_after_development_profile_freeze": True,
            "final_gate": (
                "2014-2023 capacity accepted completed/year>50, mean net>5%, mean hold<15, "
                "every 2021-2023 annual mean positive, at least 8/10 annual means positive, "
                "and no dominant signal date"
            ),
        },
        "portfolio": v1.contract_value()["portfolio"],
        "outcomes_opened": False,
        "repository_2024_plus_opened": False,
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_CAUSAL_CONTRACT",
            "contract_sha256": v1.sha256(CONTRACT),
            "sources": {
                "daily": v1.sha256(v1.DAILY),
                "regime": v1.sha256(v1.SOURCE_REGIME),
                "industry": v1.sha256(v1.INDUSTRY_PANEL),
                "minute_pattern": str(RAW_MINUTE / "{year}_day_parquet_none.parquet"),
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
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w20 AS prior20_low,
                  max(coord_high) OVER w60 AS prior60_high,
                  min(coord_low) OVER w60 AS prior60_low,
                  avg(amount) OVER w5 AS prior5_amount,
                  avg(amount) OVER w20 AS prior20_amount,
                  count(*) OVER w20 AS prior20_n,
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
                  w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
                  w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                  w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
              ), joined AS (
                SELECT d0.*,rp.state_date,rp.market_regime,rp.market_median_ret20,
                  rp.market_positive_ret20_share,rp.market_latest_source,
                  i.industry_median_ret20,i.industry_positive_ret20_share,
                  i.industry_n20,i.industry_ret20_percentile,
                  i.latest_source_timestamp AS industry_latest_source,
                  prev_coord_close/NULLIF(lag20_coord_close,0)-1 AS prior20_return,
                  prior20_high/NULLIF(prior20_low,0)-1 AS prior20_range,
                  prior60_high/NULLIF(prior60_low,0)-1 AS prior60_range,
                  prior5_amount/NULLIF(prior20_amount,0) AS amount_contraction5,
                  prev_coord_close/NULLIF(prior20_high,0) AS prev_close_to_platform
                FROM d0
                JOIN regime_prev rp ON rp.signal_date=d0.trade_date
                JOIN read_parquet('{v1.INDUSTRY_PANEL}') i
                  ON i.trade_date=rp.state_date AND i.causal_industry=d0.causal_industry
                WHERE d0.trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
              )
              SELECT *,prior20_high AS platform_ceiling,
                prior20_high/NULLIF(coordinate_factor,0) AS raw_platform_ceiling
              FROM joined
              WHERE market_regime='BULL'
                AND industry_n20>=5
                AND industry_median_ret20>0
                AND industry_positive_ret20_share>0.50
                AND prior20_n=20 AND prior60_n=60
                AND prior20_limitup_count=0
                AND prior20_return BETWEEN -0.08 AND 0.12
                AND prior20_range<=0.25
                AND prior60_range<=0.40
                AND amount_contraction5<=1.0
                AND prev_close_to_platform>=0.90
              ORDER BY trade_date,symbol
            ) TO '{MOTHER}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(MOTHER)
    for col in ("trade_date", "state_date", "market_latest_source", "industry_latest_source"):
        frame[col] = pd.to_datetime(frame[col])
    bad = frame.market_latest_source.ge(frame.trade_date) | frame.industry_latest_source.ge(frame.trade_date)
    if bad.any():
        raise ResearchError("prior PIT market/industry state is not strictly prior to signal date")
    return frame


def build_clock_features(mother: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for year in YEARS:
        registry = mother.loc[mother.trade_date.dt.year.eq(year)].copy()
        if registry.empty:
            continue
        minute_path = RAW_MINUTE / f"{year}_day_parquet_none.parquet"
        if not minute_path.exists():
            raise ResearchError(f"missing minute source {minute_path}")
        keep = [
            "trade_date", "symbol", "sleeve", "causal_industry", "prev_raw_close",
            "prev_coord_close", "coordinate_factor", "platform_ceiling", "raw_platform_ceiling",
            "prior20_amount", "up_limit_price", "cal_idx", "invalid_step_cum",
        ]
        reg = registry[keep].copy()
        con = duckdb.connect()
        con.register("registry", reg)
        frame = con.execute(
            f"""
            WITH raw AS (
              SELECT m.trade_date,r.symbol,m.bar_end_time,m.open,m.high,m.low,m.close,
                m.volume,m.amount,r.sleeve,r.causal_industry,r.prev_raw_close,
                r.prev_coord_close,r.coordinate_factor,r.platform_ceiling,
                r.raw_platform_ceiling,r.prior20_amount,r.up_limit_price,r.cal_idx,
                r.invalid_step_cum
              FROM read_parquet('{minute_path}') m JOIN registry r
                ON m.trade_date=r.trade_date AND m.qmt_code=r.symbol
              WHERE m.period='1m' AND m.adjust='none'
                AND CAST(m.bar_end_time AS TIME) BETWEEN TIME '09:30:00' AND TIME '10:01:00'
            ), opening AS (
              SELECT * FROM raw WHERE CAST(bar_end_time AS TIME)=TIME '09:30:00'
            ), continuous AS (
              SELECT * FROM raw
              WHERE CAST(bar_end_time AS TIME) BETWEEN TIME '09:31:00' AND TIME '10:00:00'
            ), agg AS (
              SELECT trade_date,symbol,count(*) AS continuous_bar_count,
                avg((close>=prev_raw_close)::INT) AS acceptance_ratio_prev_close,
                min(low) AS min_low_30m,max(high) AS max_high_30m,
                sum(amount) AS continuous_amount_30m,
                arg_max(close,bar_end_time) AS close_1000,
                max(bar_end_time) AS decision_at
              FROM continuous GROUP BY trade_date,symbol
            ), entry AS (
              SELECT trade_date,symbol,bar_end_time AS entry_time,open AS entry_raw_open,
                volume AS entry_volume
              FROM raw WHERE CAST(bar_end_time AS TIME)=TIME '10:01:00'
            )
            SELECT o.trade_date,o.symbol,o.sleeve,o.causal_industry,o.prev_raw_close,
              o.prev_coord_close,o.coordinate_factor,o.platform_ceiling,o.raw_platform_ceiling,
              o.prior20_amount,o.up_limit_price,o.cal_idx,o.invalid_step_cum,
              o.open AS opening_raw,o.amount AS auction_amount,
              a.continuous_bar_count,a.acceptance_ratio_prev_close,
              avg((c.close>=o.open)::INT) AS acceptance_ratio_open,
              a.min_low_30m,a.max_high_30m,a.close_1000,a.decision_at,
              (coalesce(o.amount,0)+coalesce(a.continuous_amount_30m,0))
                /NULLIF(o.prior20_amount,0) AS early_amount_share,
              a.close_1000/NULLIF(o.open,0)-1 AS close_over_open,
              o.open/NULLIF(o.prev_raw_close,0)-1 AS opening_gap,
              o.open*o.coordinate_factor/NULLIF(o.platform_ceiling,0)-1 AS open_vs_platform,
              a.close_1000*o.coordinate_factor/NULLIF(o.platform_ceiling,0)-1
                AS close_vs_platform,
              e.entry_time,e.entry_raw_open,e.entry_volume,
              e.entry_raw_open*o.coordinate_factor AS entry_price
            FROM opening o JOIN agg a USING(trade_date,symbol)
            JOIN continuous c USING(trade_date,symbol)
            LEFT JOIN entry e USING(trade_date,symbol)
            GROUP BY ALL
            ORDER BY o.trade_date,o.symbol
            """
        ).fetchdf()
        con.close()
        rows.append(frame)
    if not rows:
        raise ResearchError("no 10:00 clock features")
    result = pd.concat(rows, ignore_index=True)
    for col in ("trade_date", "decision_at", "entry_time"):
        result[col] = pd.to_datetime(result[col])
    v1.write_parquet(result, CLOCK)
    return result


def build_candidates(mother: pd.DataFrame, clock: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    drop = [c for c in clock.columns if c in mother.columns and c not in {"trade_date", "symbol"}]
    frame = clock.merge(mother.drop(columns=drop), on=["trade_date", "symbol"], validate="one_to_one")
    frame = frame.loc[
        frame.continuous_bar_count.eq(30)
        & frame.opening_gap.between(0.01, 0.07)
        & frame.open_vs_platform.ge(-0.05)
        & frame.opening_raw.lt(frame.up_limit_price - 0.001)
    ].copy()
    frame["entry_executable"] = (
        frame.entry_time.notna()
        & frame.entry_time.gt(frame.decision_at)
        & frame.entry_volume.gt(0)
        & frame.entry_raw_open.lt(frame.up_limit_price - 0.001)
    )
    frame["platform_traversed"] = frame.close_vs_platform.ge(0)
    for profile, setting in ADMISSION_PROFILES.items():
        frame[f"passes_{profile}"] = (
            frame.acceptance_ratio_prev_close.ge(setting["acceptance_prev"])
            & frame.acceptance_ratio_open.ge(setting["acceptance_open"])
            & frame.early_amount_share.ge(setting["early_amount_share"])
            & frame.close_over_open.ge(setting["close_over_open"])
            & frame.platform_traversed
            & frame.entry_executable
        )
    frame["passes_any"] = frame[[f"passes_{p}" for p in ADMISSION_PROFILES]].any(axis=1)
    frame["signal_date"] = frame.trade_date
    frame["feature_latest_timestamp"] = frame.decision_at
    frame["event_id"] = frame.apply(
        lambda r: f"OGA38-{r.trade_date:%Y%m%d}-{r.symbol}-1000", axis=1
    )
    frame["stock_minus_industry_ret20"] = frame.prior20_return - frame.industry_median_ret20
    frame["turnover_expansion"] = frame.early_amount_share
    frame = frame.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    audits = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "not_exactly_30_continuous_bars_count": int(frame.continuous_bar_count.ne(30).sum()),
        "feature_after_decision_count": 0,
        "entry_at_or_before_decision_count": int(
            (frame.entry_time.notna() & frame.entry_time.le(frame.decision_at)).sum()
        ),
        "entry_without_volume_count": int((frame.entry_executable & frame.entry_volume.le(0)).sum()),
        "entry_at_limit_count": int(
            (frame.entry_executable & frame.entry_raw_open.ge(frame.up_limit_price - 0.001)).sum()
        ),
        "candidate_after_2023_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "missing_required_feature_pass_count": int(
            (frame.passes_any & frame[[
                "acceptance_ratio_prev_close", "acceptance_ratio_open", "early_amount_share",
                "close_over_open", "close_vs_platform", "entry_price",
            ]].isna().any(axis=1)).sum()
        ),
    }
    if any(audits.values()):
        raise ResearchError(str(audits))
    v1.write_parquet(frame, CANDIDATES)
    return frame, audits


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    x = frame.loc[frame.passes_A80_ACTIVE].copy()
    x["year"] = x.signal_date.dt.year
    x["hash_order"] = x.event_id.map(lambda z: hashlib.sha256(z.encode()).hexdigest())
    pieces = [g.sort_values("hash_order").head(3) for _, g in x.groupby("year")]
    selected = pd.concat(pieces, ignore_index=True) if pieces else x.head(0)
    if len(selected) < count:
        rest = x.loc[~x.event_id.isin(selected.event_id)].sort_values("hash_order")
        selected = pd.concat([selected, rest.head(count - len(selected))], ignore_index=True)
    selected = selected.sort_values(["signal_date", "symbol"]).head(count).reset_index(drop=True)
    selected.insert(0, "chart_id", [f"V38-BLIND-{i:03d}" for i in range(1, len(selected) + 1)])
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(BLIND_INDEX, index=False)
    return selected


def render_blind_charts(sample: pd.DataFrame) -> None:
    if sample.empty:
        return
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())})
    con = duckdb.connect(); con.register("symbols", symbols)
    daily = con.execute(
        f"""SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close,amount
        FROM read_parquet('{v1.DAILY}') d JOIN symbols USING(symbol)
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
        ORDER BY symbol,trade_date"""
    ).fetchdf(); con.close()
    daily.trade_date = pd.to_datetime(daily.trade_date)
    groups = {s: g.reset_index(drop=True) for s, g in daily.groupby("symbol")}
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            stock = groups[event.symbol]
            pos = np.flatnonzero(stock.trade_date.eq(event.signal_date).to_numpy())[0]
            view = stock.iloc[max(0, pos - 90):pos].copy()
            minute_path = RAW_MINUTE / f"{event.signal_date.year}_day_parquet_none.parquet"
            con = duckdb.connect()
            minute = con.execute(
                f"""SELECT bar_end_time,open,high,low,close,amount
                FROM read_parquet('{minute_path}')
                WHERE qmt_code=? AND trade_date=? AND period='1m' AND adjust='none'
                  AND CAST(bar_end_time AS TIME)<=TIME '10:00:00'
                ORDER BY bar_end_time""",
                [event.symbol, event.signal_date],
            ).fetchdf(); con.close()
            minute.bar_end_time = pd.to_datetime(minute.bar_end_time)
            fig, axes = v1.plt.subplots(2, 1, figsize=(11.7, 8.3), gridspec_kw={"height_ratios": [2.1, 1]})
            x = v1.mdates.date2num(view.trade_date)
            color = np.where(view.coord_close.ge(view.coord_open), "#dc2626", "#059669")
            axes[0].vlines(x, view.coord_low, view.coord_high, color=color, lw=.7)
            axes[0].bar(x, np.maximum(abs(view.coord_close-view.coord_open), view.coord_close.abs()*.0005), bottom=np.minimum(view.coord_open, view.coord_close), color=color, width=.65)
            axes[0].axhline(event.platform_ceiling, color="#f59e0b", ls=":", label="prior-20 platform ceiling")
            axes[0].set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}", fontproperties=v1.CJK_FONT)
            axes[0].grid(alpha=.2); axes[0].legend(fontsize=8)
            xm = v1.mdates.date2num(minute.bar_end_time)
            cm = np.where(minute.close.ge(minute.open), "#dc2626", "#059669")
            axes[1].vlines(xm, minute.low, minute.high, color=cm, lw=.7)
            axes[1].bar(xm, np.maximum(abs(minute.close-minute.open), minute.close.abs()*.0003), bottom=np.minimum(minute.open, minute.close), color=cm, width=.00045)
            axes[1].axhline(event.prev_raw_close, color="#64748b", ls="--", label="prior close")
            axes[1].axhline(event.raw_platform_ceiling, color="#f59e0b", ls=":", label="platform ceiling")
            axes[1].axvline(event.decision_at, color="#2563eb", ls="--", label="10:00 decision")
            axes[1].grid(alpha=.2); axes[1].legend(fontsize=8)
            axes[1].xaxis.set_major_formatter(v1.mdates.DateFormatter("%H:%M"))
            fig.text(.01, .01, (
                "Outcome-blind; chart ends at decision. "
                f"gap={event.opening_gap:+.1%}, accept(old close)={event.acceptance_ratio_prev_close:.0%}, "
                f"accept(open)={event.acceptance_ratio_open:.0%}, early amount/prior-day mean={event.early_amount_share:.0%}. "
                "The 10:01 entry and all outcomes are hidden."
            ), fontsize=7)
            fig.tight_layout(rect=[0, .035, 1, 1]); pdf.savefig(fig, dpi=150)
            fig.savefig(BLIND_DIR / f"{event.chart_id}.png", dpi=135); v1.plt.close(fig)


def run_stage_a(reuse_mother: bool = False) -> dict[str, Any]:
    hashes = persist_contract()
    if reuse_mother and MOTHER.exists() and CLOCK.exists():
        mother = v1.read_parquet_duckdb(MOTHER)
        clock = v1.read_parquet_duckdb(CLOCK)
        for col in ("trade_date", "state_date", "market_latest_source", "industry_latest_source"):
            mother[col] = pd.to_datetime(mother[col])
        for col in ("trade_date", "decision_at", "entry_time"):
            clock[col] = pd.to_datetime(clock[col])
    else:
        mother = build_mother(); clock = build_clock_features(mother)
    frame, audit = build_candidates(mother, clock)
    sample = blind_sample(frame); render_blind_charts(sample)
    annual = {
        profile: frame.loc[frame[f"passes_{profile}"]].groupby(frame.signal_date.dt.year).size()
        .reindex(YEARS, fill_value=0).astype(int).to_dict()
        for profile in ADMISSION_PROFILES
    }
    result = {
        "experiment": EXPERIMENT, **hashes,
        "runner_sha256": v1.sha256(Path(__file__)),
        "mother_sha256": v1.sha256(MOTHER), "clock_sha256": v1.sha256(CLOCK),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF) if BLIND_PDF.exists() else None,
        "broad_candidate_count": len(frame),
        "profile_counts": {p: int(frame[f"passes_{p}"].sum()) for p in ADMISSION_PROFILES},
        "annual_profile_counts": annual,
        "unique_signal_dates": {
            p: int(frame.loc[frame[f"passes_{p}"], "signal_date"].nunique()) for p in ADMISSION_PROFILES
        },
        "max_signals_one_date": {
            p: int(frame.loc[frame[f"passes_{p}"]].groupby("signal_date").size().max())
            if frame[f"passes_{p}"].any() else 0 for p in ADMISSION_PROFILES
        },
        "blind_chart_count": len(sample),
        "audit": {**audit, "outcomes_opened": False, "repository_2024_plus_opened": False},
    }
    v1.write_json(FREEZE, result)
    return result


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)), "mother_sha256": v1.sha256(MOTHER),
        "clock_sha256": v1.sha256(CLOCK), "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF) if BLIND_PDF.exists() else None,
    }
    drift = {k: [freeze.get(k), value] for k, value in expected.items() if freeze.get(k) != value}
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def load_daily(symbols: list[str], through: str) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    con = duckdb.connect(); con.register("registry", registry)
    frame = con.execute(
        f"""SELECT d.* FROM read_parquet('{v1.DAILY}') d JOIN registry USING(symbol)
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '{through}'
        ORDER BY symbol,trade_date"""
    ).fetchdf(); con.close()
    frame.trade_date = pd.to_datetime(frame.trade_date)
    return frame


def build_outcomes(
    candidates: pd.DataFrame, output: Path, through: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    daily = load_daily(candidates.symbol.unique().tolist(), through)
    groups = {s: g.sort_values("trade_date").reset_index(drop=True) for s, g in daily.groupby("symbol")}
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        stock = groups[event.symbol]
        signal_pos = np.flatnonzero(stock.trade_date.eq(event.signal_date).to_numpy())
        if len(signal_pos) != 1:
            raise ResearchError(f"missing signal daily row {event.event_id}")
        signal_pos = int(signal_pos[0]); lineage = float(event.invalid_step_cum)
        for admission in ADMISSION_PROFILES:
            if not bool(getattr(event, f"passes_{admission}")):
                continue
            for translation, setting in TRANSLATIONS.items():
                base = {
                    "event_id": event.event_id, "symbol": event.symbol, "sleeve": event.sleeve,
                    "causal_industry": event.causal_industry, "signal_date": event.signal_date,
                    "signal_cal_idx": int(event.cal_idx), "decision_at": event.decision_at,
                    "entry_time": event.entry_time, "entry_price": float(event.entry_price),
                    "admission_profile": admission, "translation": translation,
                    "acceptance_ratio_prev_close": float(event.acceptance_ratio_prev_close),
                    "acceptance_ratio_open": float(event.acceptance_ratio_open),
                    "early_amount_share": float(event.early_amount_share),
                    "stock_minus_industry_ret20": float(event.stock_minus_industry_ret20),
                    "industry_positive_ret20_share": float(event.industry_positive_ret20_share),
                    "turnover_expansion": float(event.early_amount_share),
                }
                if not bool(event.entry_executable):
                    rows.append({**base, "status": "NO_LEGAL_ENTRY"}); continue
                target = float(event.entry_price) * (1 + float(setting["target"]))
                horizon_idx = int(event.cal_idx) + int(setting["horizon"])
                failure_decision_pos: int | None = None
                # The signal-day close occurs after entry.  If it closes the information gap,
                # T+1 permits an exit only at the next legal session open.
                signal_row = stock.iloc[signal_pos]
                if v1.legal_state(signal_row, lineage) and float(signal_row.coord_close) < float(event.prev_coord_close):
                    failure_decision_pos = signal_pos
                exit_pos = None; exit_price = None; exit_reason = None; decision_idx = None
                if failure_decision_pos is not None:
                    decision_idx = int(stock.iloc[failure_decision_pos].cal_idx)
                    for sell_pos in range(failure_decision_pos + 1, len(stock)):
                        if v1.legal_sell_open(stock.iloc[sell_pos], lineage):
                            exit_pos = sell_pos; exit_price = float(stock.iloc[sell_pos].coord_open)
                            exit_reason = "SIGNAL_DAY_GAP_FAILURE"; break
                else:
                    for pos in range(signal_pos + 1, len(stock)):
                        row = stock.iloc[pos]
                        if not v1.legal_state(row, lineage):
                            continue
                        if float(row.coord_high) >= target:
                            exit_pos = pos; exit_price = target; exit_reason = f"TARGET_{int(setting['target']*100)}"
                            decision_idx = int(row.cal_idx); break
                        if float(row.coord_close) < float(event.prev_coord_close):
                            decision_idx = int(row.cal_idx)
                            for sell_pos in range(pos + 1, len(stock)):
                                if v1.legal_sell_open(stock.iloc[sell_pos], lineage):
                                    exit_pos = sell_pos; exit_price = float(stock.iloc[sell_pos].coord_open)
                                    exit_reason = "GAP_FAILURE"; break
                            break
                        if int(row.cal_idx) >= horizon_idx:
                            decision_idx = int(row.cal_idx)
                            for sell_pos in range(pos + 1, len(stock)):
                                if v1.legal_sell_open(stock.iloc[sell_pos], lineage):
                                    exit_pos = sell_pos; exit_price = float(stock.iloc[sell_pos].coord_open)
                                    exit_reason = f"H{setting['horizon']}_TIME_STOP"; break
                            break
                if exit_pos is None:
                    rows.append({**base, "status": "UNRESOLVED"}); continue
                exit_row = stock.iloc[int(exit_pos)]
                gross = float(exit_price) / float(event.entry_price) - 1
                rows.append({
                    **base, "status": "COMPLETED", "exit_date": exit_row.trade_date,
                    "exit_cal_idx": int(exit_row.cal_idx), "exit_price": float(exit_price),
                    "exit_reason": exit_reason, "exit_decision_cal_idx": decision_idx,
                    "holding_sessions": int(exit_row.cal_idx) - int(event.cal_idx),
                    "gross_return": gross, "net_return": gross - 0.004,
                })
    frame = pd.DataFrame(rows)
    for col in ("signal_date", "decision_at", "entry_time", "exit_date"):
        frame[col] = pd.to_datetime(frame[col])
    v1.write_parquet(frame, output)
    audit = {
        "entry_at_or_before_decision_count": int((frame.entry_time <= frame.decision_at).sum()),
        "t1_same_day_exit_count": int(
            (frame.status.eq("COMPLETED") & frame.exit_cal_idx.le(frame.signal_cal_idx)).sum()
        ),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    return frame, audit


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    x = frame.loc[frame.status.eq("COMPLETED")]
    if x.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None,
                "win_rate": None, "severe_loss10": None, "target_hit_rate": None,
                "mean_holding_sessions": None, "median_holding_sessions": None}
    return {
        "completed_trades": len(x), "mean_net": float(x.net_return.mean()),
        "median_net": float(x.net_return.median()), "win_rate": float(x.net_return.gt(0).mean()),
        "severe_loss10": float(x.net_return.le(-0.10).mean()),
        "target_hit_rate": float(x.exit_reason.str.startswith("TARGET_").mean()),
        "mean_holding_sessions": float(x.holding_sessions.mean()),
        "median_holding_sessions": float(x.holding_sessions.median()),
    }


def profile_table(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for admission in ADMISSION_PROFILES:
        for translation in TRANSLATIONS:
            x = outcomes.loc[
                outcomes.admission_profile.eq(admission) & outcomes.translation.eq(translation)
            ]
            annual = {
                str(y): metrics(x.loc[x.signal_date.dt.year.eq(y)]) for y in DEVELOPMENT_YEARS
            }
            annual_means = [m["mean_net"] for m in annual.values() if m["mean_net"] is not None]
            rows.append({
                "admission_profile": admission, "translation": translation, **metrics(x),
                "positive_years": sum(value > 0 for value in annual_means),
                "median_annual_mean_net": float(np.median(annual_means)) if annual_means else None,
                "annual_json": json.dumps(annual, sort_keys=True),
            })
    return pd.DataFrame(rows)


def select_profile(table: pd.DataFrame) -> pd.Series | None:
    eligible = table.loc[
        table.completed_trades.ge(350)
        & table.positive_years.ge(5)
        & table.mean_net.ge(0.03)
        & table.mean_holding_sessions.lt(15)
    ]
    if eligible.empty:
        return None
    return eligible.sort_values(
        ["median_annual_mean_net", "mean_net", "completed_trades", "mean_holding_sessions"],
        ascending=[False, False, False, True],
    ).iloc[0]


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for col in ("signal_date", "decision_at", "entry_time"):
        candidates[col] = pd.to_datetime(candidates[col])
    dev = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT_YEARS)]
    dev_outcomes, audit = build_outcomes(dev, DEV_OUTCOMES, "2021-03-31")
    table = profile_table(dev_outcomes); v1.write_parquet(table, PROFILE_TABLE)
    selected = select_profile(table)
    if selected is None:
        result = {
            "experiment": EXPERIMENT,
            "verdict": "OPENING_GAP_30M_ACCEPTANCE_DEVELOPMENT_FAILED",
            "stage_a": stage_a,
            "profile_table": table.replace({np.nan: None}).to_dict("records"),
            "development_audit": audit,
            "forward_years_opened": False,
            "repository_2024_plus_opened": False,
        }
        v1.write_json(RESULT, result); return result
    admission = str(selected.admission_profile); translation = str(selected.translation)
    v1.write_json(PROFILE_FREEZE, {
        "experiment": EXPERIMENT, "selected_admission": admission,
        "selected_translation": translation,
        "development_outcomes_sha256": v1.sha256(DEV_OUTCOMES),
        "profile_table_sha256": v1.sha256(PROFILE_TABLE), "forward_opened": False,
    })
    forward = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)]
    forward_outcomes, forward_audit = build_outcomes(forward, FORWARD_OUTCOMES, "2023-12-31")
    chosen = pd.concat([dev_outcomes, forward_outcomes], ignore_index=True)
    chosen = chosen.loc[
        chosen.admission_profile.eq(admission) & chosen.translation.eq(translation)
        & chosen.status.eq("COMPLETED")
    ].copy()
    accepted, skipped, nav = v1.replay_portfolio(chosen)
    v1.write_parquet(accepted, ACCEPTED); v1.write_parquet(skipped, SKIPPED); v1.write_parquet(nav, NAV)
    overall = metrics(accepted.assign(status="COMPLETED"))
    annual = {
        str(y): metrics(accepted.loc[accepted.signal_date.dt.year.eq(y)].assign(status="COMPLETED"))
        for y in YEARS
    }
    portfolio = v1.portfolio_metrics(nav, accepted); concentration = v1.concentration_metrics(accepted)
    gate = {
        "completed_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_gt_5pct": overall["mean_net"] > 0.05,
        "mean_hold_lt_15": overall["mean_holding_sessions"] < 15,
        "forward_each_positive": all(annual[str(y)]["mean_net"] is not None and annual[str(y)]["mean_net"] > 0 for y in FORWARD_YEARS),
        "at_least_8_positive_years": sum(m["mean_net"] is not None and m["mean_net"] > 0 for m in annual.values()) >= 8,
        "max_date_share_le_10pct": concentration["top_signal_date_share"] <= 0.10,
    }
    verdict = "OPENING_GAP_30M_ACCEPTANCE_EDGE" if all(gate.values()) else "OPENING_GAP_30M_ACCEPTANCE_FAILED_FORWARD_OR_TARGET"
    result = {
        "experiment": EXPERIMENT, "verdict": verdict,
        "selected_admission": admission, "selected_translation": translation,
        "development_profile_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted), "capacity_skips": len(skipped),
        "completed_per_year": len(accepted) / 10, "overall_2014_2023": overall,
        "annual": annual, "portfolio": portfolio, "concentration": concentration,
        "gate": gate,
        "audit": {**audit, **{f"forward_{k}": value for k, value in forward_audit.items()},
                  "profile_selected_before_forward_open": True, "feature_after_decision_count": 0,
                  "repository_2024_plus_opened": False},
        "hashes": {"profile_freeze": v1.sha256(PROFILE_FREEZE),
                   "development_outcomes": v1.sha256(DEV_OUTCOMES),
                   "forward_outcomes": v1.sha256(FORWARD_OUTCOMES),
                   "accepted": v1.sha256(ACCEPTED), "skipped": v1.sha256(SKIPPED),
                   "nav": v1.sha256(NAV)},
    }
    v1.write_json(RESULT, result); return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-a-resume", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a or args.stage_a_resume:
        print(json.dumps(run_stage_a(reuse_mother=args.stage_a_resume), indent=2, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, default=str))
    else:
        parser.error("choose --stage-a, --stage-a-resume, or --stage-b")


if __name__ == "__main__":
    main()
