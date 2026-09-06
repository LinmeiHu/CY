#!/usr/bin/env python3
"""Run the single authorized development aggregation for the frozen corridor rule."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-INDUSTRY-NEUTRAL-SIZE-EVENT-CORRIDOR-ACCEPTANCE-V1"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
MOTHER_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_neutral_circulating_size_extremes_mother_v1"
)
PATHS = MOTHER_ROOT / "stage_b/future_paths_through_2021h1.parquet"
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_industry_neutral_size_event_corridor_acceptance_v1"
)
STAGE_1_MANIFEST = OUTPUT_ROOT / "stage_1/breadth_gate_manifest.json"
SELECTIONS = OUTPUT_ROOT / "stage_1/selection_ledger_without_returns.parquet"
STAGE_2_ROOT = OUTPUT_ROOT / "stage_2"
TRADE_LEDGER = STAGE_2_ROOT / "trade_ledger.parquet"
RESULT = STAGE_2_ROOT / "result.json"
ROUND_TRIP_COST = 0.004
EXPECTED_HASHES = {
    SPEC: "52cd905e371b518d92097ae360c0e62f5c6b07edeb506dd57766d6a4df74fe76",
    PATHS: "3cd09c1cf6d9f026ea60f98b9b9e94631abf7fad034c21526e16b3db4c257137",
    STAGE_1_MANIFEST: "f3295db9047d92adb845c7ea560af522768ccb4084363315a028139d956888e2",
    SELECTIONS: "28edc65aa09834132aebd76771e7f62e2b4ec76c2b9b487ce608b75016043964",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen identity or unauthorized validation access."""


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
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    manifest = json.loads(STAGE_1_MANIFEST.read_text(encoding="utf-8"))
    if not manifest.get("breadth_gate_pass"):
        raise ResearchError("stage-1 breadth gate did not authorize aggregation")
    if manifest.get("annual_or_pooled_return_aggregate_produced"):
        raise ResearchError("stage-1 manifest unexpectedly contains return aggregation")
    if manifest.get("validation_2022_2024_outcome_read"):
        raise ResearchError("validation quarantine already violated")
    return actual


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def summarize(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "n": int(len(frame)),
        "mean_net_return": float(frame.net_return.mean()),
        "median_net_return": float(frame.net_return.median()),
        "positive_rate": float(frame.net_return.gt(0).mean()),
        "profit_ge_4pct_rate": float(frame.net_return.ge(0.04).mean()),
        "severe_loss_le_minus_10pct_rate": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_market_sessions": float(frame.holding_market_sessions.mean()),
        "median_holding_market_sessions": float(frame.holding_market_sessions.median()),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    selections = pd.read_parquet(SELECTIONS)
    completed = selections.loc[selections.status.eq("COMPLETED")].copy()
    if completed.empty or completed.signal_year.gt(2020).any():
        raise ResearchError("completed development selection set is invalid")
    paths = pd.read_parquet(PATHS, columns=["event_id", "cal_idx", "trade_date", "coord_open"])
    if pd.to_datetime(paths.trade_date).max() > pd.Timestamp("2021-06-30"):
        raise ResearchError("context crossed the frozen 2021H1 cap")
    entry_prices = paths.rename(
        columns={"cal_idx": "entry_cal_idx", "trade_date": "entry_price_date", "coord_open": "entry_price"}
    )[["event_id", "entry_cal_idx", "entry_price_date", "entry_price"]]
    exit_prices = paths.rename(
        columns={"cal_idx": "exit_cal_idx", "trade_date": "exit_price_date", "coord_open": "exit_price"}
    )[["event_id", "exit_cal_idx", "exit_price_date", "exit_price"]]
    ledger = completed.merge(
        entry_prices,
        on=["event_id", "entry_cal_idx"],
        how="left",
        validate="one_to_one",
    ).merge(
        exit_prices,
        on=["event_id", "exit_cal_idx"],
        how="left",
        validate="one_to_one",
    )
    if ledger[["entry_price", "exit_price"]].isna().any().any():
        raise ResearchError("entry or exit coordinate price is missing")
    if (ledger[["entry_price", "exit_price"]] <= 0).any().any():
        raise ResearchError("entry or exit coordinate price is non-positive")
    if not (
        pd.to_datetime(ledger.entry_price_date).eq(pd.to_datetime(ledger.entry_date)).all()
        and pd.to_datetime(ledger.exit_price_date).eq(pd.to_datetime(ledger.exit_date)).all()
    ):
        raise ResearchError("entry/exit date alignment drift")
    ledger["gross_return"] = ledger.exit_price / ledger.entry_price - 1.0
    ledger["net_return"] = ledger.gross_return - ROUND_TRIP_COST
    if not np.isfinite(ledger[["gross_return", "net_return"]].to_numpy(dtype=float)).all():
        raise ResearchError("non-finite return")
    write_parquet(ledger, TRADE_LEDGER)

    annual = {
        str(year): summarize(ledger.loc[ledger.signal_year.eq(year)])
        for year in (2018, 2019, 2020)
    }
    for year, values in annual.items():
        values["breadth_pass"] = bool(values["n"] > 50)
        values["mean_gate_pass"] = bool(values["mean_net_return"] > 0.04)
        values["median_gate_pass"] = bool(values["median_net_return"] > 0.0)
        values["full_year_gate_pass"] = bool(
            values["breadth_pass"] and values["mean_gate_pass"] and values["median_gate_pass"]
        )
    all_development_gates_pass = all(
        values["full_year_gate_pass"] for values in annual.values()
    )
    result = {
        "experiment": EXPERIMENT,
        "research_status": "ONE_SHOT_DEVELOPMENT_RESULT",
        "source_hashes": source_hashes,
        "script_sha256": sha256(Path(__file__)),
        "trade_ledger": str(TRADE_LEDGER),
        "trade_ledger_sha256": sha256(TRADE_LEDGER),
        "annual": annual,
        "pooled": summarize(ledger),
        "by_size_lane": {
            str(lane): summarize(part)
            for lane, part in ledger.groupby("size_lane", sort=True)
        },
        "by_exit_reason": {
            str(reason): summarize(part)
            for reason, part in ledger.groupby("exit_reason", sort=True)
        },
        "all_development_gates_pass": bool(all_development_gates_pass),
        "validation_2022_2024_authorized": bool(all_development_gates_pass),
        "validation_2022_2024_outcome_read": False,
        "post_2021_signal_identity_read": False,
        "maximum_context_date": "2021-06-30",
        "no_parameter_rescue": True,
        "classification": (
            "DEVELOPMENT_GATE_PASS_VALIDATION_AUTHORIZED"
            if all_development_gates_pass
            else "DEVELOPMENT_GATE_FAIL_EXACT_RULE_CLOSED"
        ),
    }
    write_json(RESULT, result)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
