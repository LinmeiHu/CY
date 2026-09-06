#!/usr/bin/env python3
"""Evaluate the once-frozen visual rule compression on the 2015-2020 mother events."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-POST-LOW-FULL-FLOAT-TRANSFER-BASE-RESOLUTION-RULES-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / (
    "research/market_behavior_os_v2/experiments/"
    f"{EXPERIMENT}_freeze.json"
)
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
MOTHER_ROOT = DATA_ROOT / "ashare_post_low_full_float_transfer_base_resolution_mother_v1"
CANDIDATES = MOTHER_ROOT / "stage_a/candidates_frozen.parquet"
PATHS = MOTHER_ROOT / "stage_b/future_paths.parquet"
OUTPUT_ROOT = DATA_ROOT / "ashare_post_low_full_float_transfer_base_resolution_rules_v1"
TRADES = OUTPUT_ROOT / "stage_d/trades.parquet"
RESULT = OUTPUT_ROOT / "stage_d/result.json"
REPORT = REPO / (
    "research/market_behavior_os_v2/results/"
    "ASHARE-POST-LOW-FULL-FLOAT-TRANSFER-BASE-RESOLUTION-RULES-V1.md"
)
EXPECTED_HASHES = {
    SPEC: "09cef5d4bd575c8bb6d9a1bc15a35f50b08a471aa904244f67ab2859872d0dbf",
    CANDIDATES: "a681269172910f0b1fc05864c4cf8a53889cc3c5e591ceb9a169c102989a4338",
    PATHS: "97cbbe07fe78cb5ecbfdd947076e8eab22fd90685cba44b83a84d6973ef655e3",
}
ROUND_TRIP_COST = 0.004
HORIZON = 40
SIGNAL_YEARS = tuple(range(2015, 2021))


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or execution drift."""


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


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def _present(row: Any, names: tuple[str, ...]) -> bool:
    return not any(pd.isna(getattr(row, name)) for name in names)


def observable(row: Any) -> bool:
    required = (
        "trade_status",
        "current_day_data_tradable",
        "current_valid",
        "market_rule_valid",
        "corporate_action_count",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
        "coord_close",
        "invalid_step_cum",
    )
    return bool(
        _present(row, required)
        and int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.current_valid
        and row.market_rule_valid
        and int(row.corporate_action_count) == 0
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
        and np.isfinite(float(row.coord_close))
        and float(row.coord_close) > 0
    )


def legal_open(row: Any) -> bool:
    return bool(
        observable(row)
        and _present(row, ("open", "coord_open", "coordinate_factor"))
        and float(row.open) > 0
        and np.isfinite(float(row.coord_open))
        and float(row.coord_open) > 0
    )


def buyable(row: Any) -> bool:
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


def violent_rebound_warning(candidate: Any) -> bool:
    values = (
        candidate.market_median_ret20,
        candidate.market_median_ret60,
        candidate.market_positive_ret20_share,
        candidate.market_positive_ret60_share,
    )
    if any(pd.isna(value) or not np.isfinite(float(value)) for value in values):
        raise ResearchError(f"missing causal market state: {candidate.event_id}")
    return bool(
        float(candidate.market_median_ret20) > 0.08
        and float(candidate.market_median_ret60) < -0.08
        and float(candidate.market_positive_ret20_share) > 0.70
        and float(candidate.market_positive_ret60_share) < 0.35
    )


