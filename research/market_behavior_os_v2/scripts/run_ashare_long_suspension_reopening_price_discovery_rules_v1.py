#!/usr/bin/env python3
"""Evaluate the visually compressed long-suspension reopening rules once."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-LONG-SUSPENSION-REOPENING-PRICE-DISCOVERY-RULES-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
REVIEW_LOG = REPO / (
    "research/market_behavior_os_v2/results/"
    "ASHARE-LONG-SUSPENSION-REOPENING-PRICE-DISCOVERY-MOTHER-V1-"
    "VISUAL-REVIEW-LOG.md"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
MOTHER_ROOT = DATA_ROOT / "ashare_long_suspension_reopening_price_discovery_mother_v1"
CANDIDATES = MOTHER_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = MOTHER_ROOT / "stage_b/future_paths.parquet"
DAILY = DATA_ROOT / (
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
REGIME = DATA_ROOT / (
    "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
OUTPUT_ROOT = DATA_ROOT / "ashare_long_suspension_reopening_price_discovery_rules_v1"
EVENTS = OUTPUT_ROOT / "development/event_level.parquet"
MARKET_INTERVALS = OUTPUT_ROOT / "development/market_interval_medians.parquet"
RESULT = REPO / f"research/market_behavior_os_v2/results/{EXPERIMENT}_result.json"
REPORT = REPO / f"research/market_behavior_os_v2/results/{EXPERIMENT}.md"
EXPECTED_HASHES = {
    SPEC: "7d8bb90fda69116a3888906a2942eb8798952c1f81350343bd6e0bf71ebfc6e6",
    REVIEW_LOG: "22dbe54f485a10caf7db3f9cc21f99f75381f5d10626a4bd9d37095d41347485",
    CANDIDATES: "0f29af9f2b747a9650c9593da15a6f49c82a2a5984ec6d9c2f3da0610ecdae35",
    PATHS: "bcfe149df26aa4a06672d6bb6e8a8d45b36b9ab7f8956ab84805215eb6649a26",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
ROUND_TRIP_COST = 0.004
HORIZON = 20
MAX_OUTCOME_DATE = pd.Timestamp("2021-03-31")


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, PIT, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift: {path}: {actual[str(path)]} != {expected}"
            )
    return actual


def legal_open(row: Any) -> bool:
    required = (
        row.trade_status,
        row.current_day_data_tradable,
        row.current_valid,
        row.market_rule_valid,
        row.corporate_action_count,
        row.corporate_action_valid,
        row.corporate_action_blocking,
        row.hard_valid,
        row.open,
        row.coord_open,
        row.invalid_step_cum,
        row.coordinate_factor,
    )
    return bool(
        not any(pd.isna(value) for value in required)
        and int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and bool(row.current_valid)
        and bool(row.market_rule_valid)
        and int(row.corporate_action_count) == 0
        and bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and bool(row.hard_valid)
        and np.isfinite(float(row.open))
        and float(row.open) > 0
        and np.isfinite(float(row.coord_open))
        and float(row.coord_open) > 0
    )


def valid_traded_close(row: Any) -> bool:
    return bool(
        legal_open(row)
        and not pd.isna(row.close)
        and not pd.isna(row.coord_close)
        and np.isfinite(float(row.close))
        and float(row.close) > 0
        and np.isfinite(float(row.coord_close))
        and float(row.coord_close) > 0
    )


def buyable_open(row: Any) -> bool:
    return bool(
        legal_open(row)
        and not pd.isna(row.up_limit_price)
        and np.isfinite(float(row.up_limit_price))
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: Any) -> bool:
    return bool(
        legal_open(row)
        and not pd.isna(row.down_limit_price)
        and np.isfinite(float(row.down_limit_price))
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def phase(ret20: float, ret60: float) -> str:
    if not np.isfinite(ret20) or not np.isfinite(ret60):
        return "UNKNOWN"
    recent_speed = ret20 / 20.0
    medium_speed = ret60 / 60.0
    if ret60 >= 0:
        return "UP_ACCELERATING" if recent_speed > medium_speed else "UP_DECELERATING"
    return "DOWN_RECOVERING" if recent_speed > medium_speed else "DOWN_DETERIORATING"


def locate_anchor_and_observation(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    lineage = float(candidate.invalid_step_cum)
    if path.empty:
        return {"pre_status": "NO_FUTURE_PATH"}
    anchor = None
    for row in path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {"pre_status": "INVALID_COORDINATE_LINEAGE_BEFORE_ANCHOR"}
        if buyable_open(row):
            anchor = row
            break
    if anchor is None:
        return {"pre_status": "NO_LEGAL_ANCHOR"}

    observed: list[Any] = []
    for row in path.loc[path.cal_idx.ge(anchor.cal_idx)].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {
                "pre_status": "INVALID_COORDINATE_LINEAGE_DURING_OBSERVATION",
                "anchor_date": pd.Timestamp(anchor.trade_date),
                "anchor_cal_idx": int(anchor.cal_idx),
                "anchor_price": float(anchor.coord_open),
            }
        if valid_traded_close(row):
            observed.append(row)
            if len(observed) == 5:
                break
    if len(observed) != 5:
        return {
            "pre_status": "INCOMPLETE_FIVE_TRADED_SESSION_OBSERVATION",
            "anchor_date": pd.Timestamp(anchor.trade_date),
            "anchor_cal_idx": int(anchor.cal_idx),
            "anchor_price": float(anchor.coord_open),
        }
    observation = observed[-1]
    return {
        "pre_status": "OBSERVATION_COMPLETE",
        "anchor_date": pd.Timestamp(anchor.trade_date),
        "anchor_cal_idx": int(anchor.cal_idx),
        "anchor_price": float(anchor.coord_open),
        "observation_date": pd.Timestamp(observation.trade_date),
        "observation_cal_idx": int(observation.cal_idx),
        "observation_close": float(observation.coord_close),
        "stock_observation_return": float(observation.coord_close)
        / float(anchor.coord_open)
        - 1.0,
    }


def build_market_interval_medians(intervals: pd.DataFrame) -> pd.DataFrame:
    if intervals.empty:
        return pd.DataFrame(
            columns=["anchor_date", "observation_date", "market_median_return", "market_n"]
        )
    pairs = intervals[["anchor_date", "observation_date"]].drop_duplicates().copy()
    pairs = pairs.sort_values(["anchor_date", "observation_date"]).reset_index(drop=True)
    pairs["pair_id"] = np.arange(len(pairs), dtype=np.int64)
    temporary = OUTPUT_ROOT / "duckdb_tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET memory_limit='12GB'")
    con.execute(f"SET temp_directory='{temporary.as_posix()}'")
    con.register("pairs", pairs)
    query = f"""
      SELECT p.pair_id,p.anchor_date,p.observation_date,
        median(e.coord_close / s.coord_open - 1.0) AS market_median_return,
        count(*) AS market_n
      FROM pairs p
      JOIN read_parquet('{DAILY.as_posix()}') s
        ON s.trade_date=p.anchor_date
      JOIN read_parquet('{DAILY.as_posix()}') e
        ON e.symbol=s.symbol AND e.trade_date=p.observation_date
      WHERE s.trade_status=1 AND e.trade_status=1
        AND s.current_day_data_tradable AND e.current_day_data_tradable
        AND s.current_valid AND e.current_valid
        AND s.market_rule_valid AND e.market_rule_valid
        AND s.hard_valid AND e.hard_valid
        AND s.historical_identity_valid AND e.historical_identity_valid
        AND NOT s.is_st AND NOT e.is_st
        AND s.corporate_action_count=0 AND e.corporate_action_count=0
        AND s.corporate_action_valid AND e.corporate_action_valid
        AND NOT s.corporate_action_blocking AND NOT e.corporate_action_blocking
        AND s.coord_open IS NOT NULL AND e.coord_close IS NOT NULL
        AND isfinite(s.coord_open) AND isfinite(e.coord_close)
        AND s.coord_open>0 AND e.coord_close>0
        AND s.invalid_step_cum=e.invalid_step_cum
      GROUP BY p.pair_id,p.anchor_date,p.observation_date
      ORDER BY p.pair_id
    """
    result = con.execute(query).fetch_df()
    con.close()
    for column in ("anchor_date", "observation_date"):
        result[column] = pd.to_datetime(result[column])
    if len(result) != len(pairs) or result.market_median_return.isna().any():
        raise ResearchError("market interval construction failed closed")
    return result.drop(columns="pair_id")


def replay_accepted(
    candidate: Any, feature: Any, path: pd.DataFrame
) -> dict[str, Any]:
    lineage = float(candidate.invalid_step_cum)
    entry = None
    for row in path.loc[
        path.cal_idx.gt(feature.observation_cal_idx)
        & path.cal_idx.le(feature.observation_cal_idx + 3)
    ].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {"status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY"}
        if buyable_open(row):
            entry = row
            break
    if entry is None:
        return {"status": "NO_LEGAL_ENTRY_AFTER_ACCEPTANCE"}

    entry_idx = int(entry.cal_idx)
    entry_fields = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": float(entry.coord_open),
    }
    below_run = 0
    failure_pending = False
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {
                **entry_fields,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        h20_due = int(row.cal_idx) >= entry_idx + HORIZON
        if (failure_pending or h20_due) and sellable_open(row):
            exit_price = float(row.coord_open)
            gross = exit_price / float(entry.coord_open) - 1.0
            reason = "TWO_CLOSES_BELOW_ANCHOR" if failure_pending else "H20_NEXT_LEGAL_OPEN"
            return {
                **entry_fields,
                "status": "COMPLETED",
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": exit_price,
                "exit_reason": reason,
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross,
                "net_return": gross - ROUND_TRIP_COST,
            }
        if valid_traded_close(row):
            if float(row.coord_close) < float(feature.anchor_price):
                below_run += 1
            else:
                below_run = 0
            if below_run >= 2:
                failure_pending = True
    return {**entry_fields, "status": "INCOMPLETE_PATH"}


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def rounded(value: float | int | None) -> float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    return round(float(value), 8)


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    paths = pd.read_parquet(PATHS)
    regime = pd.read_parquet(REGIME)
    for column in ("pre_suspension_trade_date", "signal_date"):
        candidates[column] = pd.to_datetime(candidates[column])
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    if len(candidates) != 4459 or candidates.event_id.duplicated().any():
        raise ResearchError("candidate identity drift")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered development evaluation")
    if paths.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("path context crossed frozen cap")

    path_groups = {str(key): part for key, part in paths.groupby("event_id", sort=False)}
    feature_rows: list[dict[str, Any]] = []
    for candidate in candidates.itertuples(index=False):
        feature_rows.append(
            {
                "event_id": str(candidate.event_id),
                **locate_anchor_and_observation(
                    candidate, path_groups.get(str(candidate.event_id), pd.DataFrame())
                ),
            }
        )
    features = pd.DataFrame(feature_rows)
    complete = features.loc[features.pre_status.eq("OBSERVATION_COMPLETE")].copy()
    market = build_market_interval_medians(complete)
    write_parquet(market, MARKET_INTERVALS)
    complete = complete.merge(
        market, on=["anchor_date", "observation_date"], how="left", validate="many_to_one"
    )
    if complete.market_median_return.isna().any():
        raise ResearchError("missing causal market interval return")
    features = features.merge(
        complete[
            ["event_id", "market_median_return", "market_n"]
        ],
        on="event_id",
        how="left",
        validate="one_to_one",
    )

    events = candidates.merge(features, on="event_id", how="left", validate="one_to_one")
    events = events.merge(
        regime[
            ["trade_date", "market_median_ret20", "market_median_ret60"]
        ].rename(columns={"trade_date": "observation_date"}),
        on="observation_date",
        how="left",
        suffixes=("_signal", "_observation"),
        validate="many_to_one",
    )
    events["market_phase"] = [
        phase(float(r20), float(r60))
        if not pd.isna(r20) and not pd.isna(r60)
        else "UNKNOWN"
        for r20, r60 in zip(
            events.market_median_ret20_observation,
            events.market_median_ret60_observation,
            strict=True,
        )
    ]
    events["anchor_accepted"] = (
        events.pre_status.eq("OBSERVATION_COMPLETE")
        & events.observation_close.ge(events.anchor_price)
    )
    events["relative_accepted"] = (
        events.pre_status.eq("OBSERVATION_COMPLETE")
        & events.stock_observation_return.gt(events.market_median_return)
    )
    events["admitted"] = events.anchor_accepted & events.relative_accepted

    replay_rows: list[dict[str, Any]] = []
    candidate_lookup = candidates.set_index("event_id", drop=False)
    for feature in events.itertuples(index=False):
        if not bool(feature.admitted):
            replay_rows.append({"event_id": str(feature.event_id), "status": "NOT_ADMITTED"})
            continue
        candidate = candidate_lookup.loc[str(feature.event_id)]
        replay_rows.append(
            {
                "event_id": str(feature.event_id),
                **replay_accepted(
                    candidate,
                    feature,
                    path_groups.get(str(feature.event_id), pd.DataFrame()),
                ),
            }
        )
    replay = pd.DataFrame(replay_rows)
    events = events.merge(replay, on="event_id", how="left", validate="one_to_one")
    events = events.sort_values(["signal_date", "symbol", "event_id"], kind="mergesort")
    completed = events.loc[events.status.eq("COMPLETED")].copy()
    if not completed.empty:
        if completed.entry_date.le(completed.observation_date).any():
            raise ResearchError("entry is not strictly after observation close")
        if completed.exit_date.le(completed.entry_date).any():
            raise ResearchError("exit violates T+1")
        if completed.exit_date.max() > MAX_OUTCOME_DATE:
            raise ResearchError("development outcome crossed frozen cap")
    write_parquet(events, EVENTS)

    annual_rows: list[dict[str, Any]] = []
    for year in range(2015, 2021):
        part = completed.loc[completed.signal_date.dt.year.eq(year)]
        annual_rows.append(
            {
                "year": year,
                "completed_n": int(len(part)),
                "mean_net_return": rounded(part.net_return.mean()),
                "median_net_return": rounded(part.net_return.median()),
                "positive_rate": rounded(part.net_return.gt(0).mean()),
                "mean_gross_return": rounded(part.gross_return.mean()),
            }
        )
    phase_rows: list[dict[str, Any]] = []
    for name, part in completed.groupby("market_phase", dropna=False):
        phase_rows.append(
            {
                "market_phase": str(name),
                "completed_n": int(len(part)),
                "mean_net_return": rounded(part.net_return.mean()),
                "median_net_return": rounded(part.net_return.median()),
            }
        )
    every_year_breadth_pass = all(row["completed_n"] > 50 for row in annual_rows)
    pooled_mean = rounded(completed.net_return.mean())
    return_pass = bool(pooled_mean is not None and float(pooled_mean) > 0.04)
    gate_pass = bool(every_year_breadth_pass and return_pass)
    payload: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "scientific_role": "DATA_GENERATED_CANDLE_ANATOMY_RULE_COMPRESSION",
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes,
        "post_2021_signal_read": False,
        "max_evaluation_outcome_date": str(completed.exit_date.max().date())
        if not completed.empty
        else None,
        "mother_events": int(len(events)),
        "observation_complete_n": int(events.pre_status.eq("OBSERVATION_COMPLETE").sum()),
        "anchor_accepted_n": int(events.anchor_accepted.sum()),
        "relative_accepted_n": int(events.relative_accepted.sum()),
        "admitted_n": int(events.admitted.sum()),
        "completed_n": int(len(completed)),
        "status_counts": {
            str(key): int(value) for key, value in events.status.value_counts(dropna=False).items()
        },
        "exit_reason_counts": {
            str(key): int(value)
            for key, value in completed.exit_reason.value_counts(dropna=False).items()
        },
        "annual": annual_rows,
        "market_phase": phase_rows,
        "pooled": {
            "mean_net_return": pooled_mean,
            "median_net_return": rounded(completed.net_return.median()),
            "positive_rate": rounded(completed.net_return.gt(0).mean()),
            "mean_gross_return": rounded(completed.gross_return.mean()),
        },
        "development_gate": {
            "every_year_completed_n_gt_50": every_year_breadth_pass,
            "pooled_mean_net_return_gt_4pct": return_pass,
            "pass": gate_pass,
        },
        "decision": "OPEN_2022_2024_FROZEN_VALIDATION" if gate_pass else "CLOSE_EXACT_FAMILY",
        "event_level_path": str(EVENTS),
        "event_level_sha256": sha256(EVENTS),
        "market_intervals_path": str(MARKET_INTERVALS),
        "market_intervals_sha256": sha256(MARKET_INTERVALS),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    lines = [
        f"# {EXPERIMENT}",
        "",
        "Status: " + str(payload["decision"]),
        "",
        "The four rules were frozen from the complete candle review before this aggregation.",
        "No post-2021 signal was read.",
        "",
        "## Development gate",
        "",
        f"- Mother events: {payload['mother_events']:,}",
        f"- Admitted: {payload['admitted_n']:,}",
        f"- Completed: {payload['completed_n']:,}",
        f"- Pooled mean net: {100 * float(payload['pooled']['mean_net_return'] or 0):.3f}%",
        f"- Breadth gate: {every_year_breadth_pass}",
        f"- Return gate: {return_pass}",
        f"- Overall gate: {gate_pass}",
        "",
        "## Annual",
        "",
        "| Year | Completed | Mean net | Median net | Positive rate |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in annual_rows:
        lines.append(
            f"| {row['year']} | {row['completed_n']} | "
            f"{100 * float(row['mean_net_return'] or 0):.3f}% | "
            f"{100 * float(row['median_net_return'] or 0):.3f}% | "
            f"{100 * float(row['positive_rate'] or 0):.1f}% |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "The frozen gate passed; the unchanged rules may be evaluated on 2022–2024."
                if gate_pass
                else "The frozen gate failed. Close this exact family without parameter, horizon, or regime rescue."
            ),
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
