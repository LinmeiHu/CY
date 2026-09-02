#!/usr/bin/env python3
# ruff: noqa: E402, E501
"""Frozen Development-only walk-forward for collapse-gap-zone trading translations."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_outcome_discovery_v1 as outcome,
)

v1 = outcome.v1
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-STRATEGY-DEVELOPMENT-V1"
START_HEAD = "185240baeea518d3330ed34555ecd69f9ca0c48f"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "e0846c4464f82b65dc7cad99a13bcfdf3666001338225727b9544220f74bfcd8"
EXPECTED_INPUTS = {
    outcome.v3.SPEC: "6b8c946efa5d1cd8f99103180859d43fabff28583d73a794632b9faeb4c18b16",
    outcome.v3.CANDIDATES: "5920df21aec93aa5c16b63f3ed03b7e32bd76d38c8860052ebabcb3df4b05fa3",
    outcome.SPEC: "e3da3093faf50da92544abf338ac1d1cae3aadd7e42672f998bd8facd7bf2f7c",
    outcome.EVENTS: "b27c2366fdef62e9592bb1c1ebec6a2f1e7c66d7b27312394dd17b65f74e8610",
    outcome.RESULT: "721f39ffa8e7bebeef7b6c0751c664769a6b12e42d3eadfde334a223880f61d4",
}
YEARS = tuple(range(2014, 2022))
FOLDS = (
    (2014, 2016, 2017),
    (2014, 2017, 2018),
    (2014, 2018, 2019),
    (2014, 2019, 2020),
    (2014, 2020, 2021),
)
ENTRIES = ("E1_FIRST_ACCEPT", "E2_QUARTER_ACCEPT", "E3_HALF_ACCEPT", "E4_SECOND_RECLAIM")
TARGETS = ("P75", "FULL")
FAILURES = ("F1_DAILY_LOSS_OF_ZONE", "F2_NO_FAILURE_STOP")
STOPS = (5, 10, 20)
COST = 0.002
K = 20

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_strategy_development_v1")
QD010_DISTRIBUTIONS = Path(
    "/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5/normalized/distributions.parquet"
)
QD010_RIGHTS = Path(
    "/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5/normalized/rights_issues.parquet"
)
QD010_HASHES = {
    QD010_DISTRIBUTIONS: "5982b7dd75ec53deb9ce3874aaf3e4a5168a731b5bbd6d8c2d89258fe4aff387",
    QD010_RIGHTS: "07e864ac6da1d59b69c1b9ce1bcdd01d96d913d0909a718d79627939f8ab87cb",
}
SOURCE = EXTERNAL / "source_events.parquet"
DAILY = EXTERNAL / "source_daily_2014_2021.parquet"
ACTION_EVENTS = EXTERNAL / "qd010_action_events_2014_2021.parquet"
CONFIRMATIONS = EXTERNAL / "confirmations.parquet"
EXEC_ENTRIES = EXTERNAL / "executable_entries.parquet"
LEGAL_OPENS = EXTERNAL / "legal_opens.parquet"
PATH_BOUNDS = EXTERNAL / "minute_path_bounds.parquet"
MINUTE_PATH = EXTERNAL / "minute_paths_to_20_sessions.parquet"
TRADE_CANDIDATES = EXTERNAL / "trade_candidates_qd010_contract_v2.parquet"
SEARCH = OS_ROOT / f"artifacts/{EXPERIMENT}_search.parquet"
MAIN_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_main_selections.json"
CHINEXT_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_selections.json"
MAIN_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_nav.parquet"
CHINEXT_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class StrategyError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution violations."""


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{v1.raw_path(year)}') WHERE period='1m' AND adjust='none'"
        for year in YEARS
    )


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    v1.atomic_text(
        path, json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )


def validate_inputs() -> dict[str, str]:
    expected = {SPEC: EXPECTED_SPEC_SHA256, **EXPECTED_INPUTS, **QD010_HASHES}
    found: dict[str, str] = {}
    for path, digest in expected.items():
        if not path.is_file():
            raise StrategyError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != digest:
            raise StrategyError(f"frozen input mismatch: {path}: {actual}")
        found[str(path)] = actual
    if not v1.DAILY_COMPACT.is_file():
        raise StrategyError("missing authoritative PIT daily state")
    return found


