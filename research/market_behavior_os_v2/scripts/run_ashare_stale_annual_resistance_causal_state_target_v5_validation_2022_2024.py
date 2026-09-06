#!/usr/bin/env python3
"""Two-stage frozen validation of stale-resistance causal-state targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_quiet_inventory_fast_repricing_v1 as qfast  # noqa: E402
import run_ashare_stale_annual_resistance_causal_state_target_v5 as v5  # noqa: E402


EXPERIMENT = "ASHARE-STALE-ANNUAL-RESISTANCE-CAUSAL-STATE-TARGET-V5-VALIDATION-2022-2024"
REPO = Path(__file__).resolve().parents[3]
CONTRACT = REPO / (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-STALE-ANNUAL-RESISTANCE-CAUSAL-STATE-TARGET-V5_validation_2022_2024_contract.json"
)
EXPECTED_CONTRACT_SHA256 = "31997594588f11345b91ca929b8f440f25d6eab51783198ff6b4875dc3d72216"
V5_FREEZE = v5.FREEZE
V5_RESULT = (
    v5.v4.DATA_ROOT
    / "ashare_stale_annual_resistance_causal_state_target_v5"
    / "development_2014_2020/result.json"
)
FROZEN_CANDIDATES = v5.v4.CANDIDATES
FROZEN_REGIME = v5.v4.REGIME
DAILY = qfast.DAILY
OUTPUT_ROOT = (
    v5.v4.DATA_ROOT
    / "ashare_stale_annual_resistance_causal_state_target_v5"
    / "validation_2022_2024"
)
MARKET = OUTPUT_ROOT / "stage_a/causal_market_state_2022_2024.parquet"
CANDIDATES = OUTPUT_ROOT / "stage_a/frozen_validation_candidates.parquet"
STAGE_A_FREEZE = OUTPUT_ROOT / "stage_a/stage_a_freeze.json"
OUTCOMES = OUTPUT_ROOT / "stage_b/validation_outcomes.parquet"
ANNUAL = OUTPUT_ROOT / "stage_b/annual_metrics.csv"
RESULT = OUTPUT_ROOT / "stage_b/result.json"

EXPECTED_STATIC_HASHES = {
    "contract": EXPECTED_CONTRACT_SHA256,
    "v5_freeze": "f2ee17f59d37d4204cfee0518924a98588dfc6578fd82010c912b18ff7f5df1c",
    "v5_result": "c5197fc4f167167297a7657a520908a4d79d51e0ec76e7760e6c23ac19206bbf",
    "frozen_candidates": "4518bd47845d068d36f85016786d3743276364410a5bec6c434f10c82b27e455",
    "frozen_regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "daily": "95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
    "qfast_runner": "42be0aed77c63197320b127b483bd7bb0b9518c8dc999405be80ab1b84d45da5",
}
EXPECTED_2023_FROZEN_ONLY = {
    "300294.SZ|2023-04-13",
    "002857.SZ|2023-04-18",
}


class ValidationError(RuntimeError):
    """Fail closed on identity, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_static_inputs() -> dict[str, str]:
    paths = {
        "contract": CONTRACT,
        "v5_freeze": V5_FREEZE,
        "v5_result": V5_RESULT,
        "frozen_candidates": FROZEN_CANDIDATES,
        "frozen_regime": FROZEN_REGIME,
        "daily": DAILY,
        "qfast_runner": Path(qfast.__file__),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise ValidationError(f"missing frozen input: {missing}")
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": EXPECTED_STATIC_HASHES[name], "actual": value}
        for name, value in actual.items()
        if EXPECTED_STATIC_HASHES[name] != value
    }
    if drift:
        raise ValidationError(f"static input identity drift: {drift}")
    return actual


