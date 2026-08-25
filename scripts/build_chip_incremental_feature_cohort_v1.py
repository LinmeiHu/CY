#!/usr/bin/env python3
"""Join registered CY-021 to the chip-free cohort without reading outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from cyq_game.data.registry import DataAssetRegistry  # type: ignore[import-untyped]
from cyq_game.strategy.chip_incremental import (  # type: ignore[import-untyped]
    fixed_chip_primitives,
)
from cyq_game.strategy.markup_retest import (  # type: ignore[import-untyped]
    FORBIDDEN_SIGNAL_FIELDS,
)

REGISTRY = Path("configs/data_asset_registry.json")
PROTOCOL = Path("output/chip_incremental_validation_v1/protocol_manifest.json")
ADDENDUM_01 = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_01_manifest.json"
)
ADDENDUM_02 = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_02_manifest.json"
)
ADDENDUM_03 = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_03_manifest.json"
)
ADDENDUM_04 = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_04_manifest.json"
)
ADDENDUM_05 = Path(
    "output/chip_incremental_validation_v1/addenda/addendum_05_manifest.json"
)
CANDIDATE_MANIFEST = Path(
    "output/chip_incremental_validation_v1/candidates/manifest.json"
)
DEFAULT_OUTPUT = Path("output/chip_incremental_validation_v1/features")
SELECTOR_CODE = Path("src/cyq_game/strategy/chip_incremental.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threads", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.threads < 1 or args.threads > 4:
        raise ValueError("--threads must be between 1 and 4")
    target = args.output.resolve()
    output_path = target / "candidate_chip_features.parquet"
    manifest_path = target / "manifest.json"
    if output_path.is_file() and manifest_path.is_file():
        payload = _object(manifest_path)
        if payload.get("feature_cohort_sha256") != _sha256(output_path):
            raise ValueError("existing chip feature cohort hash changed")
        print(
            f"REUSED rows={payload['rows']} valid={payload['measurement_valid_rows']} "
            f"output={output_path}",
            flush=True,
        )
        return 0
    if target.exists():
        raise FileExistsError(f"incomplete chip feature cohort exists: {target}")

    (
        protocol,
        addendum_01,
        addendum_02,
        addendum_03,
        addendum_04,
        addendum_05,
    ) = _protocol_chain()
    candidate_manifest_path = CANDIDATE_MANIFEST.resolve()
    candidate_manifest = _object(candidate_manifest_path)
    candidate_path = candidate_manifest_path.parent / str(
        candidate_manifest["candidate_events"]
    )
    if (
        candidate_manifest.get("status") != "COMPLETE_OUTCOME_BLIND"
        or candidate_manifest.get("candidate_events_sha256") != _sha256(candidate_path)
        or candidate_manifest.get("chip_fields_used") is not False
        or candidate_manifest.get("outcome_fields_used") is not False
        or candidate_manifest.get("maximum_input_date") != "2022-12-30"
    ):
        raise ValueError("price-volume candidate manifest is not outcome-blind")

    registry = DataAssetRegistry.load(REGISTRY.resolve())
    semantic_path, semantic_manifest_path, semantic_manifest = _semantic_asset(registry)
    exact_files, exact_inventory = _exact_feature_inputs(registry)
    daily_files, daily_inventory = _candidate_daily_inputs(candidate_manifest)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    temporary_output = temporary / "candidate_chip_features.parquet"

    con = duckdb.connect()
    try:
        con.execute(f"SET threads={args.threads}")
        con.execute("SET memory_limit='10GiB'")
        con.execute("SET preserve_insertion_order=false")
        result = con.execute(
            _feature_query(candidate_path, semantic_path, exact_files, daily_files)
        )
        description = result.description
        if description is None:
            raise RuntimeError("chip feature query returned no schema")
        columns = tuple(item[0] for item in description)
        forbidden = sorted(set(columns).intersection(FORBIDDEN_SIGNAL_FIELDS))
        if forbidden:
            raise ValueError("feature cohort contains outcome fields: " + ", ".join(forbidden))
        raw_rows = [
            dict(zip(columns, values, strict=True)) for values in result.fetchall()
        ]
    finally:
        con.close()
    enriched = [{**row, **fixed_chip_primitives(row)} for row in raw_rows]
    if not enriched:
        shutil.rmtree(temporary)
        raise RuntimeError("chip feature join produced no rows")
    pq.write_table(pa.Table.from_pylist(enriched), temporary_output, compression="zstd")
    metrics = _validate(temporary_output, int(candidate_manifest["candidates"]))
    output_sha256 = _sha256(temporary_output)
    identity: dict[str, Any] = {
        "protocol_event_id": protocol["event_id"],
        "candidate_snapshot_id": candidate_manifest["candidate_snapshot_id"],
        "semantic_snapshot_id": semantic_manifest["snapshot_id"],
        "feature_cohort_sha256": output_sha256,
        "builder_sha256": _sha256(Path(__file__).resolve()),
        "selector_sha256": _sha256(SELECTOR_CODE.resolve()),
        "metrics": metrics,
    }
    snapshot_id = "chip-incremental-features-" + hashlib.sha256(
        _canonical(identity).encode()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "COMPLETE_OUTCOME_BLIND",
        "created_at": datetime.now(UTC).isoformat(),
        "feature_cohort_snapshot_id": snapshot_id,
        **identity,
        "protocol_manifest": str(PROTOCOL.resolve()),
        "protocol_manifest_sha256": _sha256(PROTOCOL.resolve()),
        "addendum_01_event_id": addendum_01["event_id"],
        "addendum_02_event_id": addendum_02["event_id"],
        "addendum_03_event_id": addendum_03["event_id"],
        "addendum_04_event_id": addendum_04["event_id"],
        "addendum_05_event_id": addendum_05["event_id"],
        "candidate_manifest": str(candidate_manifest_path),
        "candidate_manifest_sha256": _sha256(candidate_manifest_path),
        "semantic_manifest": str(semantic_manifest_path),
        "semantic_manifest_sha256": _sha256(semantic_manifest_path),
        "exact_feature_inventory": exact_inventory,
        "daily_input_inventory": daily_inventory,
        "feature_cohort": "candidate_chip_features.parquet",
        "feature_cohort_sha256": output_sha256,
        "rows": metrics["rows"],
        "measurement_valid_rows": metrics["measurement_valid_rows"],
        "maximum_input_date": "2022-12-30",
        "outcome_fields_used": False,
        "holdout_outcomes_observed": False,
    }
    _write(temporary / "manifest.json", manifest)
    temporary.replace(target)
    print(
        f"PASS rows={metrics['rows']} valid={metrics['measurement_valid_rows']} "
        f"valid_ratio={metrics['measurement_valid_ratio']:.6f} output={output_path}",
        flush=True,
    )
    return 0


def _protocol_chain() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    protocol = _object(PROTOCOL.resolve())
    first = _object(ADDENDUM_01.resolve())
    second = _object(ADDENDUM_02.resolve())
    third = _object(ADDENDUM_03.resolve())
    fourth = _object(ADDENDUM_04.resolve())
    fifth = _object(ADDENDUM_05.resolve())
    if (
        protocol.get("status") != "PREREGISTERED"
        or protocol.get("holdout_outcomes_observed") is not False
        or first.get("protocol_event_id") != protocol.get("event_id")
        or second.get("protocol_event_id") != protocol.get("event_id")
        or second.get("prior_addendum_event_id") != first.get("event_id")
        or second.get("holdout_outcomes_observed") is not False
        or third.get("protocol_event_id") != protocol.get("event_id")
        or third.get("prior_addendum_event_id") != second.get("event_id")
        or third.get("holdout_outcomes_observed") is not False
        or fourth.get("protocol_event_id") != protocol.get("event_id")
        or fourth.get("prior_addendum_event_id") != third.get("event_id")
        or fourth.get("holdout_outcomes_observed") is not False
        or fifth.get("protocol_event_id") != protocol.get("event_id")
        or fifth.get("prior_addendum_event_id") != fourth.get("event_id")
        or fifth.get("holdout_outcomes_observed") is not False
    ):
        raise ValueError("chip incremental protocol chain changed")
    return protocol, first, second, third, fourth, fifth


def _semantic_asset(
    registry: DataAssetRegistry,
) -> tuple[Path, Path, dict[str, Any]]:
    try:
        asset = registry.assets["CY-021"]
    except KeyError as error:
        raise ValueError("CY-021 must be registered before feature joining") from error
    if asset.status != "RESEARCH_CONDITIONAL" or asset.location is None:
        raise ValueError("CY-021 is not research-activated")
    raw_path = asset.lineage.get("manifest_path")
    raw_sha256 = asset.lineage.get("manifest_sha256")
    if not isinstance(raw_path, str) or not isinstance(raw_sha256, str):
        raise ValueError("CY-021 lacks a registered manifest identity")
    manifest_path = Path(raw_path).expanduser().resolve()
    if _sha256(manifest_path) != raw_sha256:
        raise ValueError("CY-021 registered manifest changed")
    manifest = _object(manifest_path)
    data_path = Path(str(manifest["data_path"])).resolve()
    if (
        manifest.get("status") != "PASS"
        or manifest.get("asset_id") != "CY-021"
        or manifest.get("coverage", {}).get("end") != "2022-12-30"
        or manifest.get("holdout_outcomes_observed") is not False
        or manifest.get("data_sha256") != _sha256(data_path)
    ):
        raise ValueError("CY-021 semantic freeze is invalid")
    return data_path, manifest_path, manifest


def _exact_feature_inputs(
    registry: DataAssetRegistry,
) -> tuple[tuple[Path, ...], list[dict[str, Any]]]:
    asset = registry.assets["CY-019"]
    raw_path = asset.lineage.get("manifest_path")
    raw_sha256 = asset.lineage.get("manifest_sha256")
    if not isinstance(raw_path, str) or not isinstance(raw_sha256, str):
        raise ValueError("CY-019 lacks a registered manifest")
    manifest_path = Path(raw_path).expanduser().resolve()
    if _sha256(manifest_path) != raw_sha256:
        raise ValueError("CY-019 manifest identity changed")
    manifest = _object(manifest_path)
    root = Path(str(manifest["location"])).resolve()
    selected: list[dict[str, Any]] = []
    by_path = {
        str(item["path"]): item
        for item in manifest["inventory"]
        if isinstance(item, dict)
    }
    for year in (2020, 2021, 2022):
        relative = f"year={year}/data.parquet"
        raw = by_path.get(relative)
        if raw is None:
            raise ValueError(f"CY-019 manifest lacks {relative}")
        path = root / relative
        if (
            not path.is_file()
            or path.stat().st_size != raw["size"]
            or _sha256(path) != raw["sha256"]
        ):
            raise ValueError(f"CY-019 development partition changed: {path}")
        selected.append(
            {
                "year": year,
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": raw["sha256"],
            }
        )
    return tuple(Path(item["path"]) for item in selected), selected


def _candidate_daily_inputs(
    candidate_manifest: dict[str, Any],
) -> tuple[tuple[Path, ...], list[dict[str, Any]]]:
    raw_inventory = candidate_manifest.get("source_inventory")
    if not isinstance(raw_inventory, list) or len(raw_inventory) != 5:
        raise ValueError("candidate manifest lacks exact 2018-2022 daily inventory")
    selected: list[dict[str, Any]] = []
    for raw in raw_inventory:
        if not isinstance(raw, dict) or int(raw.get("year", 0)) not in range(2018, 2023):
            raise ValueError("candidate daily inventory contains a forbidden year")
        path = Path(str(raw["absolute_path"])).resolve()
        if (
            not path.is_file()
            or path.stat().st_size != raw["size"]
            or _sha256(path) != raw["sha256"]
        ):
            raise ValueError(f"candidate daily input changed: {path}")
        selected.append(dict(raw))
    selected.sort(key=lambda item: int(item["year"]))
    return tuple(Path(str(item["absolute_path"])) for item in selected), selected


def _feature_query(
    candidates: Path,
    semantic: Path,
    exact_files: tuple[Path, ...],
    daily_files: tuple[Path, ...],
) -> str:
    exact_sql = _sql_list(exact_files)
    daily_sql = _sql_list(daily_files)
    return f"""
        WITH candidates AS (
            SELECT * FROM read_parquet({_sql_text(str(candidates))})
        ), candidate_symbols AS (
            SELECT DISTINCT symbol FROM candidates
        ), raw_daily AS (
            SELECT d.*,
                   lag(close) OVER (PARTITION BY symbol ORDER BY trade_date)
                       AS previous_raw_close
            FROM read_parquet({daily_sql}, union_by_name=true) d
            SEMI JOIN candidate_symbols USING (symbol)
            WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2022-12-30'
        ), coordinate_step AS (
            SELECT *, CASE
                WHEN coalesce(corporate_action_count, 0) > 0
                 AND previous_raw_close > 0 AND preclose > 0
                THEN preclose / previous_raw_close ELSE 1.0
            END AS coordinate_step
            FROM raw_daily
        ), coordinate_product AS (
            SELECT *, exp(sum(ln(coordinate_step)) OVER (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )) AS coordinate_factor,
                   exp(sum(ln(share_multiplier)) OVER (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )) AS economic_share_product
            FROM coordinate_step
        ), coordinate AS (
            SELECT *, sum(cash_per_share * economic_share_product
                                      / share_multiplier) OVER (
                PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS economic_cash_base
            FROM coordinate_product
        ), normalized AS (
            SELECT *, close / coordinate_factor AS analysis_close,
                   greatest(high-low, abs(high-preclose), abs(low-preclose))
                       / coordinate_factor AS analysis_true_range
            FROM coordinate
        ), daily_features AS (
            SELECT symbol, trade_date, close, economic_share_product,
                   economic_cash_base,
                   avg(analysis_true_range) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
                   ) * coordinate_factor AS atr14,
                   CASE WHEN lag(analysis_close, 20) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                   ) > 0 THEN analysis_close / lag(analysis_close, 20) OVER (
                       PARTITION BY symbol ORDER BY trade_date
                   ) - 1.0 END AS momentum_20
            FROM normalized
        ), exact AS (
            SELECT symbol, trade_date, available_at AS exact_available_at,
                   p50 AS exact_p50, dominant_band_mass,
                   chip_input_valid AND daily_hard_valid AND minute_hard_valid
                       AND state_chain_valid AND abs(CAST(mass_sum AS DOUBLE)-1.0) <= 1e-9
                       AND p50 > 0 AND dominant_band_mass IS NOT NULL
                       AS exact_source_valid,
                   daily_snapshot_id AS exact_daily_snapshot_id,
                   minute_snapshot_id AS exact_minute_snapshot_id,
                   state_version AS exact_state_version
            FROM read_parquet({exact_sql}, union_by_name=true)
            WHERE trade_date BETWEEN DATE '2020-01-02' AND DATE '2022-12-30'
        ), joined AS (
            SELECT s.*, d.close, d.atr14, d.momentum_20,
                   e.exact_p50 AS exact_p50_raw,
                   e.exact_p50 * d.economic_share_product
                       + d.economic_cash_base AS exact_p50,
                   d.economic_share_product, d.economic_cash_base,
                   e.dominant_band_mass,
                   e.exact_available_at, e.exact_source_valid,
                   e.exact_daily_snapshot_id, e.exact_minute_snapshot_id,
                   e.exact_state_version
            FROM read_parquet({_sql_text(str(semantic))}) s
            LEFT JOIN daily_features d USING (symbol, trade_date)
            LEFT JOIN exact e USING (symbol, trade_date)
        ), lagged AS (
            SELECT *,
                   lag(close, 20) OVER w AS close_lag20,
                   lag(atr14, 20) OVER w AS atr14_lag20,
                   lag(momentum_20, 20) OVER w AS momentum_20_lag20,
                   lag(exact_p50, 20) OVER w AS exact_p50_lag20,
                   lag(exact_p50, 40) OVER w AS exact_p50_lag40,
                   lag(dominant_band_mass, 20) OVER w AS dominant_band_mass_lag20,
                   lag(i70_lower, 20) OVER w AS i70_lower_lag20,
                   lag(i70_upper, 20) OVER w AS i70_upper_lag20,
                   lag(i90_lower, 20) OVER w AS i90_lower_lag20,
                   lag(i90_upper, 20) OVER w AS i90_upper_lag20,
                   lag(i90_width_fraction, 20) OVER w AS i90_width_fraction_lag20,
                   lag(i90_width_fraction, 40) OVER w AS i90_width_fraction_lag40,
                   lag(profit_ratio, 20) OVER w AS profit_ratio_lag20,
                   lag(profit_ratio, 40) OVER w AS profit_ratio_lag40,
                   lag(lower_peak_strength, 20) OVER w AS lower_peak_strength_lag20,
                   lag(upper_peak_strength, 20) OVER w AS upper_peak_strength_lag20,
                   lag(valley_depth, 20) OVER w AS valley_depth_lag20
            FROM joined
            WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        )
        SELECT c.*,
               abs(hash(c.symbol) % 32)::INTEGER AS symbol_bucket,
               CAST(l.available_at AS TIMESTAMP) AS semantic_available_at,
               l.snapshot_id AS semantic_snapshot_id,
               l.research_valid AND l.available_at <= c.decision_at
                   AS semantic_research_valid,
               l.exact_source_valid AND l.exact_available_at <= c.decision_at
                   AS exact_research_valid,
               l.exact_daily_snapshot_id, l.exact_minute_snapshot_id,
               l.exact_state_version,
               l.close, l.atr14, l.momentum_20,
               l.close_lag20, l.atr14_lag20, l.momentum_20_lag20,
               l.exact_p50_raw, l.economic_share_product, l.economic_cash_base,
               l.exact_p50, l.exact_p50_lag20, l.exact_p50_lag40,
               l.dominant_band_mass, l.dominant_band_mass_lag20,
               l.i70_lower, l.i70_upper, l.i90_lower, l.i90_upper,
               l.i70_lower_lag20, l.i70_upper_lag20,
               l.i90_lower_lag20, l.i90_upper_lag20,
               l.i90_width_fraction, l.i90_width_fraction_lag20,
               l.i90_width_fraction_lag40,
               l.profit_ratio, l.profit_ratio_lag20, l.profit_ratio_lag40,
               l.lower_peak_strength, l.upper_peak_strength, l.valley_depth,
               l.lower_peak_strength_lag20, l.upper_peak_strength_lag20,
               l.valley_depth_lag20, l.known_cost_fraction_min,
               l.model_spread_i90_width_fraction
        FROM candidates c
        LEFT JOIN lagged l USING (symbol, trade_date)
        ORDER BY c.symbol, c.trade_date
    """


def _validate(path: Path, expected_rows: int) -> dict[str, Any]:
    con = duckdb.connect()
    try:
        row = con.execute(
            f"""
            SELECT count(*), count(DISTINCT candidate_id), count(DISTINCT symbol),
                   min(trade_date), max(trade_date),
                   count(*) FILTER (WHERE chip_measurement_valid),
                   count(*) FILTER (WHERE semantic_available_at > decision_at),
                   count(*) FILTER (WHERE exact_research_valid
                                           AND exact_p50 IS NULL),
                   count(*) FILTER (
                       WHERE exact_research_valid AND (
                           economic_share_product <= 0
                           OR abs(exact_p50 - (
                               exact_p50_raw * economic_share_product
                               + economic_cash_base
                           )) > 1e-9
                       )
                   )
            FROM read_parquet({_sql_text(str(path))})
            """
        ).fetchone()
        annual = con.execute(
            f"""
            SELECT year(trade_date)::INTEGER, count(*),
                   count(*) FILTER (WHERE chip_measurement_valid)
            FROM read_parquet({_sql_text(str(path))})
            GROUP BY 1 ORDER BY 1
            """
        ).fetchall()
    finally:
        con.close()
    if row is None or int(row[0]) != expected_rows or int(row[1]) != expected_rows:
        raise ValueError(f"feature cohort does not cover every candidate exactly once: {row}")
    if row[3] < datetime(2020, 1, 2).date() or row[4] > datetime(2022, 12, 30).date():
        raise ValueError("feature cohort escaped development dates")
    if int(row[6]) or int(row[7]) or int(row[8]):
        raise ValueError(f"feature cohort PIT or exact join failure: {row}")
    valid = int(row[5])
    if valid == 0:
        raise ValueError("feature cohort has zero measurable chip events")
    return {
        "rows": int(row[0]),
        "symbols": int(row[2]),
        "start": row[3].isoformat(),
        "end": row[4].isoformat(),
        "measurement_valid_rows": valid,
        "measurement_valid_ratio": valid / int(row[0]),
        "annual": {
            str(year): {
                "rows": int(rows),
                "measurement_valid_rows": int(valid_rows),
                "measurement_valid_ratio": int(valid_rows) / int(rows),
            }
            for year, rows, valid_rows in annual
        },
    }


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_list(paths: tuple[Path, ...]) -> str:
    return "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


if __name__ == "__main__":
    raise SystemExit(main())