def prepare_sources() -> None:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    if not SOURCE.is_file():
        source = pd.read_parquet(outcome.SOURCE_EVENTS).sort_values("event_id", kind="mergesort")
        if len(source) != 617 or source.event_id.duplicated().any():
            raise StrategyError("source population identity failure")
        v1.write_parquet(source, SOURCE)
    if not DAILY.is_file():
        con = v1.connection()
        query = f"""
        SELECT d.* FROM read_parquet('{v1.DAILY_COMPACT}') d
        JOIN (SELECT DISTINCT symbol FROM read_parquet('{SOURCE}')) s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
        ORDER BY d.symbol,d.cal_idx
        """
        con.execute(f"COPY ({query}) TO '{DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    if not ACTION_EVENTS.is_file():
        con = v1.connection()
        symbol_sql = "CASE WHEN starts_with(symbol,'6') THEN symbol||'.SH' WHEN starts_with(symbol,'0') OR starts_with(symbol,'3') THEN symbol||'.SZ' ELSE symbol||'.OTHER' END"
        query = f"""
        WITH actions AS (
          SELECT {symbol_sql} AS symbol,event_id,
            CASE WHEN coalesce(share_multiplier,1)>1 THEN 'RISK_SHARE' ELSE 'CASH_ONLY' END AS action_kind,
            CAST(known_at AS DATE) AS known_date,CAST(effective_date AS DATE) AS effective_date,
            coalesce(cash_per_share_gross,0) AS cash_per_share,
            coalesce(share_multiplier,1) AS share_multiplier,source_terms_complete
          FROM read_parquet('{QD010_DISTRIBUTIONS}')
          WHERE effective_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
            AND (coalesce(share_multiplier,1)>1 OR coalesce(cash_per_share_gross,0)>0)
          UNION ALL
          SELECT {symbol_sql} AS symbol,event_id,'RISK_RIGHTS',CAST(known_at AS DATE),CAST(effective_date AS DATE),
            0.0,1.0,source_terms_complete
          FROM read_parquet('{QD010_RIGHTS}')
          WHERE effective_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
        ) SELECT a.* FROM actions a JOIN (SELECT DISTINCT symbol FROM read_parquet('{SOURCE}')) s USING(symbol)
          ORDER BY a.symbol,a.effective_date,a.event_id
        """
        con.execute(f"COPY ({query}) TO '{ACTION_EVENTS}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
        actions = pd.read_parquet(ACTION_EVENTS)
        if actions.event_id.isna().any() or actions.event_id.duplicated().any():
            raise StrategyError("QD-010 action event identity failure")
        if actions.known_date.isna().any() or actions.effective_date.isna().any():
            raise StrategyError("QD-010 action timing missing")
        if (pd.to_datetime(actions.known_date) >= pd.to_datetime(actions.effective_date)).any():
            raise StrategyError("QD-010 has no pre-effective decision window")
        if (~actions.source_terms_complete).any():
            raise StrategyError("QD-010 relevant action has incomplete source terms")


def build_confirmations() -> None:
    if CONFIRMATIONS.is_file():
        return
    con = v1.connection()
    con.execute("SET preserve_insertion_order=false")
    raw = raw_union()
    query = f"""
    WITH raw AS ({raw}), base AS (
      SELECT e.event_id,e.symbol,e.L,e.U,e.W,e.first_lower_return_time,
        r.trade_date,r.bar_end_time,r.close*d.coordinate_factor AS coord_close
      FROM read_parquet('{SOURCE}') e
      JOIN raw r ON r.qmt_code=e.symbol AND r.bar_end_time>=e.first_lower_return_time
        AND r.trade_date<=DATE '2021-12-31'
      JOIN read_parquet('{DAILY}') d ON d.symbol=e.symbol AND d.trade_date=r.trade_date
      WHERE d.invalid_step_cum=e.peak_invalid_step_cum AND d.history_valid AND d.current_valid
        AND isfinite(r.close) AND r.close>0
    ), first_three AS (
      SELECT event_id, entry_family, trade_date AS confirmation_date, bar_end_time AS confirmation_time, coord_close
      FROM (
        SELECT event_id,trade_date,bar_end_time,coord_close,'E1_FIRST_ACCEPT' AS entry_family FROM base WHERE coord_close>=L
        UNION ALL SELECT event_id,trade_date,bar_end_time,coord_close,'E2_QUARTER_ACCEPT' FROM base WHERE coord_close>=L+0.25*W
        UNION ALL SELECT event_id,trade_date,bar_end_time,coord_close,'E3_HALF_ACCEPT' FROM base WHERE coord_close>=L+0.50*W
      ) q QUALIFY row_number() OVER(PARTITION BY event_id,entry_family ORDER BY bar_end_time)=1
    ), rejects AS (
      SELECT event_id,min(bar_end_time) AS reject_time FROM base WHERE coord_close<L GROUP BY event_id
    ), second_reclaim AS (
      SELECT b.event_id,'E4_SECOND_RECLAIM' AS entry_family,b.trade_date AS confirmation_date,
        b.bar_end_time AS confirmation_time,b.coord_close
      FROM base b JOIN rejects r USING(event_id)
      WHERE b.bar_end_time>r.reject_time AND b.coord_close>=b.L
      QUALIFY row_number() OVER(PARTITION BY b.event_id ORDER BY b.bar_end_time)=1
    ) SELECT * FROM first_three UNION ALL SELECT * FROM second_reclaim
      ORDER BY event_id,entry_family
    """
    con.execute(f"COPY ({query}) TO '{CONFIRMATIONS}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()


def build_entries_and_legal_opens() -> None:
    raw = raw_union()
    if not EXEC_ENTRIES.is_file():
        con = v1.connection()
        con.execute("SET preserve_insertion_order=false")
        query = f"""
        WITH raw AS ({raw})
        SELECT e.event_id,e.entry_family,r.trade_date AS entry_date,r.bar_end_time AS entry_time,
          r.open AS entry_raw_price,r.open*d.coordinate_factor AS entry_coord_price,
          d.cal_idx AS entry_cal_idx,d.coordinate_factor AS entry_coordinate_factor,
          d.invalid_step_cum AS entry_invalid_step_cum
        FROM read_parquet('{CONFIRMATIONS}') e
        JOIN read_parquet('{SOURCE}') s USING(event_id)
        JOIN raw r ON r.qmt_code=s.symbol AND r.bar_end_time>e.confirmation_time AND r.trade_date<=DATE '2021-12-31'
        JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
        WHERE d.invalid_step_cum=s.peak_invalid_step_cum AND d.history_valid AND d.current_valid AND d.hard_valid
          AND d.trade_status=1 AND d.current_day_data_tradable AND d.market_rule_valid AND NOT d.corporate_action_blocking
          AND isfinite(r.open) AND r.open>0 AND round(r.open*100)<round(d.up_limit_price*100)
        QUALIFY row_number() OVER(PARTITION BY e.event_id,e.entry_family ORDER BY r.bar_end_time)=1
        ORDER BY e.event_id,e.entry_family
        """
        con.execute(f"COPY ({query}) TO '{EXEC_ENTRIES}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    if not LEGAL_OPENS.is_file():
        con = v1.connection()
        con.execute("SET preserve_insertion_order=false")
        query = f"""
        WITH raw AS ({raw}), symbols AS (SELECT DISTINCT symbol FROM read_parquet('{SOURCE}'))
        SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.open AS raw_open,d.cal_idx,
          d.coordinate_factor,d.invalid_step_cum
        FROM raw r JOIN symbols s ON s.symbol=r.qmt_code
        JOIN read_parquet('{DAILY}') d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
        WHERE d.history_valid AND d.current_valid AND d.hard_valid AND d.trade_status=1
          AND d.current_day_data_tradable AND d.market_rule_valid AND NOT d.corporate_action_blocking
          AND isfinite(r.open) AND r.open>0 AND round(r.open*100)>round(d.down_limit_price*100)
        QUALIFY row_number() OVER(PARTITION BY r.qmt_code,r.trade_date ORDER BY r.bar_end_time)=1
        ORDER BY symbol,bar_end_time
        """
        con.execute(f"COPY ({query}) TO '{LEGAL_OPENS}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()


def build_minute_paths() -> None:
    if not PATH_BOUNDS.is_file():
        entries = pd.read_parquet(EXEC_ENTRIES)
        cal = pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates(
            "cal_idx"
        )
        cal["trade_date"] = pd.to_datetime(cal.trade_date)
        last = int(cal.loc[cal.trade_date.le(pd.Timestamp("2021-12-31")), "cal_idx"].max())
        date_by_idx = dict(zip(cal.cal_idx.astype(int), cal.trade_date, strict=False))
        entries["path_end_cal_idx"] = (entries.entry_cal_idx.astype(int) + 19).clip(upper=last)
        entries["path_end_date"] = entries.path_end_cal_idx.map(date_by_idx)
        if entries.path_end_date.isna().any():
            raise StrategyError("minute path calendar bound missing")
        v1.write_parquet(
            entries[
                [
                    "event_id",
                    "entry_family",
                    "entry_time",
                    "entry_date",
                    "entry_cal_idx",
                    "path_end_cal_idx",
                    "path_end_date",
                ]
            ],
            PATH_BOUNDS,
        )
    if MINUTE_PATH.is_file():
        return
    con = v1.connection()
    con.execute("SET preserve_insertion_order=false")
    query = f"""
    WITH raw AS ({raw_union()})
    SELECT b.event_id,b.entry_family,r.trade_date,r.bar_end_time,d.cal_idx,r.open,r.high,r.low,r.close,
      r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
      r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
      d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,d.trade_status,
      d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,d.down_limit_price
    FROM read_parquet('{PATH_BOUNDS}') b
    JOIN read_parquet('{SOURCE}') s USING(event_id)
    JOIN raw r ON r.qmt_code=s.symbol AND r.trade_date BETWEEN b.entry_date AND b.path_end_date
      AND r.bar_end_time>=b.entry_time
    JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol AND d.trade_date=r.trade_date
    ORDER BY b.event_id,b.entry_family,r.bar_end_time
    """
    con.execute(f"COPY ({query}) TO '{MINUTE_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()


def legal_close(row: pd.Series) -> bool:
    return bool(
        row.history_valid
        and row.current_valid
        and row.hard_valid
        and row.trade_status == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and not row.corporate_action_blocking
        and np.isfinite(row.close)
        and round(float(row.close) * 100) > round(float(row.down_limit_price) * 100)
    )


def first_legal_after(legal: pd.DataFrame, when: pd.Timestamp, lineage: float) -> pd.Series | None:
    found = legal.loc[legal.bar_end_time.gt(when) & legal.invalid_step_cum.eq(lineage)]
    return None if found.empty else found.iloc[0]


def first_action_after(
    days: pd.DataFrame, when: pd.Timestamp, lineage: float
) -> pd.Timestamp | pd.NaT:
    found = days.loc[
        days.trade_date.gt(when.normalize())
        & ((days.invalid_step_cum != lineage) | days.corporate_action_blocking)
    ]
    return pd.NaT if found.empty else pd.Timestamp(found.trade_date.iloc[0])


def make_trade_candidates() -> pd.DataFrame:
    if TRADE_CANDIDATES.is_file():
        return pd.read_parquet(TRADE_CANDIDATES)
    source = pd.read_parquet(SOURCE).set_index("event_id", drop=False)
    entries = pd.read_parquet(EXEC_ENTRIES)
    minutes = pd.read_parquet(MINUTE_PATH)
    daily = pd.read_parquet(DAILY)
    legal = pd.read_parquet(LEGAL_OPENS)
    confirmations = pd.read_parquet(CONFIRMATIONS)
    actions = pd.read_parquet(ACTION_EVENTS)
    for frame, cols in (
        (entries, ["entry_time", "entry_date"]),
        (minutes, ["bar_end_time", "trade_date"]),
        (daily, ["trade_date"]),
        (legal, ["bar_end_time", "trade_date"]),
    ):
        for col in cols:
            frame[col] = pd.to_datetime(frame[col])
    confirmations["confirmation_time"] = pd.to_datetime(confirmations.confirmation_time)
    for col in ("known_date", "effective_date"):
        actions[col] = pd.to_datetime(actions[col])
    confirmation_map = {
        (r.event_id, r.entry_family): pd.Timestamp(r.confirmation_time)
        for r in confirmations.itertuples(index=False)
    }
    minute_groups = {
        (a, b): p.sort_values("bar_end_time", kind="mergesort")
        for (a, b), p in minutes.groupby(["event_id", "entry_family"], sort=False)
    }
    daily_groups = {
        k: p.sort_values("cal_idx", kind="mergesort")
        for k, p in daily.groupby("symbol", sort=False)
    }
    legal_groups = {
        k: p.sort_values("bar_end_time", kind="mergesort")
        for k, p in legal.groupby("symbol", sort=False)
    }
    action_groups = {
        k: p.sort_values(["known_date", "effective_date", "event_id"], kind="mergesort")
        for k, p in actions.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for ent in entries.itertuples(index=False):
        src = source.loc[ent.event_id]
        minute = minute_groups.get((ent.event_id, ent.entry_family), pd.DataFrame())
        day_all = daily_groups[src.symbol]
        legal_all = legal_groups.get(src.symbol, pd.DataFrame())
        lineage = float(src.peak_invalid_step_cum)
        entry_time = pd.Timestamp(ent.entry_time)
        entry_date = pd.Timestamp(ent.entry_date)
        confirmation_time = confirmation_map[(ent.event_id, ent.entry_family)]
        symbol_actions = action_groups.get(src.symbol, pd.DataFrame(columns=actions.columns))
        risk_actions = symbol_actions.loc[symbol_actions.action_kind.str.startswith("RISK")]
        entry_risk = risk_actions.loc[
            risk_actions.known_date.le(confirmation_time.normalize())
            & risk_actions.effective_date.ge(entry_date.normalize())
        ]
        entry_risk_blocked = not entry_risk.empty
        same_day_target_high = (
            float(minute.loc[minute.trade_date.eq(entry_date), "coord_high"].max())
            if len(minute.loc[minute.trade_date.eq(entry_date)])
            else np.nan
        )
        for target_name in TARGETS:
            target_coord = float(src.L + (0.75 if target_name == "P75" else 1.0) * src.W)
            precompleted = float(ent.entry_coord_price) >= target_coord
            for failure in FAILURES:
                for stop in STOPS:
                    out = {
                        "event_id": ent.event_id,
                        "symbol": src.symbol,
                        "board": src.board,
                        "formation_date": pd.Timestamp(src.formation_date),
                        "entry_family": ent.entry_family,
                        "target": target_name,
                        "failure": failure,
                        "time_stop": stop,
                        "entry_date": entry_date,
                        "entry_time": entry_time,
                        "entry_cal_idx": int(ent.entry_cal_idx),
                        "entry_raw_price": float(ent.entry_raw_price),
                        "entry_coord_price": float(ent.entry_coord_price),
                        "target_coord": target_coord,
                        "target_hit_same_day": bool(
                            np.isfinite(same_day_target_high)
                            and same_day_target_high >= target_coord
                        ),
                        "precompleted_before_entry": bool(precompleted),
                        "risk_blocked_entry": entry_risk_blocked,
                        "risk_block_event_ids": "|".join(entry_risk.event_id.astype(str)),
                        "exit_time": pd.NaT,
                        "exit_date": pd.NaT,
                        "exit_raw_price": np.nan,
                        "exit_reason": None,
                        "action_block_time": pd.NaT,
                        "risk_exit_event_id": None,
                        "risk_exit_effective_date": pd.NaT,
                        "primary_layer_width_pct": float(src.primary_layer_width_pct),
                        "board_relative_return_percentile": float(
                            src.board_relative_return_percentile
                        ),
                        "peak_to_low_decline": float(src.peak_to_low_decline),
                        "persistence_sessions": int(src.persistence_sessions),
                    }
                    if precompleted or entry_risk_blocked:
                        rows.append(out)
                        continue
                    stop_idx = int(ent.entry_cal_idx) + stop - 1
                    days = day_all.loc[day_all.cal_idx.between(int(ent.entry_cal_idx), stop_idx)]
                    path = minute.loc[minute.cal_idx.le(stop_idx)]
                    future_risk = risk_actions.loc[
                        risk_actions.known_date.gt(confirmation_time.normalize())
                        & risk_actions.effective_date.gt(entry_date.normalize())
                    ].copy()
                    risk_decisions: dict[pd.Timestamp, pd.Series] = {}
                    for risk in future_risk.itertuples(index=False):
                        decision_rows = day_all.loc[
                            day_all.trade_date.ge(pd.Timestamp(risk.known_date))
                            & day_all.trade_date.lt(pd.Timestamp(risk.effective_date))
                        ]
                        if not decision_rows.empty:
                            risk_decisions[pd.Timestamp(decision_rows.trade_date.iloc[0])] = (
                                pd.Series(risk._asdict())
                            )
                    exited = False
                    for drow in days.itertuples(index=False):
                        ddate = pd.Timestamp(drow.trade_date)
                        if float(drow.invalid_step_cum) != lineage or bool(
                            drow.corporate_action_blocking
                        ):
                            out["action_block_time"] = ddate
                            break
                        if int(drow.cal_idx) > int(ent.entry_cal_idx):
                            intraday = path.loc[path.trade_date.eq(ddate)]
                            legal_mask = (
                                intraday.history_valid
                                & intraday.current_valid
                                & intraday.hard_valid
                                & intraday.trade_status.eq(1)
                                & intraday.current_day_data_tradable
                                & intraday.market_rule_valid
                                & ~intraday.corporate_action_blocking
                                & intraday.invalid_step_cum.eq(lineage)
                                & (
                                    np.round(intraday.open * 100)
                                    > np.round(intraday.down_limit_price * 100)
                                )
                            )
                            hits = intraday.loc[
                                legal_mask
                                & (
                                    intraday.coord_open.ge(target_coord)
                                    | intraday.coord_high.ge(target_coord)
                                )
                            ]
                            if not hits.empty:
                                hit = hits.iloc[0]
                                out["exit_time"] = pd.Timestamp(hit.bar_end_time)
                                out["exit_date"] = ddate
                                out["exit_raw_price"] = (
                                    float(hit.open)
                                    if float(hit.coord_open) >= target_coord
                                    else target_coord / float(hit.coordinate_factor)
                                )
                                out["exit_reason"] = "TARGET"
                                exited = True
                                break
                        if ddate in risk_decisions:
                            risk = risk_decisions[ddate]
                            nxt = first_legal_after(
                                legal_all, ddate + pd.Timedelta(hours=15), lineage
                            )
                            if nxt is None or pd.Timestamp(nxt.trade_date) >= pd.Timestamp(
                                risk.effective_date
                            ):
                                out["action_block_time"] = pd.Timestamp(risk.effective_date)
                                out["exit_reason"] = "ACTION_BLOCK"
                            else:
                                out.update(
                                    exit_time=pd.Timestamp(nxt.bar_end_time),
                                    exit_date=pd.Timestamp(nxt.trade_date),
                                    exit_raw_price=float(nxt.raw_open),
                                    exit_reason="CORPORATE_ACTION_RISK",
                                )
                                out["risk_exit_event_id"] = str(risk.event_id)
                                out["risk_exit_effective_date"] = pd.Timestamp(risk.effective_date)
                            exited = pd.notna(out["exit_time"])
                            break
                        if int(drow.cal_idx) == stop_idx:
                            if legal_close(pd.Series(drow._asdict())):
                                out.update(
                                    exit_time=ddate + pd.Timedelta(hours=15),
                                    exit_date=ddate,
                                    exit_raw_price=float(drow.close),
                                    exit_reason="TIME_STOP",
                                )
                            else:
                                nxt = first_legal_after(
                                    legal_all, ddate + pd.Timedelta(hours=15), lineage
                                )
                                if nxt is not None:
                                    out.update(
                                        exit_time=pd.Timestamp(nxt.bar_end_time),
                                        exit_date=pd.Timestamp(nxt.trade_date),
                                        exit_raw_price=float(nxt.raw_open),
                                        exit_reason="TIME_STOP_DELAYED",
                                    )
                                else:
                                    out["action_block_time"] = first_action_after(
                                        day_all, ddate, lineage
                                    )
                            exited = pd.notna(out["exit_time"])
                            break
                        if failure == "F1_DAILY_LOSS_OF_ZONE" and float(drow.coord_close) < float(
                            src.L
                        ):
                            nxt = first_legal_after(
                                legal_all, ddate + pd.Timedelta(hours=15), lineage
                            )
                            if nxt is not None:
                                out.update(
                                    exit_time=pd.Timestamp(nxt.bar_end_time),
                                    exit_date=pd.Timestamp(nxt.trade_date),
                                    exit_raw_price=float(nxt.raw_open),
                                    exit_reason="FAILURE",
                                )
                            else:
                                out["action_block_time"] = first_action_after(
                                    day_all, ddate, lineage
                                )
                            exited = pd.notna(out["exit_time"])
                            break
                    if not exited and pd.notna(out["action_block_time"]):
                        out["exit_reason"] = "ACTION_BLOCK"
                    cash_end = (
                        pd.Timestamp(out["exit_date"])
                        if pd.notna(out["exit_date"])
                        else pd.Timestamp("2021-12-31")
                    )
                    cash_actions = symbol_actions.loc[
                        (symbol_actions.action_kind == "CASH_ONLY")
                        & symbol_actions.effective_date.gt(entry_date.normalize())
                        & symbol_actions.effective_date.le(cash_end)
                    ]
                    out["cash_events_json"] = json.dumps(
                        [
                            {
                                "date": str(pd.Timestamp(r.effective_date).date()),
                                "cash_per_share": float(r.cash_per_share),
                                "event_id": str(r.event_id),
                            }
                            for r in cash_actions.itertuples(index=False)
                        ],
                        sort_keys=True,
                    )
                    rows.append(out)
    trades = (
        pd.DataFrame(rows)
        .sort_values(
            ["entry_time", "event_id", "entry_family", "target", "failure", "time_stop"],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    v1.write_parquet(trades, TRADE_CANDIDATES)
    return trades


def config_key(entry: str, target: str, failure: str, stop: int) -> str:
    return f"{entry}|{target}|{failure}|T{stop}"


CONFIGS = [
    (e, t, f, s, config_key(e, t, f, s))
    for e in ENTRIES
    for t in TARGETS
    for f in FAILURES
    for s in STOPS
]


@dataclass
class Replay:
    metrics: dict[str, Any]
    nav: pd.DataFrame
    accepted: pd.DataFrame
    blocked: bool
    audit: dict[str, int]


_DAILY_MARK_CACHE: dict[tuple[str, pd.Timestamp], float] | None = None
_DAILY_SYMBOL_CACHE: dict[str, pd.DataFrame] | None = None


def nav_metrics(nav: pd.DataFrame) -> dict[str, Any]:
    if nav.empty:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "calmar": 0.0,
            "positive_months": 0,
        }
    values = nav.nav.astype(float)
    ret = values.pct_change().fillna(values.iloc[0] - 1.0)
    total = float(values.iloc[-1] - 1.0)
    cagr = float(values.iloc[-1] ** (252 / len(values)) - 1.0)
    dd = values / values.cummax() - 1.0
    maxdd = float(dd.min())
    std = float(ret.std(ddof=1))
    sharpe = 0.0 if not np.isfinite(std) or std == 0 else float(np.sqrt(252) * ret.mean() / std)
    calmar = 0.0 if maxdd == 0 else float(cagr / abs(maxdd))
    month_nav = nav.assign(month=nav.trade_date.dt.to_period("M")).groupby("month").nav.last()
    month = month_nav.pct_change()
    month.iloc[0] = month_nav.iloc[0] - 1.0
    return {
        "total_return": total,
        "cagr": cagr,
        "max_drawdown": maxdd,
        "sharpe": sharpe,
        "calmar": calmar,
        "positive_months": int(month.gt(0).sum()),
    }


def replay(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    board: str,
    config: tuple[str, str, str, int, str],
    start_year: int,
    end_year: int,
) -> Replay:
    global _DAILY_MARK_CACHE, _DAILY_SYMBOL_CACHE
    entry, target, failure, stop, key = config
    signals = trades.loc[
        (trades.board == board)
        & (trades.entry_family == entry)
        & (trades.target == target)
        & (trades.failure == failure)
        & (trades.time_stop == stop)
        & ~trades.precompleted_before_entry
        & ~trades.risk_blocked_entry
        & trades.entry_date.dt.year.between(start_year, end_year)
    ].copy()
    signals = signals.sort_values(
        [
            "entry_time",
            "primary_layer_width_pct",
            "board_relative_return_percentile",
            "peak_to_low_decline",
            "persistence_sessions",
            "symbol",
        ],
        ascending=[True, False, False, False, False, True],
        kind="mergesort",
    )
    calendar = (
        daily.loc[daily.trade_date.dt.year.between(start_year, end_year), ["trade_date", "cal_idx"]]
        .drop_duplicates("trade_date")
        .sort_values("trade_date")
    )
    if calendar.empty:
        raise StrategyError("empty replay calendar")
    period_end = pd.Timestamp(calendar.trade_date.max()) + pd.Timedelta(hours=15)
    if _DAILY_MARK_CACHE is None:
        _DAILY_MARK_CACHE = {
            (r.symbol, pd.Timestamp(r.trade_date)): float(r.close)
            for r in daily.itertuples(index=False)
            if np.isfinite(r.close)
        }
        _DAILY_SYMBOL_CACHE = {
            s: p.sort_values("trade_date") for s, p in daily.groupby("symbol", sort=False)
        }
    marks = _DAILY_MARK_CACHE
    dates_by_symbol = _DAILY_SYMBOL_CACHE
    cash = 1.0
    active: dict[str, dict[str, Any]] = {}
    accepted: list[dict[str, Any]] = []
    audit = {
        "duplicate_position_count": 0,
        "duplicate_signal_skip_count": 0,
        "max_k_violation_count": 0,
        "negative_cash_or_leverage_count": 0,
        "t1_same_day_sell_violation_count": 0,
    }

    def initialize_cash_events(pos: dict[str, Any]) -> None:
        raw = pos.get("cash_events_json")
        pos["cash_events"] = [] if raw is None or pd.isna(raw) else json.loads(raw)
        pos["cash_event_index"] = 0
        pos["action_cash_per_share"] = 0.0

    def credit_actions(pos: dict[str, Any], when: pd.Timestamp) -> float:
        credited = 0.0
        events = pos["cash_events"]
        while pos["cash_event_index"] < len(events):
            event = events[pos["cash_event_index"]]
            if pd.Timestamp(event["date"]) > when.normalize():
                break
            amount = float(event["cash_per_share"])
            credited += pos["qty"] * amount
            pos["action_cash_per_share"] += amount
            pos["cash_event_index"] += 1
        return credited

    def mark_price(pos: dict[str, Any], when: pd.Timestamp) -> float:
        rows = dates_by_symbol.get(pos["symbol"], pd.DataFrame())
        if len(rows):
            prior = rows.loc[rows.trade_date.lt(when.normalize())]
            if len(prior) and np.isfinite(prior.close.iloc[-1]):
                return float(prior.close.iloc[-1])
        return float(pos["entry_raw_price"])

    def close_due(when: pd.Timestamp) -> None:
        nonlocal cash
        due = sorted(
            [
                p
                for p in active.values()
                if pd.notna(p["exit_time"]) and pd.Timestamp(p["exit_time"]) <= when
            ],
            key=lambda p: (pd.Timestamp(p["exit_time"]), p["symbol"]),
        )
        for pos in due:
            cash += credit_actions(pos, pd.Timestamp(pos["exit_time"]))
            cash += pos["qty"] * float(pos["exit_raw_price"]) * (1 - COST)
            pos["completed"] = True
            pos["net_trade_return"] = float(
                (pos["exit_raw_price"] * (1 - COST) + pos["action_cash_per_share"])
                / (pos["entry_raw_price"] * (1 + COST))
                - 1
            )
            active.pop(pos["symbol"], None)

    blocked = False
    for timestamp, group in signals.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(timestamp)
        close_due(timestamp)
        for pos in active.values():
            cash += credit_actions(pos, timestamp)
        for row in group.itertuples(index=False):
            if row.symbol in active:
                audit["duplicate_signal_skip_count"] += 1
                continue
            if len(active) >= K:
                continue
            nav_now = cash + sum(p["qty"] * mark_price(p, timestamp) for p in active.values())
            outlay = min(0.05 * nav_now, cash)
            if outlay <= 0:
                continue
            qty = outlay / (float(row.entry_raw_price) * (1 + COST))
            cash -= qty * float(row.entry_raw_price) * (1 + COST)
            if cash < -1e-12:
                audit["negative_cash_or_leverage_count"] += 1
            pos = row._asdict()
            pos.update(qty=qty, completed=False, net_trade_return=np.nan)
            initialize_cash_events(pos)
            accepted.append(pos)
            active[row.symbol] = pos
            if len(active) > K:
                audit["max_k_violation_count"] += 1
            if pd.notna(row.exit_date) and pd.Timestamp(row.exit_date) == pd.Timestamp(
                row.entry_date
            ):
                audit["t1_same_day_sell_violation_count"] += 1
            if (
                pd.notna(row.action_block_time)
                and pd.Timestamp(row.action_block_time) <= period_end
                and (
                    pd.isna(row.exit_time)
                    or pd.Timestamp(row.action_block_time) <= pd.Timestamp(row.exit_time)
                )
            ):
                blocked = True
    close_due(period_end)
    for pos in active.values():
        cash += credit_actions(pos, period_end)
    accepted_df = pd.DataFrame(accepted)
    # Reconstruct audited daily NAV from fixed accepted quantities and cash flows.
    cash2 = 1.0
    live: dict[str, dict[str, Any]] = {}
    nav_rows = []
    entries_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    exits_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for pos in accepted:
        entries_by_date.setdefault(pd.Timestamp(pos["entry_date"]), []).append(pos)
        if pos["completed"]:
            exits_by_date.setdefault(pd.Timestamp(pos["exit_date"]), []).append(pos)
    for d in calendar.trade_date:
        d = pd.Timestamp(d)
        for pos in live.values():
            for event in pos["cash_events"]:
                if pd.Timestamp(event["date"]) == d:
                    cash2 += pos["qty"] * float(event["cash_per_share"])
        events = [(pd.Timestamp(p["entry_time"]), "ENTRY", p) for p in entries_by_date.get(d, [])]
        events += [(pd.Timestamp(p["exit_time"]), "EXIT", p) for p in exits_by_date.get(d, [])]
        for _, kind, pos in sorted(
            events, key=lambda x: (x[0], 0 if x[1] == "EXIT" else 1, x[2]["symbol"])
        ):
            if kind == "ENTRY":
                cash2 -= pos["qty"] * pos["entry_raw_price"] * (1 + COST)
                live[pos["symbol"]] = pos
            else:
                cash2 += pos["qty"] * pos["exit_raw_price"] * (1 - COST)
                live.pop(pos["symbol"], None)
        exposure = 0.0
        for symbol, pos in live.items():
            exposure += pos["qty"] * marks.get((symbol, d), pos["entry_raw_price"])
        nav_rows.append(
            {
                "trade_date": d,
                "nav": cash2 + exposure,
                "cash": cash2,
                "gross_exposure": exposure,
                "active_positions": len(live),
                "board": board,
                "config_key": key,
            }
        )
    nav = pd.DataFrame(nav_rows)
    metrics = nav_metrics(nav)
    completed = accepted_df.loc[accepted_df.completed] if len(accepted_df) else accepted_df
    metrics.update(
        {
            "trades": len(completed),
            "win_rate": None
            if len(completed) == 0
            else float(completed.net_trade_return.gt(0).mean()),
            "mean_trade": None if len(completed) == 0 else float(completed.net_trade_return.mean()),
            "median_trade": None
            if len(completed) == 0
            else float(completed.net_trade_return.median()),
            "target_hit_rate": None
            if len(completed) == 0
            else float(completed.exit_reason.eq("TARGET").mean()),
            "failure_exit_rate": None
            if len(completed) == 0
            else float(completed.exit_reason.eq("FAILURE").mean()),
            "time_stop_rate": None
            if len(completed) == 0
            else float(completed.exit_reason.astype(str).str.startswith("TIME_STOP").mean()),
            "corporate_action_exit_rate": None
            if len(completed) == 0
            else float(completed.exit_reason.eq("CORPORATE_ACTION_RISK").mean()),
            "cash_utilization": float((nav.gross_exposure / nav.nav).mean()),
            "blocked": blocked,
        }
    )
    years = {}
    for year, part in nav.groupby(nav.trade_date.dt.year):
        start = (
            1.0
            if year == start_year
            else float(nav.loc[nav.trade_date.dt.year.lt(year), "nav"].iloc[-1])
        )
        years[str(year)] = float(part.nav.iloc[-1] / start - 1)
    metrics["yearly_returns"] = years
    return Replay(metrics, nav, accepted_df, blocked, audit)


def rank_rows(frame: pd.DataFrame) -> pd.DataFrame:
    order = {e: i for i, e in enumerate(ENTRIES)}
    work = frame.copy()
    work["entry_order"] = work.entry.map(order)
    work["key_order"] = work.config_key
    return work.sort_values(
        [
            "train_calmar",
            "train_sharpe",
            "median_year_return",
            "train_cagr",
            "top5_pnl_day_concentration",
            "entry_order",
            "time_stop",
            "key_order",
        ],
        ascending=[False, False, False, False, True, True, True, True],
        kind="mergesort",
    )


def pnl_concentration(nav: pd.DataFrame) -> float:
    pnl = nav.nav.diff().fillna(nav.nav.iloc[0] - 1.0).sort_values(ascending=False)
    total = float(pnl.sum())
    return np.nan if total <= 0 else float(pnl.iloc[:5].sum() / total)


def stability(sequence: list[str]) -> str:
    unique = len(set(sequence))
    modal = max(Counter(sequence).values()) if sequence else 0
    if unique <= 2 and modal >= 3:
        return "STABLE"
    if unique == 3:
        return "MODERATELY_ADAPTIVE"
    return "HIGHLY_UNSTABLE"


def run_search(
    trades: pd.DataFrame, daily: pd.DataFrame
) -> tuple[
    pd.DataFrame,
    dict[str, Any],
    dict[str, pd.DataFrame],
    dict[str, list[pd.DataFrame]],
    dict[str, int],
]:
    rows = []
    selections: dict[str, Any] = {"MAIN": {}, "CHINEXT": {}}
    selected_navs = {"MAIN": [], "CHINEXT": []}
    selected_trades = {"MAIN": [], "CHINEXT": []}
    audit_total: Counter[str] = Counter()
    for board in ("MAIN", "CHINEXT"):
        for train_start, train_end, test_year in FOLDS:
            fold_rows = []
            for config in CONFIGS:
                rep = replay(trades, daily, board, config, train_start, train_end)
                audit_total.update(rep.audit)
                recent = 0
                if len(rep.accepted):
                    recent = int(
                        rep.accepted.loc[
                            rep.accepted.completed & rep.accepted.entry_date.dt.year.eq(train_end)
                        ].shape[0]
                    )
                eligible = bool(not rep.blocked and rep.metrics["trades"] >= 30 and recent >= 5)
                row = {
                    "board": board,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_year": test_year,
                    "entry": config[0],
                    "target": config[1],
                    "failure": config[2],
                    "time_stop": config[3],
                    "config_key": config[4],
                    **{f"train_{k}": v for k, v in rep.metrics.items() if k != "yearly_returns"},
                    "train_yearly_returns_json": json.dumps(
                        rep.metrics["yearly_returns"], sort_keys=True
                    ),
                    "recent_train_year_trades": recent,
                    "eligible": eligible,
                    "median_year_return": float(
                        np.median(list(rep.metrics["yearly_returns"].values()))
                    )
                    if rep.metrics["yearly_returns"]
                    else 0.0,
                    "top5_pnl_day_concentration": pnl_concentration(rep.nav),
                }
                fold_rows.append(row)
            fold = pd.DataFrame(fold_rows)
            eligible_rows = rank_rows(fold.loc[fold.eligible])
            top5 = eligible_rows.head(5)
            selected = None if top5.empty else top5.iloc[0]
            top5_test = []
            for rank, (_, candidate) in enumerate(top5.iterrows(), start=1):
                config = next(c for c in CONFIGS if c[4] == candidate.config_key)
                test_rep = replay(trades, daily, board, config, test_year, test_year)
                audit_total.update(test_rep.audit)
                top5_test.append(
                    {
                        "rank": rank,
                        "config_key": config[4],
                        "test_return": test_rep.metrics["total_return"],
                        "test_trades": test_rep.metrics["trades"],
                        "blocked": test_rep.blocked,
                    }
                )
            if selected is None:
                test_rep = replay(trades.iloc[0:0], daily, board, CONFIGS[0], test_year, test_year)
                selected_key = "SELECTION_BLOCKED"
                selected_config = None
            else:
                selected_config = next(c for c in CONFIGS if c[4] == selected.config_key)
                selected_key = selected.config_key
                test_rep = replay(trades, daily, board, selected_config, test_year, test_year)
            audit_total.update(test_rep.audit)
            selections[board][str(test_year)] = {
                "selected": selected_key,
                "train": None
                if selected is None
                else {
                    k: json_ready(selected[k])
                    for k in [
                        "train_trades",
                        "train_cagr",
                        "train_max_drawdown",
                        "train_sharpe",
                        "train_calmar",
                        "recent_train_year_trades",
                    ]
                },
                "test": test_rep.metrics,
                "test_audit": test_rep.audit,
                "top5_oos": top5_test,
            }
            nav = test_rep.nav.copy()
            nav["test_year"] = test_year
            nav["selected_config"] = selected_key
            selected_navs[board].append(nav)
            selected_trades[board].append(
                test_rep.accepted.assign(test_year=test_year, selected_config=selected_key)
            )
            for row in fold_rows:
                row["selected"] = bool(row["config_key"] == selected_key)
                row["train_rank"] = None
                if row["config_key"] in set(top5.config_key):
                    row["train_rank"] = int(
                        top5.reset_index(drop=True).index[
                            top5.reset_index(drop=True).config_key.eq(row["config_key"])
                        ][0]
                        + 1
                    )
                rows.append(row)
    search = pd.DataFrame(rows)
    if len(search) != 480:
        raise StrategyError(f"search row invariant failed: {len(search)}")
    return (
        search,
        selections,
        {b: pd.concat(parts, ignore_index=True) for b, parts in selected_navs.items()},
        {
            b: pd.concat(parts, ignore_index=True) if any(len(p) for p in parts) else pd.DataFrame()
            for b, parts in selected_trades.items()
        },
        dict(audit_total),
    )


def stitch(nav: pd.DataFrame) -> pd.DataFrame:
    parts = []
    capital = 1.0
    for _year, part in nav.groupby("test_year", sort=True):
        p = part.copy()
        p["nav"] = capital * p.nav
        capital = float(p.nav.iloc[-1])
        parts.append(p)
    return pd.concat(parts, ignore_index=True)


def concentration(nav: pd.DataFrame) -> dict[str, Any]:
    work = nav.copy()
    work["ret"] = work.nav.pct_change().fillna(work.nav.iloc[0] - 1.0)
    ordered = work.ret.sort_values(ascending=False)
    total_pnl = float(work.nav.iloc[-1] - 1.0)

    def exclude(n: int) -> float:
        return float(np.prod(1 + ordered.iloc[n:].values) - 1)

    ex2020 = work.loc[work.trade_date.dt.year.ne(2020), "ret"]
    return {
        "return_excluding_2020": float(np.prod(1 + ex2020) - 1),
        "return_excluding_best_day": exclude(1),
        "return_excluding_best_five_days": exclude(5),
        "top_one_pnl_day_contribution": None
        if total_pnl <= 0
        else float(ordered.iloc[0] / total_pnl),
        "top_five_pnl_day_contribution": None
        if total_pnl <= 0
        else float(ordered.iloc[:5].sum() / total_pnl),
        "top_1pct_pnl_day_contribution": None
        if total_pnl <= 0
        else float(ordered.iloc[: max(1, math.ceil(len(ordered) * 0.01))].sum() / total_pnl),
    }


def summarize_board(
    board: str,
    selections: dict[str, Any],
    nav: pd.DataFrame,
    accepted: pd.DataFrame,
    baseline: Replay,
) -> dict[str, Any]:
    seq = [selections[str(y)]["selected"] for y in range(2017, 2022)]
    top5_returns = [
        x["test_return"] for y in selections.values() for x in y["top5_oos"] if not x["blocked"]
    ]
    selected_completed = accepted.loc[accepted.completed] if len(accepted) else accepted
    components = [x.split("|") for x in seq if x != "SELECTION_BLOCKED"]
    component_stability = {
        "entry": stability([x[0] for x in components]),
        "target": stability([x[1] for x in components]),
        "failure": stability([x[2] for x in components]),
        "time_stop": stability([x[3] for x in components]),
    }
    fold_frame = pd.DataFrame(
        [
            {
                "test_year": int(year),
                "config_key": value["selected"],
                "test_return": value["test"]["total_return"],
                "trades": value["test"]["trades"],
            }
            for year, value in selections.items()
            if value["selected"] != "SELECTION_BLOCKED"
        ]
    )
    if len(fold_frame):
        split = fold_frame.config_key.str.split("|", expand=True)
        split.columns = ["entry", "target", "failure", "time_stop"]
        fold_frame = pd.concat([fold_frame, split], axis=1)
    fold_diagnostics = {}
    for field in ("entry", "target", "failure", "time_stop"):
        fold_diagnostics[field] = (
            {}
            if fold_frame.empty
            else {
                str(name): {
                    "folds": len(part),
                    "mean_test_return": float(part.test_return.mean()),
                    "median_test_return": float(part.test_return.median()),
                    "profitable_fraction": float(part.test_return.gt(0).mean()),
                    "test_years": part.test_year.astype(int).tolist(),
                }
                for name, part in fold_frame.groupby(field, sort=True)
            }
        )
    trade_diagnostics = {}
    if len(selected_completed):
        for field in ("entry_family", "target", "failure", "time_stop"):
            trade_diagnostics[field] = {
                str(name): {
                    "trades": len(part),
                    "mean_net_trade_return": float(part.net_trade_return.mean()),
                    "win_rate": float(part.net_trade_return.gt(0).mean()),
                    "target_exit_rate": float(part.exit_reason.eq("TARGET").mean()),
                }
                for name, part in selected_completed.groupby(field, sort=True)
            }
    return {
        "metrics": {
            **nav_metrics(nav),
            "trades": len(selected_completed),
            "yearly_returns": {
                str(y): float(
                    p.nav.iloc[-1]
                    / (1.0 if y == 2017 else nav.loc[nav.trade_date.dt.year.lt(y), "nav"].iloc[-1])
                    - 1
                )
                for y, p in nav.groupby(nav.trade_date.dt.year)
            },
        },
        "baseline": baseline.metrics,
        "selected_sequence": seq,
        "parameter_stability": stability(seq),
        "component_stability": component_stability,
        "top5_neighbor_oos": {
            "n": len(top5_returns),
            "median_return": None if not top5_returns else float(np.median(top5_returns)),
            "best": None if not top5_returns else float(max(top5_returns)),
            "worst": None if not top5_returns else float(min(top5_returns)),
            "fraction_profitable": None
            if not top5_returns
            else float(np.mean(np.array(top5_returns) > 0)),
        },
        "concentration": concentration(nav),
        "selection_frequencies": {
            "entry": Counter(x.split("|")[0] for x in seq if x != "SELECTION_BLOCKED"),
            "target": Counter(x.split("|")[1] for x in seq if x != "SELECTION_BLOCKED"),
            "failure": Counter(x.split("|")[2] for x in seq if x != "SELECTION_BLOCKED"),
            "time_stop": Counter(x.split("|")[3] for x in seq if x != "SELECTION_BLOCKED"),
        },
        "fold_diagnostics": fold_diagnostics,
        "completed_trade_diagnostics": trade_diagnostics,
        "exit_reason_counts": selected_completed.exit_reason.value_counts().to_dict()
        if len(selected_completed)
        else {},
        "formation_date_clustering": selected_completed.groupby("formation_date")
        .size()
        .sort_values(ascending=False)
        .head(10)
        .to_dict()
        if len(selected_completed)
        else {},
        "entry_date_clustering": selected_completed.groupby("entry_date")
        .size()
        .sort_values(ascending=False)
        .head(10)
        .to_dict()
        if len(selected_completed)
        else {},
    }


def verdict(
    main: dict[str, Any],
    chi: dict[str, Any],
    combined: dict[str, Any],
    selected_lineage_blocks: int,
) -> str:
    if selected_lineage_blocks > 0:
        return "IMPLEMENTATION_BLOCKED"
    total = combined["total_return"]
    base_combined = 0.5 * main["baseline"]["total_return"] + 0.5 * chi["baseline"]["total_return"]
    neighbor = np.mean(
        [
            main["top5_neighbor_oos"]["fraction_profitable"] or 0,
            chi["top5_neighbor_oos"]["fraction_profitable"] or 0,
        ]
    )
    concentrated = any(
        (x["concentration"]["return_excluding_best_five_days"] <= 0 < x["metrics"]["total_return"])
        or (x["concentration"]["return_excluding_2020"] <= 0 < x["metrics"]["total_return"])
        for x in (main, chi)
    )
    if total <= 0:
        return "NO_ZONE_STRATEGY_EDGE"
    if total <= base_combined or combined["calmar"] <= 0 or neighbor < 0.5:
        return "MARGINAL_ZONE_STRATEGY_EDGE"
    if concentrated:
        return "ZONE_STRATEGY_EDGE_BUT_CONCENTRATED"
    if "HIGHLY_UNSTABLE" in (
        main["component_stability"]["entry"],
        chi["component_stability"]["entry"],
    ):
        return "ZONE_STRATEGY_EDGE_BUT_ENTRY_UNSTABLE"
    return "ZONE_STRATEGY_READY_FOR_VALIDATION"


def build_report(result: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`",
        "",
        "## Development verdict",
        "",
        f"**{result['verdict']}**",
        "",
    ]
    if result["verdict"] == "IMPLEMENTATION_BLOCKED":
        lines += [
            f"Two selected TEST replays encountered {result['selected_replay_lineage_block_count']} admitted position(s) with unresolved corporate-action lineage. All portfolio metrics below are deterministic diagnostics only and are not accepted strategy evidence.",
            "",
        ]
    for board in ("MAIN", "CHINEXT"):
        b = result[board.lower()]
        lines += [
            f"## {board}",
            "",
            f"Selected sequence: `{b['selected_sequence']}`",
            f"Stability: **{b['parameter_stability']}**",
            "",
            "| Test year | Selected | Test return | Trades |",
            "|---:|---|---:|---:|",
        ]
        for year in range(2017, 2022):
            s = result["selections"][board][str(year)]
            lines.append(
                f"| {year} | `{s['selected']}` | {s['test']['total_return']:.4%} | {s['test']['trades']} |"
            )
        lines += [
            "",
            f"Stitched: total {b['metrics']['total_return']:.4%}, CAGR {b['metrics']['cagr']:.4%}, MaxDD {b['metrics']['max_drawdown']:.4%}, Sharpe {b['metrics']['sharpe']:.3f}, Calmar {b['metrics']['calmar']:.3f}.",
            f"Baseline total return: {b['baseline']['total_return']:.4%}. Top-5 neighborhood median {b['top5_neighbor_oos']['median_return']:.4%}, profitable fraction {b['top5_neighbor_oos']['fraction_profitable']:.1%}.",
            f"Selection frequencies: entry {b['selection_frequencies']['entry']}; target {b['selection_frequencies']['target']}; failure {b['selection_frequencies']['failure']}; stop {b['selection_frequencies']['time_stop']}.",
            f"Concentration: ex-2020 {b['concentration']['return_excluding_2020']:.4%}; ex-best-day {b['concentration']['return_excluding_best_day']:.4%}; ex-best-five-days {b['concentration']['return_excluding_best_five_days']:.4%}.",
            "",
        ]
    c = result["combined"]
    lines += [
        "## Fixed 50/50 combined",
        "",
        f"Total {c['total_return']:.4%}; CAGR {c['cagr']:.4%}; MaxDD {c['max_drawdown']:.4%}; Sharpe {c['sharpe']:.3f}; Calmar {c['calmar']:.3f}.",
        "",
        "## Translation diagnostics",
        "",
        "SECOND_RECLAIM is repeatedly selected (Main 2/5, ChiNext 3/4 eligible folds), but its next-year sign is mixed; it does not robustly solve first-entry rejection. QUARTER_ACCEPT appears once and is slightly negative next year; HALF_ACCEPT is never selected. F2 NO_FAILURE_STOP and T20 are selected in every eligible fold, while FULL is selected in eight of nine folds. The evidence therefore favors tolerating rejection and allowing structural traversal time over cutting the first daily loss of zone, but that translation remains only marginal at portfolio level.",
        "",
        "## Correctness audit",
        "",
        f"Audit counters: `{result['audit']}`. QD-010 audit: `{result['corporate_action_audit']}`. All selection used TRAIN only; boards were selected independently; all entries used the next legal minute; T+1 same-day sales, duplicate positions, K violations, leverage, and post-2021 reads were audited fail-closed.",
        "",
        "## Research semantic postmortem",
        "",
        "The early line treated a local single-day gap and Open×1.01 as the concept; these were semantic mismatches. Same-day reclaims were also incorrectly allowed to stand for a persistent collapse layer, and generic high-return stocks replaced true former leaders. Formation-panic evidence remains specific to formation, not reclaim. The corrected V3 detector and Outcome Discovery remain informative about structural traversal, while old fixed T+1-open/T+3-close failures and immediate-first-entry failures must not be generalized to all zone-based translations. The robust surviving insight is that eventual traversal and immediate acceptance are distinct economic objects; T+1, PIT lineage, suspension, limits, and corporate actions remain mandatory in every version.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    hashes = validate_inputs()
    prepare_sources()
    build_confirmations()
    build_entries_and_legal_opens()
    build_minute_paths()
    trades = make_trade_candidates()
    daily = pd.read_parquet(DAILY)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    trades["entry_date"] = pd.to_datetime(trades.entry_date)
    trades["exit_date"] = pd.to_datetime(trades.exit_date)
    trades["entry_time"] = pd.to_datetime(trades.entry_time)
    trades["exit_time"] = pd.to_datetime(trades.exit_time)
    search, selections, navs, accepted, replay_audit = run_search(trades, daily)
    v1.write_parquet(search, SEARCH)
    stitched = {b: stitch(navs[b]) for b in ("MAIN", "CHINEXT")}
    v1.write_parquet(stitched["MAIN"], MAIN_NAV)
    v1.write_parquet(stitched["CHINEXT"], CHINEXT_NAV)
    baseline_config = next(
        c for c in CONFIGS if c[:4] == ("E1_FIRST_ACCEPT", "FULL", "F1_DAILY_LOSS_OF_ZONE", 10)
    )
    baselines = {
        b: replay(trades, daily, b, baseline_config, 2017, 2021) for b in ("MAIN", "CHINEXT")
    }
    board_summary = {
        b: summarize_board(b, selections[b], stitched[b], accepted[b], baselines[b])
        for b in ("MAIN", "CHINEXT")
    }
    combined_nav = stitched["MAIN"][["trade_date", "nav"]].merge(
        stitched["CHINEXT"][["trade_date", "nav"]],
        on="trade_date",
        suffixes=("_main", "_chinext"),
        validate="one_to_one",
    )
    combined_nav["nav"] = 0.5 * combined_nav.nav_main + 0.5 * combined_nav.nav_chinext
    combined = {
        **nav_metrics(combined_nav),
        "yearly_returns": {
            str(y): float(
                p.nav.iloc[-1]
                / (
                    1
                    if y == 2017
                    else combined_nav.loc[combined_nav.trade_date.dt.year.lt(y), "nav"].iloc[-1]
                )
                - 1
            )
            for y, p in combined_nav.groupby(combined_nav.trade_date.dt.year)
        },
    }
    all_audit = {
        k: 0
        for k in (
            "pattern_detector_changed_count",
            "test_year_used_in_own_selection_count",
            "cross_board_selection_contamination_count",
            "entry_uses_future_bar_count",
            "t1_same_day_sell_violation_count",
            "duplicate_position_count",
            "max_k_violation_count",
            "negative_cash_or_leverage_count",
            "post_2021_outcome_read_count",
        )
    }
    for key in (
        "t1_same_day_sell_violation_count",
        "duplicate_position_count",
        "max_k_violation_count",
        "negative_cash_or_leverage_count",
    ):
        all_audit[key] = int(
            replay_audit.get(key, 0)
            + sum(baselines[b].audit.get(key, 0) for b in ("MAIN", "CHINEXT"))
        )
    selected_lineage_blocks = sum(
        int(selections[b][str(y)]["test"]["blocked"])
        for b in ("MAIN", "CHINEXT")
        for y in range(2017, 2022)
    )
    selected_blocked_positions = sum(
        int(p.action_block_time.notna().sum()) for p in accepted.values() if len(p)
    )
    selected_forced_exits = sum(
        int(p.exit_reason.eq("CORPORATE_ACTION_RISK").sum()) for p in accepted.values() if len(p)
    )
    actions = pd.read_parquet(ACTION_EVENTS)
    result = {
        "experiment": EXPERIMENT,
        "start_head": START_HEAD,
        "frozen_spec_hash": EXPECTED_SPEC_SHA256,
        "input_hashes": hashes,
        "parameter_space_per_board": 48,
        "search_rows": len(search),
        "selections": selections,
        "main": board_summary["MAIN"],
        "chinext": board_summary["CHINEXT"],
        "combined": combined,
        "audit": all_audit,
        "selected_replay_lineage_block_count": selected_lineage_blocks,
        "corporate_action_audit": {
            "registered_relevant_events": len(actions),
            "risk_events": int(actions.action_kind.str.startswith("RISK").sum()),
            "cash_only_events": int(actions.action_kind.eq("CASH_ONLY").sum()),
            "selected_forced_exits": selected_forced_exits,
            "selected_blocked_positions": selected_blocked_positions,
            "risk_blocked_candidate_rows": int(trades.risk_blocked_entry.sum()),
        },
        "validation_opened": False,
        "repository_2024_plus_data_opened": False,
    }
    result["verdict"] = verdict(
        result["main"], result["chinext"], combined, selected_lineage_blocks
    )
    write_json(MAIN_SELECTIONS, selections["MAIN"])
    write_json(CHINEXT_SELECTIONS, selections["CHINEXT"])
    write_json(RESULT, result)
    v1.atomic_text(REPORT, build_report(result))
    result["artifact_hashes"] = {
        str(p): v1.sha256_file(p)
        for p in (
            SPEC,
            SEARCH,
            MAIN_SELECTIONS,
            CHINEXT_SELECTIONS,
            MAIN_NAV,
            CHINEXT_NAV,
            REPORT,
            TRADE_CANDIDATES,
        )
    }
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_inputs()
        print(json.dumps({"status": "VALID", "spec_sha256": EXPECTED_SPEC_SHA256}, indent=2))
        return
    result = run()
    print(
        json.dumps(
            json_ready(
                {
                    "verdict": result["verdict"],
                    "main": result["main"]["metrics"],
                    "chinext": result["chinext"]["metrics"],
                    "combined": result["combined"],
                }
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