def stale_candidate_query() -> str:
    excluded = qfast.quoted_industries()
    return f"""
    WITH source AS (
      SELECT * FROM read_parquet('{DAILY.as_posix()}')
      WHERE trade_date BETWEEN DATE '2022-01-04' AND DATE '2024-12-31'
        AND sleeve IN ('MAIN','CHINEXT')
        AND causal_industry NOT IN ({excluded})
    ), windows AS (
      SELECT *,
        lag(cal_idx) OVER sy AS prior_cal_idx_x,
        lag(invalid_step_cum) OVER sy AS prior_invalid_step_x,
        max(CASE WHEN current_valid THEN coord_high END) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING
        ) AS prior250_peak_high_x,
        arg_max(CASE WHEN current_valid THEN trade_date END,
                CASE WHEN current_valid THEN coord_high END) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING
        ) AS prior250_peak_date_x,
        arg_max(CASE WHEN current_valid THEN cal_idx END,
                CASE WHEN current_valid THEN coord_high END) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING
        ) AS prior_peak_cal_idx_x,
        arg_max(CASE WHEN current_valid THEN invalid_step_cum END,
                CASE WHEN current_valid THEN coord_high END) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING
        ) AS prior_peak_invalid_step_x,
        avg(CASE WHEN current_valid THEN turnover_fraction END) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_mean_turnover_x,
        count(*) OVER(
          PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_n_x
      FROM source
      WINDOW sy AS (PARTITION BY symbol ORDER BY trade_date)
    ), featured AS (
      SELECT *,
        coord_close/nullif(prior_coord_close,0)-1 AS step_return_x,
        (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS close_location_x,
        coord_close/nullif(prior250_peak_high_x,0)-1 AS peak_overshoot_x,
        turnover_fraction/nullif(prior20_mean_turnover_x,0) AS turnover_expansion_x,
        cal_idx-prior_peak_cal_idx_x AS peak_age_sessions_x
      FROM windows
    )
    SELECT symbol,sleeve,industry,causal_industry,CAST(trade_date AS DATE) AS signal_date,
      cal_idx,invalid_step_cum,prior250_peak_high_x AS prior250_peak_high,
      CAST(prior250_peak_date_x AS DATE) AS prior250_peak_date,
      prior_peak_cal_idx_x AS prior_peak_cal_idx,peak_age_sessions_x AS peak_age_sessions,
      peak_overshoot_x AS peak_overshoot,
      prior20_mean_turnover_x AS prior20_mean_turnover,
      turnover_expansion_x AS turnover_expansion,
      coord_open,coord_high,coord_low,coord_close,step_return_x AS step_return,
      close_location_x AS close_location,prior250_peak_high_x AS stabilized_low_coord,
      available_at,decision_at
    FROM featured
    WHERE year(trade_date) IN (2023,2024)
      AND hard_valid AND history_valid AND current_valid AND current_day_data_tradable
      AND market_rule_valid AND corporate_action_valid AND NOT corporate_action_blocking
      AND historical_identity_valid AND NOT is_st
      AND prior20_n_x=20 AND prior_cal_idx_x=cal_idx-1
      AND prior_invalid_step_x=invalid_step_cum
      AND prior_peak_invalid_step_x=invalid_step_cum
      AND peak_age_sessions_x>=60
      AND peak_overshoot_x>0 AND peak_overshoot_x<=0.05
      AND step_return_x BETWEEN 0.02 AND 0.095
      AND turnover_expansion_x>=1.50
      AND close_location_x>=0.75-1e-12
      AND round(close*100)<round(up_limit_price*100)
    ORDER BY symbol,cal_idx
    """


def greedy_cooldown(raw: pd.DataFrame, seed: pd.DataFrame | None = None) -> pd.DataFrame:
    seed_last = {} if seed is None else seed.groupby("symbol").cal_idx.max().astype(int).to_dict()
    keep: list[int] = []
    for symbol, part in raw.groupby("symbol", sort=False):
        last = int(seed_last.get(symbol, -10**12))
        for index, row in part.sort_values("cal_idx", kind="mergesort").iterrows():
            if int(row.cal_idx) - last > 60:
                keep.append(index)
                last = int(row.cal_idx)
    return raw.loc[keep].sort_values(["signal_date", "symbol"], kind="mergesort").reset_index(drop=True)


def candidate_key(frame: pd.DataFrame) -> set[str]:
    return set(frame.symbol.astype(str) + "|" + pd.to_datetime(frame.signal_date).dt.strftime("%Y-%m-%d"))


