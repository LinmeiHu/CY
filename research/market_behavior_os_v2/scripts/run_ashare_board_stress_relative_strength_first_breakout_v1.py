#!/usr/bin/env python3
"""Frozen causal replay for board-stress relative-strength first-breakout V1.

Stage A creates the candidate parquet without outcomes.  This runner evaluates
all three preregistered profiles on 2014-2018, freezes exactly one profile, and
then evaluates only that profile on 2019-2021.  It never reads post-2021 rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from run_ashare_forced_liquidation_stabilized_reversal_simple_rule_development_v1 import (
    metrics,
    replay_one,
)


PROFILES = (
    {"profile": "H10_NEXT_OPEN", "target": None, "horizon": 10, "stop": False},
    {"profile": "H20_NEXT_OPEN", "target": None, "horizon": 20, "stop": False},
    {"profile": "T10_H20_NEXT_OPEN", "target": 0.10, "horizon": 20, "stop": False},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_paths(candidates: pd.DataFrame, daily_path: Path, max_date: str) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("candidates", candidates)
    query = f"""
    SELECT
      c.event_id,c.symbol,c.sleeve,c.signal_date,c.cal_idx AS signal_cal_idx,
      c.invalid_step_cum AS signal_invalid_step_cum,
      d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
      d.coord_open,d.coord_high,d.coord_low,d.coord_close,
      d.coordinate_factor,d.invalid_step_cum,d.trade_status,
      d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_valid,
      d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
    FROM candidates c
    JOIN read_parquet('{daily_path.as_posix()}') d
      ON c.symbol=d.symbol
     AND d.cal_idx > c.cal_idx
    WHERE d.trade_date <= DATE '{max_date}'
    ORDER BY c.event_id,d.cal_idx
    """
    return con.execute(query).fetchdf()


def replay(candidates: pd.DataFrame, paths: pd.DataFrame, profiles: tuple[dict[str, object], ...]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    by_event = {key: part for key, part in paths.groupby("event_id", sort=False)}
    for candidate in candidates.itertuples(index=False):
        row = pd.Series(candidate._asdict())
        row["signal_cal_idx"] = int(row.cal_idx)
        row["signal_invalid_step_cum"] = float(row.invalid_step_cum)
        if "stabilized_low_coord" not in row or pd.isna(row["stabilized_low_coord"]):
            row["stabilized_low_coord"] = 0.0
        path = by_event.get(candidate.event_id, pd.DataFrame())
        for profile in profiles:
            records.append(replay_one(row, path, profile))
    return pd.DataFrame(records)


def annual_metrics(frame: pd.DataFrame, years: range) -> dict[str, dict[str, object]]:
    dates = pd.to_datetime(frame.signal_date)
    return {str(year): metrics(frame.loc[dates.dt.year.eq(year)]) for year in years}


def select_profile(
    discovery: pd.DataFrame, profiles: tuple[dict[str, object], ...]
) -> tuple[str, list[dict[str, object]]]:
    ranking: list[dict[str, object]] = []
    for profile in profiles:
        name = str(profile["profile"])
        part = discovery.loc[discovery.profile.eq(name)]
        yearly = annual_metrics(part, range(2014, 2019))
        yearly_means = [yearly[str(year)]["mean_net"] for year in range(2014, 2019)]
        if any(value is None for value in yearly_means):
            raise RuntimeError(f"Incomplete discovery year for {name}")
        finite = [float(value) for value in yearly_means]
        pooled = metrics(part)
        ranking.append(
            {
                "profile": name,
                "yearly": yearly,
                "yearly_mean_net": dict(zip((str(year) for year in range(2014, 2019)), finite)),
                "median_annual_mean_net": float(np.median(finite)),
                "pooled": pooled,
                "horizon": int(profile["horizon"]),
            }
        )
    ranking.sort(
        key=lambda row: (
            -float(row["median_annual_mean_net"]),
            -float(row["pooled"]["mean_net"]),
            int(row["horizon"]),
            str(row["profile"]),
        )
    )
    return str(ranking[0]["profile"]), ranking


def run(candidate_path: Path, daily_path: Path, contract_path: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = json.loads(contract_path.read_text())
    profiles = tuple(contract.get("fixed_profiles", PROFILES))
    if not profiles:
        raise RuntimeError("No replay profiles are frozen in the contract")
    candidates = pd.read_parquet(candidate_path).rename(columns={"trade_date": "signal_date"})
    if candidates.empty or pd.to_datetime(candidates.signal_date).max() > pd.Timestamp("2021-12-31"):
        raise RuntimeError("Candidate identity is empty or contains post-2021 signals")
    required = {"event_id", "symbol", "sleeve", "signal_date", "cal_idx", "invalid_step_cum"}
    missing = required.difference(candidates.columns)
    if missing:
        raise RuntimeError(f"Missing frozen candidate fields: {sorted(missing)}")

    discovery_candidates = candidates.loc[pd.to_datetime(candidates.signal_date).dt.year.le(2018)].copy()
    discovery_paths = load_paths(discovery_candidates, daily_path, "2019-03-31")
    discovery = replay(discovery_candidates, discovery_paths, profiles)
    selected, ranking = select_profile(discovery, profiles)
    selected_profile = tuple(profile for profile in profiles if profile["profile"] == selected)

    confirmation_candidates = candidates.loc[pd.to_datetime(candidates.signal_date).dt.year.between(2019, 2021)].copy()
    confirmation_paths = load_paths(confirmation_candidates, daily_path, "2021-12-31")
    confirmation = replay(confirmation_candidates, confirmation_paths, selected_profile)

    discovery_path = output_dir / "discovery_outcomes.parquet"
    confirmation_path = output_dir / "confirmation_outcomes.parquet"
    discovery.to_parquet(discovery_path, index=False)
    confirmation.to_parquet(confirmation_path, index=False)

    selected_discovery = discovery.loc[discovery.profile.eq(selected)]
    discovery_annual = annual_metrics(selected_discovery, range(2014, 2019))
    confirmation_annual = annual_metrics(confirmation, range(2019, 2022))
    confirmation_pooled = metrics(confirmation)
    annual_completed = [int(confirmation_annual[str(year)]["completed_trades"]) for year in range(2019, 2022)]
    continuation = bool(
        np.mean(annual_completed) > 50
        and confirmation_pooled["mean_net"] is not None
        and float(confirmation_pooled["mean_net"]) > 0.03
        and confirmation_pooled["median_net"] is not None
        and float(confirmation_pooled["median_net"]) > 0
        and all(
            confirmation_annual[str(year)]["mean_net"] is not None
            and float(confirmation_annual[str(year)]["mean_net"]) > 0
            for year in range(2019, 2022)
        )
    )
    completed = pd.concat(
        [
            selected_discovery.loc[selected_discovery.status.eq("COMPLETED")],
            confirmation.loc[confirmation.status.eq("COMPLETED")],
        ],
        ignore_index=True,
    )
    result = {
        "experiment": str(contract["experiment_id"]),
        "contract_sha256": sha256(contract_path),
        "candidate_sha256": sha256(candidate_path),
        "candidate_count": int(len(candidates)),
        "profile_ranking": ranking,
        "selected_profile": selected,
        "selected_discovery": {
            "pooled": metrics(selected_discovery),
            "annual": discovery_annual,
        },
        "selected_confirmation": {
            "pooled": confirmation_pooled,
            "annual": confirmation_annual,
            "board": {
                board: metrics(confirmation.loc[confirmation.sleeve.eq(board)])
                for board in ("MAIN", "CHINEXT")
            },
        },
        "continuation_gate_pass": continuation,
        "audit": {
            "signal_bar_fill_count": int(completed.entry_cal_idx.le(completed.signal_cal_idx).sum()),
            "t1_same_day_exit_count": int(completed.exit_cal_idx.le(completed.entry_cal_idx).sum()),
            "post_2021_signal_count": int(pd.to_datetime(completed.signal_date).dt.year.gt(2021).sum()),
            "post_2021_exit_count": int(pd.to_datetime(completed.exit_date).dt.year.gt(2021).sum()),
            "alternate_profile_confirmation_rows": 0,
            "repository_2022_plus_outcomes_opened": False,
            "repository_2024_plus_data_opened": False,
        },
        "artifacts": {
            "discovery_outcomes_sha256": sha256(discovery_path),
            "confirmation_outcomes_sha256": sha256(confirmation_path),
        },
    }
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--daily", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.candidates, args.daily, args.contract, args.output_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
