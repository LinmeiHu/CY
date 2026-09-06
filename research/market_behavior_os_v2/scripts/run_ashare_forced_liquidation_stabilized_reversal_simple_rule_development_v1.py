#!/usr/bin/env python3
"""Frozen Stage-B replay for forced-liquidation stabilized reversal V1.

The candidate parquet and contract are frozen before this runner is invoked.
This runner reads security outcomes through 2021 only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-FORCED-LIQUIDATION-STABILIZED-REVERSAL-SIMPLE-RULE-DEVELOPMENT-V1"
PROFILES = (
    {"profile": "H10_NEXT_OPEN", "target": None, "horizon": 10, "stop": False},
    {"profile": "H20_NEXT_OPEN", "target": None, "horizon": 20, "stop": False},
    {"profile": "T10_H20_NO_STOP", "target": 0.10, "horizon": 20, "stop": False},
    {"profile": "T10_H20_STABILIZED_LOW_STOP", "target": 0.10, "horizon": 20, "stop": True},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def legal_state(row: pd.Series) -> bool:
    required = (
        "trade_status",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
    )
    if any(pd.isna(row.get(field)) for field in required):
        return False
    return bool(
        int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def buyable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.up_limit_price, row.coordinate_factor)
    if not legal_state(row) or not all(np.isfinite(float(value)) for value in values):
        return False
    return bool(
        float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
    )


def sellable_open(row: pd.Series) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    if not legal_state(row) or not all(np.isfinite(float(value)) for value in values):
        return False
    return bool(
        float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def load_paths(candidate_path: Path, daily_path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    query = f"""
    SELECT
      c.event_id,c.symbol,c.sleeve,c.signal_date,c.cal_idx AS signal_cal_idx,
      c.stabilized_low_coord,c.invalid_step_cum AS signal_invalid_step_cum,
      d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
      d.coord_open,d.coord_high,d.coord_low,d.coord_close,
      d.coordinate_factor,d.invalid_step_cum,d.trade_status,
      d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_valid,
      d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price
    FROM read_parquet('{candidate_path.as_posix()}') c
    JOIN read_parquet('{daily_path.as_posix()}') d
      ON c.symbol=d.symbol
     AND d.cal_idx > c.cal_idx
    WHERE d.trade_date <= DATE '2021-12-31'
    ORDER BY c.event_id,d.cal_idx
    """
    return con.execute(query).fetchdf()


def replay_one(candidate: pd.Series, path: pd.DataFrame, profile: dict[str, object]) -> dict[str, object]:
    signal_idx = int(candidate.signal_cal_idx)
    signal_invalid = float(candidate.signal_invalid_step_cum)
    base = {
        "event_id": candidate.event_id,
        "symbol": candidate.symbol,
        "sleeve": candidate.sleeve,
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_cal_idx": signal_idx,
        "profile": str(profile["profile"]),
    }
    if path.empty:
        return {**base, "status": "NO_FUTURE_PATH_THROUGH_2021"}
    entry_pool = path.loc[path.cal_idx.le(signal_idx + 3)].copy()
    entry_pool = entry_pool.loc[entry_pool.invalid_step_cum.eq(signal_invalid)]
    entry_row = next((row for _, row in entry_pool.iterrows() if buyable_open(row)), None)
    if entry_row is None:
        return {**base, "status": "NO_LEGAL_ENTRY"}

    entry_idx = int(entry_row.cal_idx)
    entry_price = float(entry_row.coord_open)
    target_return = profile["target"]
    target_price = None if target_return is None else entry_price * (1.0 + float(target_return))
    pending_reason: str | None = None
    decision_idx: int | None = None
    censored = False
    exit_payload: dict[str, object] | None = None

    future = path.loc[path.cal_idx.gt(entry_idx)].sort_values("cal_idx")
    for _, row in future.iterrows():
        if not np.isfinite(float(row.invalid_step_cum)) or float(row.invalid_step_cum) != signal_invalid:
            censored = True
            break

        if pending_reason is not None and sellable_open(row):
            exit_payload = {
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": float(row.coord_open),
                "exit_reason": pending_reason,
                "exit_decision_cal_idx": decision_idx,
            }
            break

        if (
            target_price is not None
            and legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target_price
        ):
            exit_payload = {
                "exit_date": pd.Timestamp(row.trade_date),
                "exit_cal_idx": int(row.cal_idx),
                "exit_price": target_price,
                "exit_reason": "TARGET_10",
                "exit_decision_cal_idx": entry_idx,
            }
            break

        if not legal_state(row) or not np.isfinite(float(row.coord_close)):
            continue
        if bool(profile["stop"]) and float(row.coord_close) < float(candidate.stabilized_low_coord):
            pending_reason = "STABILIZED_LOW_STOP"
            decision_idx = int(row.cal_idx)
        elif int(row.cal_idx) >= entry_idx + int(profile["horizon"]):
            pending_reason = f"H{int(profile['horizon'])}_TIME_STOP"
            decision_idx = int(row.cal_idx)

    if censored:
        return {
            **base,
            "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            "entry_date": pd.Timestamp(entry_row.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
        }
    if exit_payload is None:
        return {
            **base,
            "status": "INCOMPLETE_BY_2021_END",
            "entry_date": pd.Timestamp(entry_row.trade_date),
            "entry_cal_idx": entry_idx,
            "entry_price": entry_price,
        }

    gross = float(exit_payload["exit_price"]) / entry_price - 1.0
    return {
        **base,
        "status": "COMPLETED",
        "entry_date": pd.Timestamp(entry_row.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
        **exit_payload,
        "holding_sessions": int(exit_payload["exit_cal_idx"]) - entry_idx,
        "gross_return": gross,
        "net_return": gross - 0.004,
    }


def metrics(frame: pd.DataFrame) -> dict[str, object]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    returns = pd.to_numeric(completed.net_return, errors="coerce")
    return {
        "signals": int(len(frame)),
        "completed_trades": int(len(completed)),
        "mean_net": None if completed.empty else float(returns.mean()),
        "median_net": None if completed.empty else float(returns.median()),
        "win_rate": None if completed.empty else float(returns.gt(0).mean()),
        "severe_loss10": None if completed.empty else float(returns.le(-0.10).mean()),
        "target_hit": None if completed.empty else float(completed.exit_reason.eq("TARGET_10").mean()),
        "mean_holding_sessions": None if completed.empty else float(completed.holding_sessions.mean()),
    }


def annual_metrics(frame: pd.DataFrame, years: range) -> dict[str, dict[str, object]]:
    return {
        str(year): metrics(frame.loc[pd.to_datetime(frame.signal_date).dt.year.eq(year)])
        for year in years
    }


def select_profile(outcomes: pd.DataFrame) -> tuple[str | None, list[dict[str, object]]]:
    ranking: list[dict[str, object]] = []
    discovery = outcomes.loc[pd.to_datetime(outcomes.signal_date).dt.year.le(2018)]
    for profile in (item["profile"] for item in PROFILES):
        part = discovery.loc[discovery.profile.eq(profile)]
        yearly = annual_metrics(part, range(2014, 2019))
        yearly_means = [yearly[str(year)]["mean_net"] for year in range(2014, 2019)]
        finite = [float(value) for value in yearly_means if value is not None]
        positive_years = sum(value > 0 for value in finite)
        pooled = metrics(part)
        eligible = len(finite) == 5 and positive_years >= 3
        ranking.append(
            {
                "profile": profile,
                "eligible": eligible,
                "positive_years": positive_years,
                "yearly_mean_net": dict(zip((str(year) for year in range(2014, 2019)), yearly_means)),
                "median_year_mean": None if len(finite) != 5 else float(np.median(finite)),
                "pooled_median_net": pooled["median_net"],
                "pooled_severe_loss10": pooled["severe_loss10"],
                "horizon": next(int(item["horizon"]) for item in PROFILES if item["profile"] == profile),
            }
        )
    eligible_rows = [row for row in ranking if row["eligible"]]
    if not eligible_rows:
        return None, ranking
    selected = sorted(
        eligible_rows,
        key=lambda row: (
            -float(row["median_year_mean"]),
            -float(row["pooled_median_net"]),
            float(row["pooled_severe_loss10"]),
            int(row["horizon"]),
            str(row["profile"]),
        ),
    )[0]
    return str(selected["profile"]), ranking


def run(candidate_path: Path, daily_path: Path, contract_path: Path, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = json.loads(contract_path.read_text())
    candidates = pd.read_parquet(candidate_path)
    if pd.to_datetime(candidates.signal_date).max() > pd.Timestamp("2021-12-31"):
        raise RuntimeError("Candidate file contains post-2021 rows")
    paths = load_paths(candidate_path, daily_path)
    records: list[dict[str, object]] = []
    by_event = {key: part for key, part in paths.groupby("event_id", sort=False)}
    for candidate in candidates.itertuples(index=False):
        path = by_event.get(candidate.event_id, pd.DataFrame())
        row = pd.Series(candidate._asdict())
        row["signal_cal_idx"] = row.pop("cal_idx")
        row["signal_invalid_step_cum"] = row.pop("invalid_step_cum")
        for profile in PROFILES:
            records.append(replay_one(row, path, profile))
    outcomes = pd.DataFrame(records)
    outcomes_path = output_dir / "outcomes.parquet"
    outcomes.to_parquet(outcomes_path, index=False)
    selected, ranking = select_profile(outcomes)
    selected_frame = outcomes.loc[outcomes.profile.eq(selected)] if selected is not None else outcomes.iloc[0:0]
    confirmation = selected_frame.loc[pd.to_datetime(selected_frame.signal_date).dt.year.ge(2019)]
    confirmation_yearly = annual_metrics(confirmation, range(2019, 2022))
    confirmation_metrics = metrics(confirmation)
    completed_per_year = [confirmation_yearly[str(year)]["completed_trades"] for year in range(2019, 2022)]
    continuation_pass = bool(
        selected is not None
        and np.mean(completed_per_year) > 50
        and confirmation_metrics["mean_net"] is not None
        and float(confirmation_metrics["mean_net"]) >= 0.03
        and confirmation_metrics["median_net"] is not None
        and float(confirmation_metrics["median_net"]) > 0
        and all(
            confirmation_yearly[str(year)]["mean_net"] is not None
            and float(confirmation_yearly[str(year)]["mean_net"]) > 0
            for year in range(2019, 2022)
        )
    )
    result = {
        "experiment": str(contract.get("experiment", EXPERIMENT)),
        "contract_sha256": sha256(contract_path),
        "candidate_sha256": sha256(candidate_path),
        "outcomes_sha256": sha256(outcomes_path),
        "candidate_count": int(len(candidates)),
        "profile_ranking": ranking,
        "selected_profile": selected,
        "selected_discovery": None
        if selected is None
        else {
            "pooled": metrics(selected_frame.loc[pd.to_datetime(selected_frame.signal_date).dt.year.le(2018)]),
            "annual": annual_metrics(selected_frame, range(2014, 2019)),
        },
        "selected_confirmation": {
            "pooled": confirmation_metrics,
            "annual": confirmation_yearly,
            "board": {
                board: metrics(confirmation.loc[confirmation.sleeve.eq(board)])
                for board in ("MAIN", "CHINEXT")
            },
        },
        "continuation_gate_pass": continuation_pass,
        "audit": {
            "signal_bar_fill_count": int(
                outcomes.loc[outcomes.status.eq("COMPLETED")].entry_cal_idx.le(
                    outcomes.loc[outcomes.status.eq("COMPLETED")].signal_cal_idx
                ).sum()
            ),
            "t1_same_day_exit_count": int(
                outcomes.loc[outcomes.status.eq("COMPLETED")].exit_cal_idx.le(
                    outcomes.loc[outcomes.status.eq("COMPLETED")].entry_cal_idx
                ).sum()
            ),
            "post_2021_signal_count": int(pd.to_datetime(outcomes.signal_date).dt.year.gt(2021).sum()),
            "post_2021_exit_count": int(
                pd.to_datetime(outcomes.get("exit_date"), errors="coerce").dt.year.gt(2021).sum()
            ),
            "repository_2022_plus_outcomes_opened": False,
            "repository_2024_plus_data_opened": False,
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
    result = run(args.candidates, args.daily, args.contract, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