def build_stage_a() -> dict[str, Any]:
    static_hashes = verify_static_inputs()
    connection = duckdb.connect()
    connection.execute("SET threads=8")
    frozen = connection.execute(
        f"""
        SELECT * FROM read_parquet('{FROZEN_CANDIDATES.as_posix()}')
        WHERE year(signal_date) IN (2022,2023)
        ORDER BY signal_date,sleeve,symbol,event_id
        """
    ).fetch_df()
    raw = connection.execute(stale_candidate_query()).fetch_df()
    market_2024 = qfast.build_2024_market(connection)
    market_old = connection.execute(
        f"""
        SELECT * FROM read_parquet('{FROZEN_REGIME.as_posix()}')
        WHERE year(trade_date) IN (2022,2023)
        ORDER BY trade_date
        """
    ).fetch_df()
    connection.close()
    for column in ("signal_date", "available_at", "decision_at", "prior250_peak_date"):
        raw[column] = pd.to_datetime(raw[column])
        frozen[column] = pd.to_datetime(frozen[column])
    market_old["trade_date"] = pd.to_datetime(market_old.trade_date)
    market_2024["trade_date"] = pd.to_datetime(market_2024.trade_date)

    rebuilt_2023 = greedy_cooldown(raw.loc[raw.signal_date.dt.year.eq(2023)].copy())
    frozen_2023 = frozen.loc[frozen.signal_date.dt.year.eq(2023)].copy()
    frozen_only = candidate_key(frozen_2023) - candidate_key(rebuilt_2023)
    rebuilt_only = candidate_key(rebuilt_2023) - candidate_key(frozen_2023)
    if rebuilt_only or frozen_only != EXPECTED_2023_FROZEN_ONLY:
        raise ValidationError(
            f"2023 identity reproduction drift: frozen_only={sorted(frozen_only)}, "
            f"rebuilt_only={sorted(rebuilt_only)}"
        )

    seed = frozen_2023[["symbol", "cal_idx"]]
    rebuilt_2024 = greedy_cooldown(raw.loc[raw.signal_date.dt.year.eq(2024)].copy(), seed)
    rebuilt_2024["event_id"] = (
        rebuilt_2024.symbol.astype(str)
        + "|"
        + rebuilt_2024.signal_date.dt.strftime("%Y-%m-%d")
        + "|SAR1"
    )
    combined = pd.concat([frozen, rebuilt_2024[frozen.columns]], ignore_index=True)
    market = pd.concat([market_old, market_2024[market_old.columns]], ignore_index=True)
    combined = combined.merge(
        market[["trade_date", "market_regime", "latest_source_timestamp"]],
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    combined = combined.rename(columns={"latest_source_timestamp": "market_latest_source_timestamp"})
    for column in ("signal_date", "available_at", "decision_at", "market_latest_source_timestamp"):
        combined[column] = pd.to_datetime(combined[column])
    if combined.event_id.duplicated().any():
        raise ValidationError("duplicate validation event identity")
    if combined.available_at.gt(combined.decision_at).any():
        raise ValidationError("candidate information later than decision_at")
    if combined.market_latest_source_timestamp.gt(combined.decision_at).any():
        raise ValidationError("market state information later than candidate decision_at")
    if not combined.market_regime.isin(["BULL", "BEAR", "TRANSITION"]).all():
        raise ValidationError("missing causal market state")
    annual = combined.groupby(combined.signal_date.dt.year).size().to_dict()
    if set(annual) != {2022, 2023, 2024} or any(value <= 50 for value in annual.values()):
        raise ValidationError(f"validation signal-count gate failed before outcomes: {annual}")

    v5.v4.write_parquet(market, MARKET)
    v5.v4.write_parquet(combined, CANDIDATES)
    stage_a = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_IDENTITY_FREEZE",
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "static_hashes": static_hashes,
        "annual_signal_counts": {str(key): int(value) for key, value in annual.items()},
        "2023_reproduction_audit": {
            "frozen": int(len(frozen_2023)),
            "rebuilt": int(len(rebuilt_2023)),
            "frozen_only_exact_coordinate_equality_rows": sorted(frozen_only),
            "rebuilt_only": sorted(rebuilt_only),
            "interpretation": (
                "The newer exact coordinate materialization represents two prior-high equality rows as "
                "exact zero overshoot; the frozen source retained positive floating-point epsilon. "
                "No new row is introduced by the rebuilt definition."
            ),
        },
        "market_state_source_after_decision_count": int(
            combined.market_latest_source_timestamp.gt(combined.decision_at).sum()
        ),
        "candidate_sha256": sha256(CANDIDATES),
        "market_sha256": sha256(MARKET),
        "outcome_columns_read": [],
        "2024_future_return_or_exit_read": False,
    }
    v5.v4.write_json(STAGE_A_FREEZE, stage_a)
    return stage_a


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise ValidationError("missing Stage-A identity freeze")
    stage_a = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "market_sha256": sha256(MARKET),
    }
    drift = {
        key: {"frozen": stage_a.get(key), "current": value}
        for key, value in current.items()
        if stage_a.get(key) != value
    }
    if drift:
        raise ValidationError(f"Stage-A identity drift: {drift}")
    verify_static_inputs()
    return stage_a


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    connection = duckdb.connect()
    candidates = connection.execute(
        f"SELECT * FROM read_parquet('{CANDIDATES.as_posix()}') ORDER BY signal_date,sleeve,symbol,event_id"
    ).fetch_df()
    connection.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "cal_idx"]].rename(columns={"cal_idx": "signal_cal_idx"}),
    )
    paths = connection.execute(
        f"""
        SELECT c.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.trade_status,d.current_day_data_tradable,
          d.current_valid,d.market_rule_valid,d.corporate_action_valid,
          d.corporate_action_blocking,d.hard_valid,d.up_limit_price,d.down_limit_price,
          d.available_at,d.decision_at
        FROM candidate_ids c
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.signal_cal_idx
        WHERE d.trade_date<=DATE '2025-03-31'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    for column in ("signal_date", "available_at", "decision_at", "market_latest_source_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    for column in ("trade_date", "available_at", "decision_at"):
        paths[column] = pd.to_datetime(paths[column])
    if paths.available_at.dt.date.gt(paths.trade_date.dt.date).any():
        raise ValidationError("execution row unavailable on its trade date")
    outcomes = v5.replay(candidates, paths)
    v5.v4.write_parquet(outcomes, OUTCOMES)

    annual_rows: list[dict[str, Any]] = []
    for year, part in outcomes.groupby("signal_year", sort=True):
        annual_rows.append({"year": int(year), **v5.v4.metrics(part)})
    annual = pd.DataFrame(annual_rows)
    ANNUAL.parent.mkdir(parents=True, exist_ok=True)
    annual.to_csv(ANNUAL, index=False, float_format="%.10g")
    pooled = v5.v4.metrics(outcomes)
    by_state = {
        state: v5.v4.metrics(part)
        for state, part in outcomes.groupby("market_regime", sort=True)
    }
    count_gate = bool(annual.signals.gt(50).all())
    mean_gate = bool(float(pooled["mean_net"]) > 0.04)
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "FROZEN_2022_2024_VALIDATION_NO_RETUNING",
        "contract_sha256": sha256(CONTRACT),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a": stage_a,
        "pooled": pooled,
        "annual": annual.to_dict("records"),
        "by_signal_market_state": by_state,
        "validation_gate": {
            "each_2022_2024_year_signal_count_gt_50": count_gate,
            "pooled_completed_mean_net_gt_4pct": mean_gate,
            "pass": count_gate and mean_gate,
            "individual_years_mean_net_gt_4pct": {
                str(int(row.year)): bool(float(row.mean_net) > 0.04)
                for row in annual.itertuples(index=False)
            },
        },
        "causality_audit": {
            "market_state_source_after_decision_count": int(
                candidates.market_latest_source_timestamp.gt(candidates.decision_at).sum()
            ),
            "max_signal_date": str(candidates.signal_date.max().date()),
            "max_execution_source_date": str(paths.trade_date.max().date()),
            "same_bar_entry_count": int(
                outcomes.loc[outcomes.entry_date.notna(), "entry_date"].dt.date.le(
                    outcomes.loc[outcomes.entry_date.notna(), "signal_date"].dt.date
                ).sum()
            ),
        },
        "outcomes_sha256": sha256(OUTCOMES),
        "annual_sha256": sha256(ANNUAL),
    }
    v5.v4.write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("a", "b"), required=True)
    parser.add_argument("--print-result", action="store_true")
    args = parser.parse_args()
    result = build_stage_a() if args.stage == "a" else run_stage_b()
    if args.print_result:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
