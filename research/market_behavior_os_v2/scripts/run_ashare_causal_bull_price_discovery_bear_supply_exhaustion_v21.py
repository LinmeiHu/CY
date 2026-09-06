#!/usr/bin/env python3
"""Evaluate the frozen pre-2021 causal BULL/BEAR mechanism union."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

EXPERIMENT = "ASHARE-CAUSAL-BULL-PRICE-DISCOVERY-BEAR-SUPPLY-EXHAUSTION-V21"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "cf82bc3df573497c0b9d8874cd67bf0af1842286a228277449a8b902ac160e27"

DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
BULL = (
    DATA_ROOT
    / "ashare_bull_distributed_accumulation_chart_rules_v3"
    / "development_2014_2020"
    / "outcomes.parquet"
)
BEAR_FAST = (
    DATA_ROOT
    / "ashare_causal_bear_bull_dual_engine_lane_specific_acceptance_v19r2"
    / "development_2014_2020_outcomes.parquet"
)
BEAR_SLOW = (
    DATA_ROOT
    / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
    / "development_2014_2020_outcomes.parquet"
)
EXPECTED_HASHES = {
    "bull": "362a995b40839849744ca33daaa9a8bb088e0e15fa13ac5626abf0d8359b2a1a",
    "bear_fast": "53d552de91a87b31eb3a81c16d5acd00a44e89c10e95fc31edcf71af7e2e60fe",
    "bear_slow": "8e410688aba5f07f1a36c87bd0e061c8d052fe6d2b051656b59970589320285d",
}

OUTPUT_ROOT = DATA_ROOT / "ashare_causal_bull_price_discovery_bear_supply_exhaustion_v21"
LEDGER = OUTPUT_ROOT / "development_2014_2020_union.parquet"
RESULT = OUTPUT_ROOT / "result.json"


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, routing, or chronology drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sources() -> dict[str, str]:
    paths = {
        "freeze": FREEZE,
        "bull": BULL,
        "bear_fast": BEAR_FAST,
        "bear_slow": BEAR_SLOW,
    }
    expected = {"freeze": EXPECTED_FREEZE_SHA256, **EXPECTED_HASHES}
    actual: dict[str, str] = {}
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
        FROM read_parquet('{BEAR_SLOW.as_posix()}') s
        JOIN read_parquet('{BEAR_FAST.as_posix()}') f
          ON s.symbol=f.symbol AND CAST(s.signal_date AS DATE)=CAST(f.signal_date AS DATE)
        WHERE s.mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
          AND s.market_regime='BEAR' AND s.status='COMPLETED'
          AND f.engine='BEAR_REPAIR' AND f.expected_market_regime='BEAR'
          AND f.status='COMPLETED'
        """
    ).fetchone()[0]
    union = con.execute(
        f"""
        WITH bull AS (
          SELECT 'BULL|' || event_id AS union_event_id,event_id AS source_event_id,
            symbol,sleeve,signal_date,signal_cal_idx,
            'BULL_PRICE_DISCOVERY' AS mechanism,'BULL' AS market_regime,
            confirmation_date,confirmation_cal_idx,entry_date,entry_cal_idx,entry_price,
            exit_date,exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,net_return,
            1 AS priority
          FROM read_parquet('{BULL.as_posix()}')
          WHERE status='COMPLETED'
            AND signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ), bear_fast AS (
          SELECT 'BEAR_FAST|' || chart_event_id AS union_event_id,
            chart_event_id AS source_event_id,symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_FAST_CAPITULATION_ACTIVE_DEMAND' AS mechanism,'BEAR' AS market_regime,
            confirmation_date,confirmation_cal_idx,entry_date,entry_cal_idx,entry_price,
            exit_date,exit_cal_idx,exit_price,exit_reason,holding_sessions,gross_return,net_return,
            2 AS priority
          FROM read_parquet('{BEAR_FAST.as_posix()}')
          WHERE status='COMPLETED' AND engine='BEAR_REPAIR'
            AND expected_market_regime='BEAR'
            AND signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ), bear_slow AS (
          SELECT 'BEAR_SLOW|' || event_id AS union_event_id,event_id AS source_event_id,
            symbol,sleeve,signal_date,signal_cal_idx,
            'BEAR_SLOW_SUPPLY_EXHAUSTION_TAKEOVER' AS mechanism,'BEAR' AS market_regime,
            CAST(NULL AS TIMESTAMP) AS confirmation_date,
            CAST(NULL AS DOUBLE) AS confirmation_cal_idx,
            entry_date,entry_cal_idx,entry_price,exit_date,exit_cal_idx,exit_price,exit_reason,
            holding_sessions,gross_return,net_return,3 AS priority
          FROM read_parquet('{BEAR_SLOW.as_posix()}')
          WHERE status='COMPLETED' AND mechanism='SLOW_SUPPLY_EXHAUSTION_TAKEOVER'
            AND market_regime='BEAR'
            AND signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ), stacked AS (
          SELECT * FROM bull
          UNION ALL SELECT * FROM bear_fast
          UNION ALL SELECT * FROM bear_slow
        ), chosen AS (
          SELECT *,ROW_NUMBER() OVER(
            PARTITION BY symbol,CAST(signal_date AS DATE)
            ORDER BY priority,union_event_id
          ) AS dedup_rank
          FROM stacked
        )
        SELECT * EXCLUDE(priority,dedup_rank)
        FROM chosen WHERE dedup_rank=1
        ORDER BY signal_date,symbol,union_event_id
        """
    ).fetch_df()
    con.close()
    for column in ("signal_date", "confirmation_date", "entry_date", "exit_date"):
        union[column] = pd.to_datetime(union[column])
    if union.union_event_id.duplicated().any():
        raise ResearchError("duplicate union event identity")
    if union.duplicated(["symbol", "signal_date"]).any():
        raise ResearchError("same-symbol same-date duplicate survived")
    if union.entry_cal_idx.le(union.signal_cal_idx).any():
        raise ResearchError("same/prior-session entry")
    if union.exit_cal_idx.le(union.entry_cal_idx).any():
        raise ResearchError("same/prior-session exit")
    if not union.loc[union.market_regime.eq("BULL"), "mechanism"].eq(
        "BULL_PRICE_DISCOVERY"
    ).all():
        raise ResearchError("invalid BULL route")
    if union.loc[union.market_regime.eq("BEAR"), "mechanism"].eq(
        "BULL_PRICE_DISCOVERY"
    ).any():
        raise ResearchError("BULL component leaked into BEAR")
    if union.market_regime.eq("TRANSITION").any():
        raise ResearchError("TRANSITION must remain cash")
    confirmed_bull = union.loc[union.mechanism.eq("BULL_PRICE_DISCOVERY")]
    if confirmed_bull.confirmation_cal_idx.isna().any():
        raise ResearchError("BULL confirmation missing")
    if confirmed_bull.entry_cal_idx.le(confirmed_bull.confirmation_cal_idx).any():
        raise ResearchError("BULL entered at/before confirmation")
    return union, int(overlap)


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    if values.isna().any():
        raise ResearchError("completed union contains null net return")
    return {
        "completed": len(frame),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": float(values.mean()) if len(frame) else None,
        "median_net": float(values.median()) if len(frame) else None,
        "positive_rate": float(values.gt(0).mean()) if len(frame) else None,
        "ge_4pct_rate": float(values.ge(0.04).mean()) if len(frame) else None,
        "severe10": float(values.le(-0.10).mean()) if len(frame) else None,
        "target_hit": (
            float(frame.exit_reason.str.startswith("TARGET_").mean()) if len(frame) else None
        ),
        "mean_holding_sessions": (
            float(frame.holding_sessions.mean()) if len(frame) else None
        ),
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
    annual_gate = {
        year: {
            "completed_gt_50": item["completed"] > 50,
            "mean_net_gt_4pct": item["mean_net"] is not None and item["mean_net"] > 0.04,
            "median_net_positive": (
                item["median_net"] is not None and item["median_net"] > 0
            ),
            "severe10_le_20pct": item["severe10"] is not None and item["severe10"] <= 0.20,
        }
        for year, item in annual.items()
    }
    gates = {
        "every_year_completed_gt_50": all(
            item["completed_gt_50"] for item in annual_gate.values()
        ),
        "every_year_mean_net_gt_4pct": all(
            item["mean_net_gt_4pct"] for item in annual_gate.values()
        ),
        "every_year_median_net_positive": all(
            item["median_net_positive"] for item in annual_gate.values()
        ),
        "every_year_severe10_le_20pct": all(
            item["severe10_le_20pct"] for item in annual_gate.values()
        ),
        "pooled_mean_net_gt_4pct": pooled["mean_net"] > 0.04,
    }
    all_gates_pass = all(gates.values())
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "CONSUMED_2014_2020_POST_HOC_MULTI_STATE_DEVELOPMENT_TEST",
        "source_hashes": source_hashes,
        "ledger_sha256": sha256(LEDGER),
        "runner_sha256": sha256(Path(__file__)),
        "exact_same_symbol_date_bear_overlap_removed": overlap,
        "pooled": pooled,
        "annual": annual,
        "by_mechanism": by_mechanism,
        "annual_gate": annual_gate,
        "gates": gates,
        "all_gates_pass": all_gates_pass,
        "future_market_function": False,
        "2021_signal_or_outcome_read": "NO",
        "2022_2024_signal_or_outcome_read": "NO",
        "post_2024_read": "NO",
        "verdict": (
            "LATER_PERIOD_IDENTITY_FREEZE_AUTHORIZED"
            if all_gates_pass
            else "STRICT_ANNUAL_GATE_FAIL_NO_LATER_PERIOD_READ"
        ),
    }
    write_json(RESULT, payload)
    payload["result_sha256"] = sha256(RESULT)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True, default=str))
