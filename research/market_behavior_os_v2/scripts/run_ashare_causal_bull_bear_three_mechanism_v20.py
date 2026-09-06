#!/usr/bin/env python3
"""Reproduce the frozen pre-2021 causal dual-state three-mechanism candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

EXPERIMENT = "ASHARE-CAUSAL-BULL-BEAR-THREE-MECHANISM-V20"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "8003a906224d1c9d03d422d1aefe9bd39bedbbce63a0bd3fb04bae51bfc2f700"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
V19 = (
    DATA_ROOT
    / "ashare_causal_bear_bull_dual_engine_lane_specific_acceptance_v19r2"
    / "development_2014_2020_outcomes.parquet"
)
SLOW = (
    DATA_ROOT
    / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
    / "development_2014_2020_outcomes.parquet"
)
EXPECTED_HASHES = {
    "v19r2": "53d552de91a87b31eb3a81c16d5acd00a44e89c10e95fc31edcf71af7e2e60fe",
    "slow": "8e410688aba5f07f1a36c87bd0e061c8d052fe6d2b051656b59970589320285d",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_causal_bull_bear_three_mechanism_v20"
LEDGER = OUTPUT_ROOT / "development_2014_2020_union.parquet"
RESULT = OUTPUT_ROOT / "result.json"


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, union semantics, or chronology."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sources() -> dict[str, str]:
    paths = {"freeze": FREEZE, "v19r2": V19, "slow": SLOW}
    expected = {"freeze": EXPECTED_FREEZE_SHA256, **EXPECTED_HASHES}
    actual = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen source: {path}")
        actual[name] = sha256(path)
        if actual[name] != expected[name]:
            raise ResearchError(f"{name} identity drift: {actual[name]} != {expected[name]}")
    return actual


def build_union() -> tuple[pd.DataFrame, int]:
    con = duckdb.connect()
    overlap = con.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet('{SLOW.as_posix()}') s
        JOIN read_parquet('{V19.as_posix()}') v
          ON s.symbol=v.symbol AND CAST(s.signal_date AS DATE)=CAST(v.signal_date AS DATE)
        WHERE s.mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
          AND s.market_regime='BEAR' AND s.status='COMPLETED'
          AND v.status='COMPLETED'
        """
    ).fetchone()[0]
    union = con.execute(
        f"""
        WITH v19 AS (
          SELECT chart_event_id AS event_id,symbol,sleeve,signal_date,signal_cal_idx,
            CASE WHEN engine='BULL_CONTINUATION' THEN
              'BULL_QUIET_INVENTORY_CONTINUATION'
            ELSE 'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' END AS mechanism,
            expected_market_regime AS market_regime,entry_date,entry_cal_idx,entry_price,
            exit_date,exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,net_return,
            1 AS priority
          FROM read_parquet('{V19.as_posix()}')
          WHERE status='COMPLETED'
            AND signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ), slow AS (
          SELECT event_id,symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,
            market_regime,entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,
            exit_price,exit_reason,holding_sessions,gross_return,net_return,2 AS priority
          FROM read_parquet('{SLOW.as_posix()}')
          WHERE mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
            AND market_regime='BEAR' AND status='COMPLETED'
            AND signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ), stacked AS (
          SELECT * FROM v19 UNION ALL SELECT * FROM slow
        ), chosen AS (
          SELECT *,ROW_NUMBER() OVER(
            PARTITION BY symbol,CAST(signal_date AS DATE)
            ORDER BY priority,event_id
          ) AS dedup_rank
          FROM stacked
        )
        SELECT * EXCLUDE(priority,dedup_rank)
        FROM chosen
        WHERE dedup_rank=1
        ORDER BY signal_date,symbol,event_id
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "entry_date", "exit_date"):
        union[column] = pd.to_datetime(union[column])
    if union.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    if union.duplicated(["symbol", "signal_date"]).any():
        raise ResearchError("same-symbol same-date union duplicate")
    if union.entry_cal_idx.le(union.signal_cal_idx).any():
        raise ResearchError("same/prior-session entry")
    if union.exit_cal_idx.le(union.entry_cal_idx).any():
        raise ResearchError("same/prior-session exit")
    if not union.loc[union.market_regime.eq("BULL"), "mechanism"].eq(
        "BULL_QUIET_INVENTORY_CONTINUATION"
    ).all():
        raise ResearchError("invalid BULL route")
    if union.loc[union.market_regime.eq("TRANSITION")].shape[0]:
        raise ResearchError("TRANSITION must remain cash")
    return union, int(overlap)


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    return {
        "completed": len(frame),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": float(values.mean()),
        "median_net": float(values.median()),
        "win_rate": float(values.gt(0).mean()),
        "ge_4pct_rate": float(values.ge(0.04).mean()),
        "severe10": float(values.le(-0.10).mean()),
        "target_hit": float(frame.exit_reason.str.startswith("TARGET_").mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
    }


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.close()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, Any]:
    source_hashes = verify_sources()
    union, overlap = build_union()
    write_parquet(union, LEDGER)
    pooled = metrics(union)
    annual = {
        str(year): metrics(union.loc[union.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    by_mechanism = {
        str(name): metrics(part) for name, part in union.groupby("mechanism", sort=True)
    }
    gates = {
        "completed_gt_50_each_year": all(item["completed"] > 50 for item in annual.values()),
        "pooled_mean_net_gt_4pct": pooled["mean_net"] > 0.04,
        "pooled_median_positive": pooled["median_net"] > 0,
        "severe10_le_20pct": pooled["severe10"] <= 0.20,
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_RETROSPECTIVE_DEVELOPMENT_CANDIDATE",
        "source_hashes": source_hashes,
        "ledger_sha256": sha256(LEDGER),
        "runner_sha256": sha256(Path(__file__)),
        "exact_same_symbol_date_overlap_removed": overlap,
        "pooled": pooled,
        "annual": annual,
        "by_mechanism": by_mechanism,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "future_market_function": False,
        "2021_signal_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "verdict": (
            "LATER_PERIOD_REPLAY_AUTHORIZED"
            if all(gates.values())
            else "CANDIDATE_FAILS_GATE"
        ),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