def _common(candidate: Any, warning: bool) -> dict[str, Any]:
    return {
        "event_id": str(candidate.event_id),
        "symbol": str(candidate.symbol),
        "sleeve": str(candidate.sleeve),
        "causal_industry": str(candidate.causal_industry),
        "anchor_date": pd.Timestamp(candidate.anchor_date),
        "anchor_idx": int(candidate.anchor_idx),
        "anchor_low": float(candidate.anchor_low),
        "base_ceiling": float(candidate.base_ceiling),
        "old_high_target": float(candidate.old_high),
        "signal_date": pd.Timestamp(candidate.signal_date),
        "signal_year": int(pd.Timestamp(candidate.signal_date).year),
        "signal_cal_idx": int(candidate.signal_cal_idx),
        "market_regime": str(candidate.market_regime),
        "market_median_ret20": float(candidate.market_median_ret20),
        "market_median_ret60": float(candidate.market_median_ret60),
        "market_positive_ret20_share": float(
            candidate.market_positive_ret20_share
        ),
        "market_positive_ret60_share": float(
            candidate.market_positive_ret60_share
        ),
        "violent_rebound_warning": warning,
        "turnover_before_signal": float(candidate.turnover_before_signal),
        "anchor_age_sessions": int(candidate.anchor_age_sessions),
        "target_headroom": float(candidate.target_headroom),
        "horizon_sessions": HORIZON,
    }


