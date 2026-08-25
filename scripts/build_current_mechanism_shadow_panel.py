#!/usr/bin/env python3
"""Build the outcome-blind current warm-up panel for the frozen chip grid."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.data.registry import DataAssetRegistry, DataOperation, InputSnapshotManifest
from cyq_game.strategy.chip_incremental import fixed_chip_primitives

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_price_volume_candidate_cohort_v1 as legacy_candidates  # noqa: E402

PROTOCOL = ROOT / "configs/chip_mechanism_interaction_v1.json"
TRAINING = ROOT / "output/chip_mechanism_interaction_v1/training_v1/manifest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-snapshot", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "configs/data_asset_registry.json"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 8, 13))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 8, 24))
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _candidate_query(daily_files: tuple[Path, ...]) -> str:
    query = legacy_candidates._candidate_query(daily_files)  # noqa: SLF001
    source_old = "trade_date BETWEEN DATE '2018-01-01' AND DATE '2022-12-30'"
    target_old = "trade_date BETWEEN DATE '2020-01-02' AND DATE '2022-12-30'"
    if query.count(source_old) != 1 or query.count(target_old) != 1:
        raise ValueError("frozen price-volume query date anchors changed")
    return query.replace(
        source_old,
        "trade_date BETWEEN DATE '2025-01-01' AND DATE '2026-08-24'",
    ).replace(
        target_old,
        "trade_date BETWEEN DATE '2026-01-01' AND DATE '2026-08-24'",
    )


def _candidate_id(row: dict[str, Any]) -> str:
    trade_date = row["trade_date"]
    if isinstance(trade_date, datetime):
        trade_date = trade_date.date()
    identity = {
        "symbol": str(row["symbol"]),
        "trade_date": trade_date.isoformat(),
        "decision_at": row["decision_at"].isoformat(),
        "daily_snapshot_id": str(row["daily_snapshot_id"]),
        "definition": "PRICE_VOLUME_ONLY_BREAKOUT_RETEST_V1A1",
    }
    return "pv-candidate-" + hashlib.sha256(
        json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _select_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(key=lambda row: (row["symbol"], row["trade_date"]))
    selected: list[dict[str, Any]] = []
    last_session: dict[str, int] = {}
    selected_weeks: set[tuple[str, int, int]] = set()
    for row in rows:
        symbol = str(row["symbol"])
        session = int(row["symbol_session_index"])
        previous = last_session.get(symbol)
        iso = row["trade_date"].isocalendar()
        week = (symbol, iso.year, iso.week)
        if previous is not None and session - previous < 20:
            continue
        if week in selected_weeks:
            continue
        selected_row = dict(row)
        selected_row["candidate_id"] = _candidate_id(selected_row)
        selected_row["candidate_definition"] = "PRICE_VOLUME_ONLY_BREAKOUT_RETEST_V1A1"
        selected_row["candidate_uses_chip_fields"] = False
        selected.append(selected_row)
        last_session[symbol] = session
        selected_weeks.add(week)
    return selected


def _sql(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _feature_query(
    *, candidates: Path, semantic: Path, daily: Path, start: date, end: date
) -> str:
    return f"""
        WITH raw_daily AS (
            SELECT *, lag(close) OVER (PARTITION BY symbol ORDER BY trade_date)
                         AS previous_raw_close
            FROM read_parquet({_sql(daily)})
            WHERE trade_date <= DATE '{end.isoformat()}'
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
        ), joined AS (
            SELECT s.*, d.close, d.atr14, d.momentum_20,
                   s.exact_p50 * d.economic_share_product
                       + d.economic_cash_base AS comparable_exact_p50
            FROM read_parquet({_sql(semantic)}) s
            LEFT JOIN daily_features d USING (symbol, trade_date)
        ), lagged AS (
            SELECT *, lag(close, 20) OVER w AS close_lag20,
                   lag(atr14, 20) OVER w AS atr14_lag20,
                   lag(momentum_20, 20) OVER w AS momentum_20_lag20,
                   lag(comparable_exact_p50, 20) OVER w AS exact_p50_lag20,
                   lag(comparable_exact_p50, 40) OVER w AS exact_p50_lag40,
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
        SELECT c.*, l.* EXCLUDE (symbol, trade_date, close, exact_p50),
               l.close, l.comparable_exact_p50 AS exact_p50,
               l.research_valid AND l.exact_research_valid
                   AND l.available_at <= c.decision_at AS semantic_research_valid,
               l.exact_research_valid AND l.available_at <= c.decision_at
                   AS exact_source_research_valid
        FROM read_parquet({_sql(candidates)}) c
        LEFT JOIN lagged l USING (symbol, trade_date)
        WHERE c.trade_date BETWEEN DATE '{start.isoformat()}' AND DATE '{end.isoformat()}'
        ORDER BY c.symbol, c.trade_date
    """


def _matching_parameters(
    row: dict[str, Any], protocol: dict[str, Any]
) -> list[str]:
    if not row["chip_measurement_valid"]:
        return []
    if not (
        float(row["market_return_20"]) > 0
        and float(row["sector_return_20"]) > 0
        and float(row["close"]) >= float(row["exact_p50"])
        and float(row["profit_ratio_change_20"]) >= 0
        and float(row["i90_contraction_20"]) >= 0
    ):
        return []
    atr = float(row["atr14"])
    if atr <= 0 or (float(row["close"]) - float(row["i90_upper"])) / atr > 0.25:
        return []
    grids = protocol["mechanism_parameters"]
    matches: list[str] = []
    for migration in grids["cost_migration_floor_vol"]:
        for disagreement in grids["seller_model_disagreement_cap_atr"]:
            for overhead in grids["overhead_distance_cap_atr"]:
                if (
                    float(row["price_minus_cost_migration_20_vol"])
                    >= float(migration)
                    and float(row["seller_model_disagreement_atr"])
                    <= float(disagreement)
                    and (float(row["i90_upper"]) - float(row["close"])) / atr
                    <= float(overhead)
                ):
                    raw = f"{float(migration):.6f}|{float(disagreement):.6f}|{float(overhead):.6f}"
                    matches.append(hashlib.sha256(raw.encode()).hexdigest()[:16])
    return matches


def main() -> int:
    args = _parse_args()
    if args.start != date(2026, 8, 13) or args.end != date(2026, 8, 24):
        raise ValueError("v1 current warm-up range is frozen at 2026-08-13..2026-08-24")
    protocol = _read(PROTOCOL)
    training = _read(TRAINING)
    if training.get("decision") != "NO_TRADE" or training.get("promotion_authorized"):
        raise ValueError("current warm-up requires the frozen NO_TRADE decision")
    registry = DataAssetRegistry.load(args.registry.resolve())
    snapshot = InputSnapshotManifest.load(args.input_snapshot.resolve(), registry=registry)
    snapshot.authorize(DataOperation.STATE_GENERATION, registry=registry)
    daily_binding = snapshot.binding("daily_pit_b")
    semantic_binding = snapshot.binding("semantic_chip_current")
    daily_2025 = daily_binding.verify_file(
        daily_binding.path / "daily/partition_year=2025/data_0.parquet"
    )
    daily_2026 = daily_binding.verify_file(
        daily_binding.path / "daily/partition_year=2026/data_0.parquet"
    )
    semantic = semantic_binding.verify_file(
        semantic_binding.path / "semantic_features.parquet"
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    candidate_path = output / "candidate_events.parquet"
    connection = duckdb.connect()
    connection.execute("SET threads=4")
    result = connection.execute(_candidate_query((daily_2025, daily_2026)))
    assert result.description is not None
    columns = tuple(item[0] for item in result.description)
    raw_rows = [dict(zip(columns, values, strict=True)) for values in result.fetchall()]
    candidates = _select_candidates(raw_rows)
    if not candidates:
        raise RuntimeError("current fixed price-volume definition produced no candidates")
    pq.write_table(pa.Table.from_pylist(candidates), candidate_path, compression="zstd")
    joined = connection.execute(
        _feature_query(
            candidates=candidate_path,
            semantic=semantic,
            daily=daily_2026,
            start=args.start,
            end=args.end,
        )
    )
    assert joined.description is not None
    joined_columns = tuple(item[0] for item in joined.description)
    rows = [
        dict(zip(joined_columns, values, strict=True)) for values in joined.fetchall()
    ]
    connection.close()
    panel: list[dict[str, Any]] = []
    for row in rows:
        primitive_input = dict(row)
        primitive_input["exact_research_valid"] = row["exact_source_research_valid"]
        primitives = fixed_chip_primitives(primitive_input)
        enriched = {**row, **primitives}
        matches = _matching_parameters(enriched, protocol)
        enriched.update(
            matching_parameter_ids=matches,
            matching_parameter_count=len(matches),
            shadow_classification="PRE_SHADOW_WARMUP_ONLY",
            active_action="NO_TRADE",
        )
        panel.append(enriched)
    panel_path = output / "shadow_warmup_panel.parquet"
    if panel:
        pq.write_table(pa.Table.from_pylist(panel), panel_path, compression="zstd")
    measurable = sum(bool(row["chip_measurement_valid"]) for row in panel)
    manifest = {
        "schema_version": 1,
        "status": "COMPLETE_OUTCOME_BLIND_WARMUP",
        "classification": "PRE_SHADOW_WARMUP_ONLY",
        "active_action": "NO_TRADE",
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "candidate_rows": len(panel),
        "measurable_rows": measurable,
        "matching_rows": sum(int(row["matching_parameter_count"] > 0) for row in panel),
        "outcomes_accessed": False,
        "input_snapshot": {
            "path": str(snapshot.path),
            "sha256": snapshot.sha256,
            "manifest_id": snapshot.manifest_id,
        },
        "protocol_sha256": _sha256(PROTOCOL),
        "training_sha256": _sha256(TRAINING),
        "legacy_candidate_builder_sha256": _sha256(
            Path(legacy_candidates.__file__).resolve()
        ),
        "builder_sha256": _sha256(Path(__file__).resolve()),
        "candidate_events_sha256": _sha256(candidate_path),
        "panel_sha256": None if not panel else _sha256(panel_path),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
