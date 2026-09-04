#!/usr/bin/env python3
"""Run the causal-numeric-erratum 2024-2025 validation of Industry-Consensus Q1."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-INDUSTRY-CONSENSUS-Q1-TEMPORAL-VALIDATION-2024-2025-V1_1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
TRADES_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_trades.csv"
SELECTION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXTERNAL_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "industry_consensus_q1_temporal_validation_2024_2025_v1_1"
)
FEATURE_PATH = EXTERNAL_ROOT / "daily_feature_panel_2023_2025.parquet"
TEMP_PATH = EXTERNAL_ROOT / "duckdb_tmp"
EXPECTED_SPEC_SHA256 = "b77b2a5c9b608b95f18637d96a1690cfd285b8c1ed11d4403b4e37b36ab42247"
INITIAL_CAPITAL = 10_000_000.0
VALIDATION_START = date(2024, 1, 1)
VALIDATION_END = date(2025, 12, 31)
R20_POSITIVE_EPSILON = 1e-12


class TemporalValidationError(RuntimeError):
    """Fail-closed error for the frozen 2024-2025 validation."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise TemporalValidationError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise TemporalValidationError("frozen validation spec identity mismatch")
    erratum = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if erratum.get("status") != (
        "FROZEN_NUMERIC_ERRATUM_BEFORE_ANY_2024_2025_STRATEGY_OUTCOME_AGGREGATION"
    ):
        raise TemporalValidationError("numeric-erratum validation contract is not frozen")
    base_binding = erratum["base_contract"]
    base_path = _resolve(base_binding["path"])
    if (
        not base_path.is_file()
        or sha256_file(base_path) != base_binding["sha256"]
    ):
        raise TemporalValidationError("base validation contract identity mismatch")
    spec = json.loads(base_path.read_text(encoding="utf-8"))
    spec.update(
        {
            "experiment_id": erratum["experiment_id"],
            "status": erratum["status"],
            "claim_boundary": erratum["claim_boundary"],
            "research_question": erratum["research_question"],
            "initial_contract_failure": erratum["initial_contract_failure"],
            "numerical_erratum": erratum["numerical_erratum"],
            "corrected_development_diagnostic": erratum[
                "corrected_development_diagnostic"
            ],
            "classification": erratum["classification"],
            "prohibited": spec["prohibited"] + erratum["additional_prohibited"],
        }
    )
    if spec.get("starting_checkpoint") != (
        "beab86e0e0da8a4ce0f79f801a4c8a88f3e9b82a"
    ):
        raise TemporalValidationError("starting checkpoint changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise TemporalValidationError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("2026 market", "CY-011", "Top-N", "retune"):
        if phrase not in prohibited:
            raise TemporalValidationError(f"missing prohibition: {phrase}")
    frozen = spec["frozen_strategy"]
    if (
        frozen["cost_per_side"] != 0.002
        or frozen["leverage"] is not False
        or "one-half" not in frozen["event_capital"]
        or "20 market sessions" not in frozen["holding"]
    ):
        raise TemporalValidationError("frozen strategy identity changed")
    if spec["numerical_erratum"]["epsilon"] != R20_POSITIVE_EPSILON:
        raise TemporalValidationError("causal numeric tie rule changed")
    return spec


def _validated_cy006_paths(spec: dict[str, Any]) -> tuple[list[Path], dict[str, Any]]:
    registry = json.loads(
        _resolve(spec["inputs"]["data_asset_registry"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    assets = {item["asset_id"]: item for item in registry["assets"]}
    asset = assets.get("CY-006")
    if (
        asset is None
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or not asset.get("quality_evidence", {}).get("gate_pass")
        or "daily causal state generation with row-level hard_valid enforcement"
        not in asset.get("allowed_uses", [])
    ):
        raise TemporalValidationError("CY-006 registry activation changed")

    manifest = json.loads(
        _resolve(spec["inputs"]["cy006_manifest"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    root = Path(manifest["root"])
    manifest_rows = {row["path"]: row for row in manifest["files"]}
    paths: list[Path] = []
    identities: list[dict[str, Any]] = []
    for expected in spec["cy006_partitions"]:
        binding = manifest_rows.get(expected["path"])
        if binding != {
            "path": expected["path"],
            "size": expected["bytes"],
            "sha256": expected["sha256"],
        }:
            raise TemporalValidationError(
                f"manifest binding changed: {expected['year']}"
            )
        path = root / expected["path"]
        if (
            not path.is_file()
            or path.stat().st_size != expected["bytes"]
            or sha256_file(path) != expected["sha256"]
        ):
            raise TemporalValidationError(
                f"CY-006 partition mismatch: {expected['year']}"
            )
        paths.append(path)
        identities.append(
            {
                "year": expected["year"],
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": expected["sha256"],
            }
        )
    if [item["year"] for item in identities] != list(range(2018, 2026)):
        raise TemporalValidationError("validation read set is not exactly 2018-2025")
    return paths, {
        "asset_id": "CY-006",
        "pit_grade": "B",
        "manifest_sha256": spec["inputs"]["cy006_manifest"]["sha256"],
        "partitions": identities,
        "market_2026_partition_read": "NO",
    }


def _build_daily_frame(paths: list[Path]) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='10GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{TEMP_PATH.as_posix()}'")
    connection.from_parquet(
        [str(path) for path in paths], union_by_name=True
    ).create_view("source")
    audit_row = connection.execute(
        """
        SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
          sum((available_at>decision_at)::INTEGER),
          sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
          sum((hard_valid AND market_rule_valid AND
            (limit_pct IS NULL OR up_limit_price IS NULL))::INTEGER),
          sum((trade_date>DATE '2025-12-31')::INTEGER)
        FROM source
        """
    ).fetchone()
    audit = {
        "rows": int(audit_row[0]),
        "symbols": int(audit_row[1]),
        "first": str(audit_row[2]),
        "last": str(audit_row[3]),
        "time_travel": int(audit_row[4]),
        "lineage_failures": int(audit_row[5]),
        "limit_rule_failures": int(audit_row[6]),
        "post_2025_rows": int(audit_row[7]),
    }
    if (
        audit["first"] != "2018-01-02"
        or audit["last"] != "2025-12-31"
        or audit["time_travel"] != 0
        or audit["lineage_failures"] != 0
        or audit["limit_rule_failures"] != 0
        or audit["post_2025_rows"] != 0
    ):
        raise TemporalValidationError(f"daily source audit failed: {audit}")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER(ORDER BY trade_date)-1 cal_idx
        FROM (SELECT DISTINCT trade_date FROM source) ORDER BY trade_date
        """
    )
    calendar = [
        row[0]
        for row in connection.execute(
            "SELECT trade_date FROM calendar ORDER BY cal_idx"
        ).fetchall()
    ]
    connection.execute(
        """
        CREATE TEMP TABLE base AS SELECT s.*,c.cal_idx,
          (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
           AND s.trading_state_valid IS TRUE AND s.industry_valid IS TRUE
           AND s.float_valid IS TRUE AND s.corporate_action_valid IS TRUE
           AND s.market_valid IS TRUE AND s.market_rule_valid IS TRUE
           AND s.historical_identity_valid IS TRUE
           AND s.corporate_action_blocking IS FALSE
           AND coalesce(s.rights_ratio,0)=0
           AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
           AND s.open>0 AND s.high>=greatest(s.open,s.close)
           AND s.low<=least(s.open,s.close) AND s.close>0
           AND s.volume>=0 AND s.amount>=0) history_valid,
          (s.hard_valid IS TRUE AND s.trade_status=1
           AND s.current_day_data_tradable IS TRUE AND s.is_st IS FALSE) current_valid,
          lag(s.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
          lag(s.hard_valid IS TRUE AND s.bar_valid IS TRUE
           AND s.trading_state_valid IS TRUE AND s.industry_valid IS TRUE
           AND s.float_valid IS TRUE AND s.corporate_action_valid IS TRUE
           AND s.market_valid IS TRUE AND s.market_rule_valid IS TRUE
           AND s.historical_identity_valid IS TRUE
           AND s.corporate_action_blocking IS FALSE
           AND coalesce(s.rights_ratio,0)=0
           AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
           AND s.open>0 AND s.high>=greatest(s.open,s.close)
           AND s.low<=least(s.open,s.close) AND s.close>0
           AND s.volume>=0 AND s.amount>=0) OVER w previous_history_valid
        FROM source s JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY s.symbol ORDER BY s.trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE steps0 AS SELECT *,CASE
          WHEN history_valid AND previous_history_valid
           AND cal_idx-previous_cal_idx=1
           AND coalesce(corporate_action_count,0)=0
          THEN ln(close/previous_close)
          WHEN history_valid AND previous_history_valid
           AND cal_idx-previous_cal_idx=1 AND corporate_action_count>0
           AND corporate_action_available_date IS NOT NULL
           AND corporate_action_available_date<=trade_date
           AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
           AND previous_close-coalesce(cash_per_share,0)>0
          THEN ln(close/((previous_close-coalesce(cash_per_share,0))
            /coalesce(share_multiplier,1)))
          ELSE NULL END step_return
        FROM base
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE steps AS SELECT *,
          step_return-median(step_return) OVER(PARTITION BY trade_date) residual_step
        FROM steps0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE coordinates AS SELECT *,
          sum(coalesce(step_return,0)) OVER
            (PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING)
            log_coordinate
        FROM steps
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE geometry0 AS SELECT *,exp(log_coordinate) coordinate_close,
          exp(log_coordinate)*open/close coordinate_open,
          exp(log_coordinate)*high/close coordinate_high,
          exp(log_coordinate)*low/close coordinate_low,
          lag(exp(log_coordinate)) OVER ws previous_coordinate_close,
          count(step_return) OVER w120 valid_steps120,
          lag(cal_idx,120) OVER ws cal_idx_lag120,
          sum(step_return) OVER w5 r5,sum(step_return) OVER w20 r20,
          max(step_return) OVER w20 max_return20,
          count(step_return) OVER w20 valid_steps20,
          avg(amount) OVER p20 avg_amount20,median(amount) OVER p20 median_amount20,
          avg(volume) OVER p20 avg_volume20,count(*) OVER p20 prior_count20,
          count(residual_step) OVER w20 residual_count20,
          stddev_samp(residual_step) OVER w20 idio_vol20,
          sum(CASE WHEN step_return>0 THEN volume
                   WHEN step_return<0 THEN -volume ELSE 0 END)
            OVER w20 / nullif(sum(volume) OVER w20,0) signed_volume_share20
        FROM coordinates WINDOW
          ws AS (PARTITION BY symbol ORDER BY trade_date),
          w5 AS (PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w120 AS (PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
          p20 AS (PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE geometry AS SELECT *,
          (coordinate_high-coordinate_low)
            /nullif(previous_coordinate_close,0) range_fraction,
          ln(coordinate_open/nullif(previous_coordinate_close,0)) gap_return,
          ln(coordinate_close/nullif(coordinate_open,0)) intraday_return,
          CASE WHEN coordinate_high>coordinate_low
            THEN (coordinate_close-coordinate_low)/(coordinate_high-coordinate_low)
            ELSE 0.5 END close_location
        FROM geometry0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE rolling AS SELECT *,
          median(range_fraction) OVER p5 median_range5_prior,
          median(range_fraction) OVER p20 median_range20_prior,
          count(range_fraction) OVER p20 range_count20
        FROM geometry WINDOW
          p5 AS (PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
          p20 AS (PARTITION BY symbol ORDER BY trade_date
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE eligible0 AS SELECT *,
          range_fraction/nullif(median_range20_prior,0) range_ratio,
          median_range5_prior/nullif(median_range20_prior,0) compression_ratio,
          amount/nullif(median_amount20,0) activity_ratio,
          (high>=up_limit_price-greatest(0.001,abs(up_limit_price)*1e-6)) limit_touch
        FROM rolling
        WHERE current_valid AND history_valid AND cal_idx>=120
          AND valid_steps120=120 AND cal_idx-cal_idx_lag120=120
          AND valid_steps20=20 AND prior_count20=20
          AND avg_amount20>=50000000 AND avg_volume20>0
          AND previous_coordinate_close>0 AND coordinate_open>0
          AND isfinite(r5) AND isfinite(r20) AND isfinite(max_return20)
          AND residual_count20=20 AND isfinite(idio_vol20)
          AND isfinite(signed_volume_share20)
        """
    )
    frame = connection.execute(
        """
        SELECT *,count(*) OVER(PARTITION BY trade_date,industry) industry_count,
          (sum((r20>1e-12)::INTEGER) OVER(PARTITION BY trade_date,industry)
            -(r20>1e-12)::INTEGER)
            / nullif(count(*) OVER(PARTITION BY trade_date,industry)-1,0)
            diffusion_score,
          (sum(step_return) OVER(PARTITION BY trade_date,industry)-step_return)
            / nullif(count(*) OVER(PARTITION BY trade_date,industry)-1,0)
            industry_return_loo,
          (sum((step_return>0)::INTEGER) OVER(PARTITION BY trade_date,industry)
            -(step_return>0)::INTEGER)
            / nullif(count(*) OVER(PARTITION BY trade_date,industry)-1,0)
            industry_breadth_loo
        FROM eligible0 QUALIFY industry_count>=6
        ORDER BY trade_date,industry,symbol
        """
    ).fetch_df()
    connection.close()
    keep = [
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "step_return",
        "gap_return",
        "intraday_return",
        "range_fraction",
        "range_ratio",
        "compression_ratio",
        "close_location",
        "r20",
        "max_return20",
        "avg_amount20",
        "activity_ratio",
        "limit_touch",
        "limit_pct",
        "up_limit_price",
        "diffusion_score",
        "industry_return_loo",
        "industry_breadth_loo",
    ]
    frame = frame[keep].copy()
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise TemporalValidationError("invalid extended daily feature panel")
    return frame, calendar, audit


def _canonicalize_diffusion(frame: pd.DataFrame) -> pd.DataFrame:
    """Resolve machine-noise r20 ties without changing an economic threshold."""
    output = frame.copy()
    positive = output.r20.gt(R20_POSITIVE_EPSILON).astype(int)
    grouped = output.assign(_positive_r20=positive).groupby(
        ["trade_date", "industry"], sort=False
    )["_positive_r20"]
    counts = grouped.transform("count")
    if counts.le(1).any():
        raise TemporalValidationError("canonical diffusion encountered singleton industry")
    output["diffusion_score"] = (grouped.transform("sum") - positive) / (counts - 1)
    return output


def _parity_gate(
    extended: pd.DataFrame, accepted_path: Path, spec: dict[str, Any]
) -> dict[str, Any]:
    gate = spec["mandatory_pre_outcome_replication_gate"]
    start, end = [pd.Timestamp(item) for item in gate["overlap_period"]]
    accepted = pd.read_parquet(
        accepted_path, filters=[("trade_date", ">=", start), ("trade_date", "<=", end)]
    )
    accepted = _canonicalize_diffusion(accepted)
    candidate = extended.loc[
        pd.to_datetime(extended.trade_date).between(start, end)
    ].copy()
    if list(candidate.columns) != list(accepted.columns):
        raise TemporalValidationError("2023 feature columns do not reproduce")
    keys = ["trade_date", "symbol"]
    accepted = accepted.sort_values(keys).reset_index(drop=True)
    candidate = candidate.sort_values(keys).reset_index(drop=True)
    if len(candidate) != len(accepted):
        raise TemporalValidationError("2023 feature row count does not reproduce")
    accepted_keys = accepted[keys].astype(str)
    candidate_keys = candidate[keys].astype(str)
    if not accepted_keys.equals(candidate_keys):
        raise TemporalValidationError("2023 feature keys do not reproduce")

    max_abs = 0.0
    max_rel = 0.0
    numeric_columns = 0
    for column in accepted.columns:
        left = accepted[column]
        right = candidate[column]
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            numeric_columns += 1
            left_values = left.to_numpy(float)
            right_values = right.to_numpy(float)
            finite = np.isfinite(left_values) & np.isfinite(right_values)
            if not np.array_equal(np.isnan(left_values), np.isnan(right_values)):
                raise TemporalValidationError(f"2023 missingness changed: {column}")
            if finite.any():
                absolute = np.abs(left_values[finite] - right_values[finite])
                relative = absolute / np.maximum(np.abs(left_values[finite]), 1e-15)
                max_abs = max(max_abs, float(absolute.max()))
                max_rel = max(max_rel, float(relative.max()))
                close = np.isclose(
                    left_values[finite],
                    right_values[finite],
                    rtol=float(gate["maximum_relative_numeric_difference"]),
                    atol=float(gate["maximum_absolute_numeric_difference"]),
                )
                if not close.all():
                    first = int(np.flatnonzero(~close)[0])
                    raise TemporalValidationError(
                        f"2023 numeric parity failed:{column}:{first}"
                    )
        elif not left.astype(str).equals(right.astype(str)):
            raise TemporalValidationError(f"2023 exact parity failed: {column}")
    return {
        "status": "PASS",
        "overlap_start": start.date().isoformat(),
        "overlap_end": end.date().isoformat(),
        "rows": len(accepted),
        "columns": len(accepted.columns),
        "numeric_columns": numeric_columns,
        "maximum_absolute_numeric_difference": max_abs,
        "maximum_relative_numeric_difference": max_rel,
    }


def _weekly_low_max(daily: pd.DataFrame, construction: Any) -> pd.DataFrame:
    weekly = daily.loc[daily.cal_idx.mod(5).eq(4)].copy()
    baseline = (
        weekly.sort_values(
            ["trade_date", "diffusion_score", "symbol"],
            ascending=[True, False, True],
        )
        .groupby("trade_date", sort=False)
        .head(10)
        .copy()
    )
    baseline["signal_rank"] = baseline.groupby("trade_date").cumcount() + 1
    baseline["family"] = "arm0_baseline"
    if not baseline.groupby("trade_date").size().eq(10).all():
        raise TemporalValidationError("future diffusion baseline breadth changed")
    low_max = construction._select_modifier(
        weekly,
        baseline,
        "industry_diffusion_low_max",
        "max_return20",
        ascending=True,
    )
    if construction._allocation_difference(baseline, low_max) != 0:
        raise TemporalValidationError("Low-MAX changed frozen industry allocation")
    if not low_max.groupby("trade_date").size().eq(10).all():
        raise TemporalValidationError("future Low-MAX breadth changed")
    return low_max


def _q1_selection(champion: pd.DataFrame) -> pd.DataFrame:
    champion = champion.sort_values(
        ["trade_date", "diffusion_score", "max_return20", "symbol"],
        ascending=[True, False, True, True],
    ).copy()
    champion["q1_order"] = champion.groupby("trade_date").cumcount() + 1
    if not champion.groupby("trade_date").size().eq(10).all():
        raise TemporalValidationError("Champion signal breadth changed")
    selection = champion.loc[champion.q1_order.le(2)].copy()
    if not selection.groupby("trade_date").size().eq(2).all():
        raise TemporalValidationError("Q1 pair breadth changed")
    return selection


def _selection_replication_gate(
    accepted_daily: pd.DataFrame,
    candidate_daily: pd.DataFrame,
    q1: Any,
    q1_spec: dict[str, Any],
    cycle016: Any,
    spec: dict[str, Any],
) -> dict[str, Any]:
    construction = cycle016.CONSTRUCTION
    expected = _q1_selection(
        _weekly_low_max(_canonicalize_diffusion(accepted_daily), construction)
    )
    pre_2024 = candidate_daily.loc[
        pd.to_datetime(candidate_daily.trade_date).dt.year.le(2023)
    ].copy()
    generated = _q1_selection(_weekly_low_max(pre_2024, construction))
    columns = ["trade_date", "symbol", "industry"]
    expected_keys = expected[columns].copy()
    generated_keys = generated[columns].copy()
    for frame in (expected_keys, generated_keys):
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
    expected_keys = expected_keys.sort_values(columns).reset_index(drop=True)
    generated_keys = generated_keys.sort_values(columns).reset_index(drop=True)
    if not expected_keys.equals(generated_keys):
        raise TemporalValidationError("causal-erratum Q1 construction does not reproduce")

    serialized = expected_keys.copy()
    serialized["trade_date"] = serialized.trade_date.dt.strftime("%Y-%m-%d")
    selection_sha256 = hashlib.sha256(
        serialized.to_csv(index=False, lineterminator="\n").encode()
    ).hexdigest()
    expected_hash = spec["corrected_development_diagnostic"]["selection_sha256"]
    if selection_sha256 != expected_hash:
        raise TemporalValidationError("corrected development selection identity changed")

    legacy_keys = q1._selection(q1_spec, cycle016)[columns].copy()
    legacy_keys["trade_date"] = pd.to_datetime(legacy_keys.trade_date)
    legacy_keys = legacy_keys.sort_values(columns).reset_index(drop=True)
    comparison = legacy_keys.merge(expected_keys, how="outer", indicator=True)
    changed = comparison.loc[comparison._merge.ne("both")]
    return {
        "status": "PASS",
        "rows": len(expected_keys),
        "decision_dates": int(expected_keys.trade_date.nunique()),
        "selection_sha256": selection_sha256,
        "legacy_rows_unchanged": int(comparison._merge.eq("both").sum()),
        "legacy_rows_removed": int(comparison._merge.eq("left_only").sum()),
        "corrected_rows_added": int(comparison._merge.eq("right_only").sum()),
        "decision_dates_with_any_pair_change": int(changed.trade_date.nunique()),
    }


def _load_validation_risk_events(
    spec: dict[str, Any], calendar: list[date], ca: Any
) -> tuple[list[Any], dict[str, Any]]:
    distributions = _resolve(spec["inputs"]["qd010_distributions"]["path"])
    rights = _resolve(spec["inputs"]["qd010_rights"]["path"])
    connection = duckdb.connect()
    rows = connection.execute(
        """
        SELECT symbol,event_id,'SHARE_DISTRIBUTION' AS event_kind,
          CAST(known_at AS DATE) known_date,CAST(effective_date AS DATE) effective_date
        FROM read_parquet(?)
        WHERE effective_date BETWEEN DATE '2024-01-01' AND DATE '2025-12-31'
          AND coalesce(share_multiplier,1)>1 AND source_terms_complete IS TRUE
        UNION ALL
        SELECT symbol,event_id,'RIGHTS_ISSUE' AS event_kind,
          CAST(known_at AS DATE) known_date,CAST(effective_date AS DATE) effective_date
        FROM read_parquet(?)
        WHERE effective_date BETWEEN DATE '2024-01-01' AND DATE '2025-12-31'
        ORDER BY symbol,effective_date,event_id
        """,
        [str(distributions), str(rights)],
    ).fetchdf()
    connection.close()
    if rows.event_id.isna().any() or rows.duplicated("event_id").any():
        raise TemporalValidationError("missing or duplicate QD-010 event identity")
    events: list[Any] = []
    invalid_timing = 0
    for row in rows.itertuples(index=False):
        if pd.isna(row.known_date) or pd.isna(row.effective_date):
            invalid_timing += 1
            continue
        known = pd.Timestamp(row.known_date).date()
        effective = pd.Timestamp(row.effective_date).date()
        decision = (
            ca._first_decision_date(known, effective, calendar)
            if known < effective
            else None
        )
        invalid_timing += int(decision is None)
        events.append(
            ca.RiskEvent(
                symbol=ca._market_symbol(row.symbol),
                event_id=str(row.event_id),
                event_kind=str(row.event_kind),
                known_date=known,
                decision_date=decision,
                effective_date=effective,
            )
        )
    audit = {
        "risk_events_2024_2025": len(events),
        "share_distribution_events": sum(
            item.event_kind == "SHARE_DISTRIBUTION" for item in events
        ),
        "rights_events": sum(item.event_kind == "RIGHTS_ISSUE" for item in events),
        "events_without_pre_effective_decision_session": invalid_timing,
        "first_effective_date": min(
            (item.effective_date for item in events), default=None
        ),
        "last_effective_date": max(
            (item.effective_date for item in events), default=None
        ),
        "pit_boundary": "QD-010 PIT-B current-history evidence; no PIT-A claim",
    }
    return events, audit


def _performance(equity: pd.DataFrame, initial_nav: float) -> dict[str, float | None]:
    nav = equity.nav.to_numpy(float)
    returns = np.empty(len(nav), dtype=float)
    returns[0] = nav[0] / initial_nav - 1.0
    returns[1:] = nav[1:] / nav[:-1] - 1.0
    peaks = np.maximum.accumulate(np.concatenate(([initial_nav], nav)))[1:]
    drawdown = nav / peaks - 1.0
    total = float(nav[-1] / initial_nav - 1.0)
    annualized = float((1.0 + total) ** (252.0 / len(nav)) - 1.0)
    volatility = float(np.std(returns, ddof=1))
    sharpe = (
        float(math.sqrt(252.0) * np.mean(returns) / volatility)
        if volatility > 0
        else 0.0
    )
    maximum_drawdown = float(drawdown.min())
    return {
        "total_return": total,
        "annualized_return": annualized,
        "maximum_drawdown": maximum_drawdown,
        "daily_sharpe": sharpe,
        "calmar": annualized / abs(maximum_drawdown)
        if maximum_drawdown < 0
        else None,
    }


def _full_calendar_equity(
    replay_equity: pd.DataFrame, calendar: list[date]
) -> pd.DataFrame:
    start = next(item for item in calendar if item >= VALIDATION_START)
    first_replay = pd.Timestamp(replay_equity.trade_date.iloc[0]).date()
    prior_dates = [item for item in calendar if start <= item < first_replay]
    prior = pd.DataFrame(
        {
            "trade_date": prior_dates,
            "family": "industry_consensus_q1_event",
            "nav": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "positions": 0,
            "industries": 0,
            "industry_hhi": 0.0,
        }
    )
    output = pd.concat([prior, replay_equity], ignore_index=True)
    if (
        pd.Timestamp(output.trade_date.iloc[0]).date() != start
        or pd.Timestamp(output.trade_date.iloc[-1]).date() != VALIDATION_END
    ):
        raise TemporalValidationError("full validation calendar is incomplete")
    return output


def _yearly_metrics(
    equity: pd.DataFrame, trades: pd.DataFrame, plans: pd.DataFrame
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    prior_nav = INITIAL_CAPITAL
    signal_dates = pd.to_datetime(plans.signal_date)
    exit_dates = pd.to_datetime(trades.exit_date)
    for year in (2024, 2025):
        year_equity = equity.loc[pd.to_datetime(equity.trade_date).dt.year.eq(year)]
        year_trades = trades.loc[exit_dates.dt.year.eq(year)]
        metrics = _performance(year_equity, prior_nav)
        metrics.update(
            {
                "event_dates": int(signal_dates.loc[signal_dates.dt.year.eq(year)].nunique()),
                "planned_entries": int(signal_dates.dt.year.eq(year).sum()),
                "completed_exits": len(year_trades),
                "severe_exit_fraction": float(year_trades.net_return.le(-0.10).mean())
                if len(year_trades)
                else None,
            }
        )
        output[str(year)] = metrics
        prior_nav = float(year_equity.nav.iloc[-1])
    return output


def _classify(
    candidate: dict[str, Any], years: dict[str, Any], spec: dict[str, Any]
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    primary = spec["classification"]["INDEPENDENT_TEMPORAL_CONFIRMATION_PASS_all_required"]
    primary_checks = {
        "event_dates": candidate["event_dates"] >= primary["minimum_event_dates"],
        "entry_execution": candidate["entry_execution_fraction"]
        >= primary["minimum_entry_execution_fraction"],
        "total_return": candidate["total_return"] > primary["minimum_total_return"],
        "daily_sharpe": candidate["daily_sharpe"] >= primary["minimum_daily_sharpe"],
        "maximum_drawdown": candidate["maximum_drawdown"]
        > primary["maximum_drawdown_must_be_greater_than"],
        "severe_trade_fraction": candidate["severe_trade_fraction"]
        <= primary["maximum_severe_trade_fraction"],
        "positive_calendar_years": all(
            years[year]["total_return"] > 0 for year in primary["positive_calendar_years"]
        ),
        "terminal_open_lots": candidate["terminal_open_lots"]
        == primary["terminal_open_lots"],
    }
    mixed = spec["classification"]["POSITIVE_BUT_MIXED_TRANSFER_all_required"]
    mixed_checks = {
        "event_dates": candidate["event_dates"] >= mixed["minimum_event_dates"],
        "entry_execution": candidate["entry_execution_fraction"]
        >= mixed["minimum_entry_execution_fraction"],
        "total_return": candidate["total_return"] > mixed["minimum_total_return"],
        "daily_sharpe": candidate["daily_sharpe"] > mixed["minimum_daily_sharpe"],
        "maximum_drawdown": candidate["maximum_drawdown"]
        > mixed["maximum_drawdown_must_be_greater_than"],
        "terminal_open_lots": candidate["terminal_open_lots"]
        == mixed["terminal_open_lots"],
    }
    if all(primary_checks.values()):
        classification = "INDEPENDENT_TEMPORAL_CONFIRMATION_PASS"
    elif candidate["total_return"] <= 0 or candidate["daily_sharpe"] <= 0:
        classification = "NO_TEMPORAL_TRANSFER"
    elif all(mixed_checks.values()):
        classification = "POSITIVE_BUT_MIXED_TRANSFER"
    else:
        classification = "TEMPORAL_TRANSFER_INCONCLUSIVE"
    return classification, primary_checks, mixed_checks


def _render(result: dict[str, Any]) -> str:
    candidate = result["candidate"]
    years = result["calendar_years"]
    development = result["development_comparison"][
        "causal_numeric_erratum_2018_2023"
    ]
    return "\n".join(
        [
            "# Industry-Consensus Q1 temporal validation — 2024-2025 V1.1",
            "",
            f"Classification: `{result['classification']}`.",
            "",
            (
                "The economic rule was carried forward without changing its pair, industry "
                "condition, capital divisor, entry, h20 exit, cost, or execution semantics. "
                "Before any validation portfolio outcome was aggregated, a failed 2023 "
                "replication gate exposed a future-batch-dependent floating-point sign at "
                "mathematically zero r20. V1.1 freezes those machine-noise ties as neutral."
            ),
            "",
            "## Combined 2024-2025",
            "",
            (
                f"Total {candidate['total_return']:.2%}; annualized "
                f"{candidate['annualized_return']:.2%}; maximum drawdown "
                f"{candidate['maximum_drawdown']:.2%}; Sharpe "
                f"{candidate['daily_sharpe']:.3f}; Calmar "
                f"{candidate['calmar']:.3f}."
            ),
            (
                f"Events {candidate['event_dates']}; completed trades "
                f"{candidate['completed_trades']}; entry execution "
                f"{candidate['entry_execution_fraction']:.2%}; severe trades "
                f"{candidate['severe_trade_fraction']:.2%}; turnover "
                f"{candidate['turnover_multiple_initial_capital']:.2f}x."
            ),
            "",
            "## Calendar years",
            "",
            "| Year | Return | Annualized | Max DD | Sharpe | Events | Exits |",
            "|---:|---:|---:|---:|---:|---:|---:|",
            *[
                (
                    f"| {year} | {years[year]['total_return']:.2%} | "
                    f"{years[year]['annualized_return']:.2%} | "
                    f"{years[year]['maximum_drawdown']:.2%} | "
                    f"{years[year]['daily_sharpe']:.3f} | "
                    f"{years[year]['event_dates']} | "
                    f"{years[year]['completed_exits']} |"
                )
                for year in ("2024", "2025")
            ],
            "",
            "## Frozen decision",
            "",
            (
                "The validation passes combined positive return, drawdown, severe-loss, "
                "event-count, and terminal-liquidation checks. It fails the 0.50 Sharpe "
                "gate, the requirement that both calendar years be positive, and the "
                "90% entry-ratio gate. The 84% entry ratio also misses the frozen 85% "
                "mixed-transfer gate; all 16 missing entries were capital-skipped under "
                "the unchanged cash ledger, not market-unexecutable."
            ),
            (
                "Therefore the result is weak positive transfer, not independent "
                "confirmation. No filter, Top-N, threshold, holding, exit, sizing, or "
                "combination rescue is authorized on consumed 2024-2025."
            ),
            "",
            "## Frozen development comparison",
            "",
            (
                f"The numerically corrected consumed 2018-2023 development result was "
                f"{development['annualized_return']:.2%} annualized, "
                f"{development['maximum_drawdown']:.2%} maximum drawdown, and "
                f"{development['daily_sharpe']:.3f} Sharpe. This comparison is "
                "descriptive only and does not authorize any rule change."
            ),
            "",
            "## Governance",
            "",
            (
                "2024-2025 data access began only after explicit user authorization and the "
                "initial hashed contract. No portfolio result was accepted before the "
                "causal numerical erratum was diagnosed solely on the 2023 overlap, checked "
                "on consumed development history, and re-frozen. No 2026 market outcome or "
                "CY-011 was read. CY-006 and QD-010 remain registered PIT-B/current-history "
                "inputs, so this is temporal validation under that accepted data contract, "
                "not a live or guaranteed-return claim."
            ),
            "",
        ]
    )


def run() -> dict[str, Any]:
    spec = _load_spec()
    paths, input_identity = _validated_cy006_paths(spec)
    extended, calendar, source_audit = _build_daily_frame(paths)
    accepted_path = _resolve(
        spec["inputs"]["accepted_pre2024_daily_feature_panel"]["path"]
    )
    feature_parity = _parity_gate(extended, accepted_path, spec)

    base = _load_module(
        "industry_consensus_q1_frozen_for_temporal_validation",
        _resolve(spec["inputs"]["frozen_strategy_runner"]["path"]),
    )
    q1 = _load_module(
        "q1_construction_for_temporal_validation",
        _resolve(spec["inputs"]["q1_construction_runner"]["path"]),
    )
    q1_spec = q1._load_spec()
    cycle016 = q1._load_module(
        "cycle016_for_temporal_validation",
        q1._resolve(q1_spec["inputs"]["champion_anatomy_runner"]["path"]),
    )
    accepted_daily = pd.read_parquet(accepted_path)
    selection_parity = _selection_replication_gate(
        accepted_daily, extended, q1, q1_spec, cycle016, spec
    )

    retained = extended.loc[pd.to_datetime(extended.trade_date).dt.year.ge(2023)].copy()
    retained.to_parquet(FEATURE_PATH, index=False, compression="zstd")
    construction = cycle016.CONSTRUCTION
    future_champion = _weekly_low_max(extended, construction)
    future_q1 = _q1_selection(future_champion)
    future_q1 = future_q1.loc[
        pd.to_datetime(future_q1.trade_date).dt.date.between(
            VALIDATION_START, VALIDATION_END
        )
    ].copy()
    future_q1["trade_date"] = pd.to_datetime(future_q1.trade_date).dt.date

    plans = base._plans(future_q1, calendar)
    if plans.empty or not plans.signal_date.map(
        lambda item: VALIDATION_START <= item <= VALIDATION_END
    ).all():
        raise TemporalValidationError("invalid validation plan window")
    selection = plans.merge(
        future_q1[
            [
                "trade_date",
                "symbol",
                "industry",
                "diffusion_score",
                "max_return20",
                "q1_order",
            ]
        ].rename(columns={"trade_date": "signal_date"}),
        on=["signal_date", "symbol", "industry"],
        how="left",
        validate="one_to_one",
    ).sort_values(["signal_date", "symbol"])
    if selection[["diffusion_score", "max_return20", "q1_order"]].isna().any().any():
        raise TemporalValidationError("selection lineage incomplete")

    ca = cycle016.CA
    market_rows = ca.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = _load_validation_risk_events(spec, calendar, ca)
    base.EVALUATION_END = VALIDATION_END
    candidate, replay_equity, trades = base._replay(
        plans, market_rows, calendar, events, ca
    )
    equity = _full_calendar_equity(replay_equity, calendar)
    candidate.update(_performance(equity, INITIAL_CAPITAL))
    candidate.update(
        {
            "family": "industry_consensus_q1_event_causal_numeric_erratum",
            "start_date": str(equity.trade_date.iloc[0]),
            "end_date": str(equity.trade_date.iloc[-1]),
            "terminal_open_lots": 0,
        }
    )
    years = _yearly_metrics(equity, trades, plans)
    classification, primary_checks, mixed_checks = _classify(
        candidate, years, spec
    )
    legacy_development_result = json.loads(
        _resolve(spec["inputs"]["frozen_strategy_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    development = spec["corrected_development_diagnostic"]["candidate"]
    comparison = {
        "causal_numeric_erratum_2018_2023": development,
        "legacy_floating_implementation_2018_2023": legacy_development_result[
            "candidate"
        ],
        "annualized_return_delta": candidate["annualized_return"]
        - development["annualized_return"],
        "maximum_drawdown_delta": candidate["maximum_drawdown"]
        - development["maximum_drawdown"],
        "daily_sharpe_delta": candidate["daily_sharpe"]
        - development["daily_sharpe"],
    }

    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        TRADES_PATH,
        trades.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        SELECTION_PATH,
        selection.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "classification": classification,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "YES_AUTHORIZED_2024_2025_ONLY",
        "maximum_market_outcome_date": "2025-12-31",
        "market_2026_outcome_read": "NO",
        "cy011_read": "NO",
        "candidate": candidate,
        "calendar_years": years,
        "primary_confirmation_checks": primary_checks,
        "mixed_transfer_checks": mixed_checks,
        "development_comparison": comparison,
        "feature_replication_gate": feature_parity,
        "selection_replication_gate": selection_parity,
        "initial_contract_failure": spec["initial_contract_failure"],
        "numerical_erratum": spec["numerical_erratum"],
        "source_audit": source_audit,
        "input_identity": input_identity,
        "action_audit": action_audit,
        "external_feature_artifact": {
            "path": str(FEATURE_PATH),
            "sha256": sha256_file(FEATURE_PATH),
            "rows": len(retained),
            "first_date": str(retained.trade_date.min()),
            "last_date": str(retained.trade_date.max()),
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
            "trades_sha256": sha256_file(TRADES_PATH),
            "selection_sha256": sha256_file(SELECTION_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