def replay_one(candidate: Any, path: pd.DataFrame) -> dict[str, Any]:
    warning = violent_rebound_warning(candidate)
    common = _common(candidate, warning)
    if warning:
        return {**common, "status": "MARKET_WARNING_VETO"}
    if path.empty:
        return {**common, "status": "NO_FUTURE_PATH"}
    lineage = float(candidate.invalid_step_cum)
    ceiling = float(candidate.base_ceiling)
    target = float(candidate.old_high)
    confirm_pool = path.loc[
        path.cal_idx.gt(candidate.signal_cal_idx)
        & path.cal_idx.le(candidate.signal_cal_idx + 3)
    ]
    confirmation = None
    for row in confirm_pool.itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {**common, "status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY"}
        if observable(row):
            confirmation = row
            break
    if confirmation is None:
        return {**common, "status": "NO_VALID_CONFIRMATION_SESSION"}
    confirmation_fields = {
        "confirmation_date": pd.Timestamp(confirmation.trade_date),
        "confirmation_cal_idx": int(confirmation.cal_idx),
        "confirmation_close": float(confirmation.coord_close),
        "confirmation_margin": float(confirmation.coord_close) / ceiling - 1,
    }
    if float(confirmation.coord_close) <= ceiling:
        return {**common, **confirmation_fields, "status": "CONFIRMATION_REJECTED"}
    if (
        np.isfinite(float(confirmation.coord_high))
        and float(confirmation.coord_high) >= target
    ):
        return {
            **common,
            **confirmation_fields,
            "status": "TARGET_REACHED_BEFORE_ENTRY",
        }
    entry_pool = path.loc[
        path.cal_idx.gt(confirmation.cal_idx)
        & path.cal_idx.le(confirmation.cal_idx + 3)
    ]
    entry = None
    for row in entry_pool.itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                **confirmation_fields,
                "status": "INVALID_COORDINATE_LINEAGE_BEFORE_ENTRY",
            }
        if buyable(row):
            if float(row.coord_open) >= target:
                return {
                    **common,
                    **confirmation_fields,
                    "status": "TARGET_REACHED_BEFORE_ENTRY",
                }
            entry = row
            break
        if (
            observable(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            return {
                **common,
                **confirmation_fields,
                "status": "TARGET_REACHED_BEFORE_ENTRY",
            }
    if entry is None:
        return {**common, **confirmation_fields, "status": "NO_LEGAL_ENTRY"}
    entry_idx = int(entry.cal_idx)
    entry_price = float(entry.coord_open)
    entry_fields = {
        "entry_date": pd.Timestamp(entry.trade_date),
        "entry_cal_idx": entry_idx,
        "entry_price": entry_price,
    }
    exit_instruction = (
        "BASE_CEILING_INVALIDATION"
        if observable(entry) and float(entry.coord_close) < ceiling
        else None
    )
    exit_row = None
    exit_price = math.nan
    exit_reason = None
    for row in path.loc[path.cal_idx.gt(entry_idx)].itertuples(index=False):
        if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
            return {
                **common,
                **confirmation_fields,
                **entry_fields,
                "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
            }
        if exit_instruction is None and int(row.cal_idx) >= entry_idx + HORIZON:
            exit_instruction = "H40_TIME_STOP"
        if exit_instruction is not None:
            if sellable_open(row):
                exit_row = row
                exit_price = float(row.coord_open)
                exit_reason = exit_instruction
                break
            continue
        if sellable_open(row) and float(row.coord_open) >= target:
            exit_row = row
            exit_price = float(row.coord_open)
            exit_reason = "OLD_HIGH_TARGET_GAP_OPEN"
            break
        if (
            observable(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            exit_row = row
            exit_price = target
            exit_reason = "OLD_HIGH_TARGET_INTRADAY"
            break
        if observable(row) and float(row.coord_close) < ceiling:
            exit_instruction = "BASE_CEILING_INVALIDATION"
    if exit_row is None:
        return {
            **common,
            **confirmation_fields,
            **entry_fields,
            "status": "INCOMPLETE_PATH",
            "pending_exit_instruction": exit_instruction,
        }
    gross = exit_price / entry_price - 1
    return {
        **common,
        **confirmation_fields,
        **entry_fields,
        "status": "COMPLETED",
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "holding_sessions": int(exit_row.cal_idx) - entry_idx,
        "gross_return": gross,
        "net_return": gross - ROUND_TRIP_COST,
    }


def summarize_group(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "completed": 0,
            "mean_net_return": None,
            "median_net_return": None,
            "positive_rate": None,
            "severe_loss_rate": None,
        }
    return {
        "completed": int(len(frame)),
        "mean_net_return": float(frame.net_return.mean()),
        "median_net_return": float(frame.net_return.median()),
        "positive_rate": float(frame.net_return.gt(0).mean()),
        "severe_loss_rate": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "target_rate": float(frame.exit_reason.str.startswith("OLD_HIGH").mean()),
        "invalidation_rate": float(
            frame.exit_reason.eq("BASE_CEILING_INVALIDATION").mean()
        ),
    }


def build_report(payload: dict[str, Any]) -> None:
    annual = payload["annual"]
    state = payload["market_regime"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Scientific status",
        "",
        "Data-generated visual-rule compression on consumed 2015-2020 development history. "
        "All 910 charts were reviewed before this specification was frozen. This is not independent confirmation.",
        "",
        "## Frozen simple strategy",
        "",
        "1. Find the frozen post-low full-float-transfer base and its first close above the base ceiling.",
        "2. Require the next valid completed session to remain above the ceiling; buy only at a later legal non-limit-up open.",
        "3. Do not enter the narrow causal violent-rebound-from-deep-damage state defined in the frozen spec.",
        "4. Take profit at the pre-anchor 60-session old high. If a completed close falls below the base ceiling, sell at the next legal non-limit-down open; otherwise time-stop after 40 held market sessions.",
        "",
        "All state fields are available at the signal close. No signal or confirmation bar fills itself.",
        "",
        "## Gate result",
        "",
        f"- Completed trades: {payload['completed_trades']}",
        f"- Pooled mean net: {payload['pooled']['mean_net_return']:.4%}",
        f"- Minimum annual completed trades: {payload['minimum_annual_completed']}",
        f"- Count gate: {payload['annual_count_gate']}",
        f"- Mean gate: {payload['pooled_mean_gate']}",
        f"- Open 2022-2024: {payload['open_2022_2024_authorized']}",
        "",
        "## Annual development anatomy",
        "",
        "| Year | N | Mean net | Median net | Positive | Severe loss |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year in SIGNAL_YEARS:
        row = annual[str(year)]
        lines.append(
            f"| {year} | {row['completed']} | {row['mean_net_return']:.3%} | "
            f"{row['median_net_return']:.3%} | {row['positive_rate']:.1%} | "
            f"{row['severe_loss_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Causal market-state context",
            "",
            "| State | N | Mean net | Median net | Positive | Severe loss |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for name in ("BULL", "BEAR", "TRANSITION"):
        row = state[name]
        lines.append(
            f"| {name} | {row['completed']} | {row['mean_net_return']:.3%} | "
            f"{row['median_net_return']:.3%} | {row['positive_rate']:.1%} | "
            f"{row['severe_loss_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- 2022-2024 signal/features/outcomes read: NO",
            "- CY-011 read: NO",
            "- Maximum path date: 2021-06-30",
            "- Threshold search after aggregation: NONE",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    candidates = pd.read_parquet(CANDIDATES)
    paths = pd.read_parquet(PATHS)
    for column in ("anchor_date", "signal_date"):
        candidates[column] = pd.to_datetime(candidates[column])
    paths["trade_date"] = pd.to_datetime(paths["trade_date"])
    if len(candidates) != 910 or candidates.event_id.duplicated().any():
        raise ResearchError("mother candidate identity drift")
    if candidates.signal_date.min() < pd.Timestamp("2015-01-01"):
        raise ResearchError("pre-2015 signal entered compressed-rule evaluation")
    if candidates.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered compressed-rule evaluation")
    if paths.trade_date.max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("outcome path crossed frozen date cap")
    path_groups = {key: part for key, part in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(candidate, path_groups.get(str(candidate.event_id), pd.DataFrame()))
        for candidate in candidates.itertuples(index=False)
    ]
    trades = pd.DataFrame(rows).sort_values(
        ["signal_date", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if len(trades) != 910 or trades.event_id.duplicated().any():
        raise ResearchError("compressed-rule event identity drift")
    completed = trades.loc[trades.status.eq("COMPLETED")].copy()
    if completed.empty:
        raise ResearchError("no completed trades")
    if completed.confirmation_date.le(completed.signal_date).any():
        raise ResearchError("confirmation is not strictly after signal")
    if completed.entry_date.le(completed.confirmation_date).any():
        raise ResearchError("entry is not strictly after confirmation")
    if completed.exit_date.le(completed.entry_date).any():
        raise ResearchError("exit violates T+1 ordering")
    write_parquet(trades, TRADES)
    annual = {
        str(year): summarize_group(completed.loc[completed.signal_year.eq(year)])
        for year in SIGNAL_YEARS
    }
    regimes = {
        name: summarize_group(completed.loc[completed.market_regime.eq(name)])
        for name in ("BULL", "BEAR", "TRANSITION")
    }
    pooled = summarize_group(completed)
    minimum_annual = min(row["completed"] for row in annual.values())
    count_gate = minimum_annual > 50
    mean_gate = bool(pooled["mean_net_return"] > 0.04)
    payload: dict[str, Any] = {
        "experiment": EXPERIMENT,
        "scientific_status": "DATA_GENERATED_VISUAL_RULE_COMPRESSION_DEVELOPMENT",
        "source_hashes": source_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "trades_sha256": sha256(TRADES),
        "mother_events": int(len(trades)),
        "status_counts": {
            str(key): int(value) for key, value in trades.status.value_counts().items()
        },
        "completed_trades": int(len(completed)),
        "violent_rebound_warning_events": int(trades.violent_rebound_warning.sum()),
        "pooled": pooled,
        "annual": annual,
        "market_regime": regimes,
        "minimum_annual_completed": int(minimum_annual),
        "annual_count_gate": bool(count_gate),
        "pooled_mean_gate": bool(mean_gate),
        "open_2022_2024_authorized": bool(count_gate and mean_gate),
        "maximum_signal_date": str(candidates.signal_date.max().date()),
        "maximum_outcome_path_date": str(paths.trade_date.max().date()),
        "2022_2024_signal_feature_or_outcome_read": "NO",
        "cy011_read": "NO",
        "future_function": False,
        "threshold_grid": "NONE",
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    build_report(payload)
    payload["report_sha256"] = sha256(REPORT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
