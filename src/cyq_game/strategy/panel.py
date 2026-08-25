"""Build the reusable, causal predictor panel for MARKUP_RETEST v1.

The output deliberately contains no forward return, MFE, MAE, exit price or
other label.  Label construction lives in :mod:`cyq_game.strategy.labels` and
writes to a physically separate directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from cyq_game.chip.peak_versions import PEAK_DEFINITION_VERSION, PEAK_TRACK_VERSION
from cyq_game.data.registry import DataAssetRegistry
from cyq_game.strategy.markup_retest import (
    FORBIDDEN_SIGNAL_FIELDS,
    MarkupRetestConfig,
    StrategyStage,
    load_passing_frozen_parameters,
    verify_registered_asset_inventory,
)
from cyq_game.strategy.semantic_contract import (
    require_active_semantic_epoch,
    semantic_fingerprint_fields,
)


def _board_sql(symbol_expression: str = "symbol") -> str:
    return f"""
        CASE
            WHEN {symbol_expression} LIKE '300%'
              OR {symbol_expression} LIKE '301%'
              OR {symbol_expression} LIKE '302%'
            THEN 'CHINEXT'
            WHEN {symbol_expression} LIKE '%.SH' THEN 'MAIN_SH'
            ELSE 'MAIN_SZ'
        END
    """


def _main_chinext_scope_sql(symbol_expression: str = "symbol") -> str:
    prefix_markets = (
        ("000", "SZ"),
        ("001", "SZ"),
        ("002", "SZ"),
        ("003", "SZ"),
        ("300", "SZ"),
        ("301", "SZ"),
        ("302", "SZ"),
        ("600", "SH"),
        ("601", "SH"),
        ("603", "SH"),
        ("605", "SH"),
    )
    conditions = [
        f"{symbol_expression} LIKE '{prefix}___.{market}'"
        for prefix, market in prefix_markets
    ]
    return "(" + " OR ".join(conditions) + ")"


@dataclass(frozen=True)
class PanelBuildResult:
    stage: str
    status: str
    path: Path
    manifest_path: Path
    rows: int
    symbols: int
    eligible_rows: int
    strict_rows: int
    coverage: float
    config_sha256: str
    panel_snapshot_id: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        payload["manifest_path"] = str(self.manifest_path)
        return payload


@dataclass(frozen=True)
class CorporateActionInputs:
    """Frozen, verified QD-010 inputs consumed by the causal panel."""

    source_manifest_path: Path
    inventory_manifest_path: Path
    distributions_path: Path
    rights_path: Path
    source_manifest_sha256: str
    inventory_manifest_sha256: str
    distributions_sha256: str
    rights_sha256: str
    snapshot_id: str
    strict_pit_eligible: bool

    def source_inventory(self) -> list[dict[str, Any]]:
        return [
            _absolute_inventory_item(path, sha256)
            for path, sha256 in (
                (self.source_manifest_path, self.source_manifest_sha256),
                (self.inventory_manifest_path, self.inventory_manifest_sha256),
                (self.distributions_path, self.distributions_sha256),
                (self.rights_path, self.rights_sha256),
            )
        ]


def panel_path(config: MarkupRetestConfig, stage: StrategyStage | str) -> Path:
    boundary = config.stage(stage)
    return config.outputs.panel_root / boundary.name.value / config.sha256[:12]


def build_causal_panel(
    config: MarkupRetestConfig,
    stage: StrategyStage | str,
    *,
    reuse: bool = True,
    threads: int | None = None,
) -> PanelBuildResult:
    """Build one stage panel from explicit, year-partitioned registered inputs."""

    boundary = config.stage(stage)
    if boundary.name == StrategyStage.RESEALED:
        load_passing_frozen_parameters(config)
    builder_sha256 = _sha256(Path(__file__))
    corporate_actions = _resolve_corporate_action_inputs(config)
    source_input_inventory = [
        *corporate_actions.source_inventory(),
        verify_registered_asset_inventory(config, config.assets.daily_asset_id),
        verify_registered_asset_inventory(config, config.assets.chip_feature_asset_id),
    ]
    target = panel_path(config, boundary.name)
    manifest_path = target / "manifest.json"
    if reuse and manifest_path.is_file():
        return _load_manifest(
            manifest_path,
            expected_config_sha=config.sha256,
            expected_schema_version=config.panel_schema_version,
            expected_builder_sha=builder_sha256,
            expected_source_inventory=source_input_inventory,
        )
    if target.exists():
        raise FileExistsError(
            f"panel target exists without a reusable matching manifest: {target}"
        )

    daily_files = tuple(config.assets.daily_file(year) for year in boundary.years())
    feature_files = tuple(config.assets.feature_file(year) for year in boundary.years())
    all_inputs = (*daily_files, *feature_files)
    config.assert_input_files(boundary.name, all_inputs)
    missing = [str(path) for path in all_inputs if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing panel inputs: " + ", ".join(missing))

    temp = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    if temp.exists():
        shutil.rmtree(temp)
    temp.mkdir(parents=True)
    db_path = temp / "panel.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"PRAGMA threads={threads or max(1, (os.cpu_count() or 2) - 1)}")
        con.execute("PRAGMA memory_limit='24GB'")
        con.execute("PRAGMA preserve_insertion_order=false")
        _create_panel_table(
            con,
            config,
            boundary.name,
            daily_files,
            feature_files,
            corporate_actions,
        )
        _assert_predictor_schema(con)
        metrics = _panel_metrics(con, config, boundary.name)
        data_root = temp / "data"
        data_root.mkdir()
        escaped_root = _sql_text(str(data_root))
        con.execute(
            f"""
            COPY (
                SELECT *
                FROM causal_panel
                ORDER BY trade_date, symbol
            ) TO {escaped_root} (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                PARTITION_BY (partition_year, symbol_bucket)
            )
            """
        )
        from cyq_game.strategy.signals import _SIGNAL_INPUT_COLUMNS

        signal_scan_root = temp / "panel_signal_scan"
        signal_scan_root.mkdir()
        signal_columns = ", ".join(f'"{name}"' for name in _SIGNAL_INPUT_COLUMNS)
        con.execute(
            f"""
            COPY (
                SELECT {signal_columns}, symbol_bucket
                FROM causal_panel
                ORDER BY symbol_bucket, symbol, trade_date
            ) TO {_sql_text(str(signal_scan_root))} (
                FORMAT PARQUET,
                COMPRESSION ZSTD,
                PARTITION_BY (symbol_bucket)
            )
            """
        )
    finally:
        con.close()
        db_path.unlink(missing_ok=True)

    parquet_files = sorted((temp / "data").rglob("*.parquet")) + sorted(
        (temp / "panel_signal_scan").rglob("*.parquet")
    )
    if not parquet_files:
        shutil.rmtree(temp)
        raise RuntimeError("causal panel build produced no parquet files")
    inventory = [
        {
            "path": str(path.relative_to(temp)),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in parquet_files
    ]
    snapshot_payload = {
        **semantic_fingerprint_fields(),
        "schema_version": config.panel_schema_version,
        "strategy_version": config.strategy_version,
        "stage": boundary.name.value,
        "state_history_start": boundary.history_start.isoformat(),
        "warmup_policy": "PROCESS_HISTORY_SCORE_EVALUATION_ONLY",
        "config_sha256": config.sha256,
        "builder_sha256": builder_sha256,
        "input_paths": [str(path) for path in all_inputs],
        "source_input_inventory": source_input_inventory,
        "corporate_action_snapshot_id": corporate_actions.snapshot_id,
        "inventory": inventory,
        "metrics": metrics,
    }
    panel_snapshot_id = "panel-" + hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        "schema_version": config.panel_schema_version,
        "strategy_version": config.strategy_version,
        "status": "COMPLETE",
        "created_at": datetime.now(UTC).isoformat(),
        "stage": boundary.name.value,
        "evaluation_start": boundary.start.isoformat(),
        "evaluation_end": boundary.end.isoformat(),
        "state_history_start": boundary.history_start.isoformat(),
        "warmup_policy": "PROCESS_HISTORY_SCORE_EVALUATION_ONLY",
        "maximum_input_date": boundary.max_input_date.isoformat(),
        "config_sha256": config.sha256,
        "builder_sha256": builder_sha256,
        "panel_snapshot_id": panel_snapshot_id,
        "predictor_only": True,
        "label_directory": str(config.outputs.label_root),
        "forbidden_fields": sorted(FORBIDDEN_SIGNAL_FIELDS),
        "input_assets": {
            "daily": config.assets.daily_asset_id,
            "chip_features": config.assets.chip_feature_asset_id,
            "corporate_actions": config.assets.corporate_action_asset_id,
        },
        "input_paths": [str(path) for path in all_inputs],
        "source_input_inventory": source_input_inventory,
        "corporate_action_snapshot_id": corporate_actions.snapshot_id,
        "corporate_action_pit_grade": (
            "A" if corporate_actions.strict_pit_eligible else "B_RESEARCH_ONLY"
        ),
        "survivor_bias_disclosure": (
            "Research universe uses registered historical rows only. Delisted names are not "
            "silently imputed; no unregistered current-universe snapshot is consumed."
        ),
        "industry_policy": (
            "Causal last-known classification; missing classification falls back to board "
            "leave-one-out as B_RESEARCH_ONLY and never receives confidence 1."
        ),
        "inventory": inventory,
        "metrics": metrics,
    }
    (temp / "manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temp.rename(target)
    return _load_manifest(
        target / "manifest.json",
        expected_config_sha=config.sha256,
        expected_schema_version=config.panel_schema_version,
        expected_builder_sha=builder_sha256,
        expected_source_inventory=source_input_inventory,
    )


def _create_panel_table(
    con: duckdb.DuckDBPyConnection,
    config: MarkupRetestConfig,
    stage: StrategyStage,
    daily_files: tuple[Path, ...],
    feature_files: tuple[Path, ...],
    corporate_actions: CorporateActionInputs,
) -> None:
    boundary = config.stage(stage)
    daily_sql = _sql_list(daily_files)
    feature_sql = _sql_list(feature_files)
    symbol_filter = ""
    if boundary.symbols:
        symbol_filter = "AND d.symbol IN (" + ",".join(
            _sql_text(symbol) for symbol in boundary.symbols
        ) + ")"

    start = boundary.start.isoformat()
    end = boundary.end.isoformat()
    history_start = boundary.history_start.isoformat()
    maximum = boundary.max_input_date.isoformat()
    recent = config.windows.recent_evidence
    accumulation = config.windows.accumulation
    recent_floor = config.fixed.recent_band_overlap_floor
    mass_tol = config.quality.mass_tolerance
    support_tolerance = config.fixed.support_tolerance_atr
    current_industry_grade = _sql_text(config.quality.current_industry_grade)
    rights_sql = _sql_text(str(corporate_actions.rights_path))
    distributions_sql = _sql_text(str(corporate_actions.distributions_path))
    action_snapshot_id = _sql_text(corporate_actions.snapshot_id)
    action_strict_pit = "true" if corporate_actions.strict_pit_eligible else "false"
    action_pit_grade = _sql_text(
        "A" if corporate_actions.strict_pit_eligible else "B_RESEARCH_ONLY"
    )
    feature_columns = {
        str(row[0])
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet({feature_sql}, union_by_name=true)"
        ).fetchall()
    }
    _assert_unique_panel_input(
        con, source_sql=daily_sql, source_name="registered daily input"
    )
    _assert_unique_panel_input(
        con, source_sql=feature_sql, source_name="registered chip feature input"
    )

    def optional_feature(name: str) -> str:
        if name in feature_columns:
            return f"f.{name}"
        return f"CAST(NULL AS DOUBLE) AS {name}"

    dominant_band_lower_sql = optional_feature("dominant_band_lower")
    dominant_band_upper_sql = optional_feature("dominant_band_upper")
    dominant_band_mass_sql = optional_feature("dominant_band_mass")
    model_spread_cost_p50_sql = optional_feature("model_spread_cost_p50")
    model_spread_cost_p90_sql = optional_feature("model_spread_cost_p90")
    model_spread_main_peak_sql = optional_feature("model_spread_main_peak")
    model_spread_dominant_peak_sql = optional_feature(
        "model_spread_dominant_peak_today"
    )
    known_cost_fraction_min_sql = optional_feature("known_cost_fraction_min")
    tracked_base_peak_sql = optional_feature("tracked_base_peak")
    peak_track_band_lower_sql = optional_feature("peak_track_band_lower")
    peak_track_band_upper_sql = optional_feature("peak_track_band_upper")
    peak_track_mass_sql = optional_feature("peak_track_mass")
    peak_track_prominence_sql = optional_feature("peak_track_prominence")
    peak_track_id_sql = (
        "f.peak_track_id"
        if "peak_track_id" in feature_columns
        else "CAST(NULL AS VARCHAR) AS peak_track_id"
    )
    peak_track_ambiguous_sql = (
        "f.peak_track_ambiguous"
        if "peak_track_ambiguous" in feature_columns
        else "true AS peak_track_ambiguous"
    )
    peak_track_split_sql = (
        "f.peak_track_split"
        if "peak_track_split" in feature_columns
        else "true AS peak_track_split"
    )
    peak_track_merge_sql = (
        "f.peak_track_merge"
        if "peak_track_merge" in feature_columns
        else "true AS peak_track_merge"
    )
    peak_track_lost_sql = (
        "f.peak_track_lost"
        if "peak_track_lost" in feature_columns
        else "true AS peak_track_lost"
    )
    peak_definition_version_sql = (
        "f.peak_definition_version"
        if "peak_definition_version" in feature_columns
        else "CAST(NULL AS VARCHAR) AS peak_definition_version"
    )
    peak_track_version_sql = (
        "f.peak_track_version"
        if "peak_track_version" in feature_columns
        else "CAST(NULL AS VARCHAR) AS peak_track_version"
    )
    degraded_mode_sql = (
        "f.degraded_mode"
        if "degraded_mode" in feature_columns
        else "CAST(NULL AS VARCHAR) AS degraded_mode"
    )
    source_mode_sql = (
        "f.source_mode"
        if "source_mode" in feature_columns
        else "CAST(NULL AS VARCHAR) AS source_mode"
    )
    action_blocking_sql = (
        "f.action_blocking"
        if "action_blocking" in feature_columns
        else "true AS action_blocking"
    )
    action_provenance_sql = (
        "f.action_provenance"
        if "action_provenance" in feature_columns
        else "CAST(NULL AS VARCHAR) AS action_provenance"
    )
    if boundary.symbols:
        peer_sums_cte = f"""
        peer_universe AS (
            SELECT
                trade_date,
                nullif(nullif(trim(industry), ''), 'UNKNOWN') AS peer_industry,
                {_board_sql()} AS peer_board,
                CASE WHEN preclose > 0 THEN close / preclose - 1.0 END AS peer_return
            FROM read_parquet({daily_sql}, union_by_name=true)
            WHERE trade_date BETWEEN DATE '{history_start}' AND DATE '{maximum}'
        ), industry_peers AS (
            SELECT trade_date, peer_industry,
                   sum(peer_return) AS industry_return_sum,
                   count(peer_return) AS industry_return_count
            FROM peer_universe
            WHERE peer_industry IS NOT NULL
            GROUP BY trade_date, peer_industry
        ), board_peers AS (
            SELECT trade_date, peer_board,
                   sum(peer_return) AS board_return_sum,
                   count(peer_return) AS board_return_count
            FROM peer_universe
            GROUP BY trade_date, peer_board
        ), peer_sums AS (
            SELECT
                w.*,
                i.industry_return_sum,
                i.industry_return_count,
                b.board_return_sum,
                b.board_return_count
            FROM with_market w
            LEFT JOIN industry_peers i
              ON w.trade_date = i.trade_date
             AND w.effective_industry = i.peer_industry
            LEFT JOIN board_peers b
              ON w.trade_date = b.trade_date
             AND w.board = b.peer_board
        )
        """
    else:
        peer_sums_cte = """
        peer_sums AS (
            SELECT
                *,
                sum(stock_return) OVER (
                    PARTITION BY trade_date, effective_industry
                ) AS industry_return_sum,
                count(stock_return) OVER (
                    PARTITION BY trade_date, effective_industry
                ) AS industry_return_count,
                sum(stock_return) OVER (PARTITION BY trade_date, board)
                    AS board_return_sum,
                count(stock_return) OVER (PARTITION BY trade_date, board)
                    AS board_return_count
            FROM with_market
        )
        """

    # Each CTE layer exists to keep window expressions causal and non-nested.
    # Volatility scaling is known only through the prior completed session; no
    # decision-day high/low may change that day's threshold.
    con.execute(
        f"""
        CREATE TABLE causal_panel AS
        WITH base_joined AS (
            SELECT
                d.*,
                f.available_at AS feature_available_at,
                f.daily_snapshot_id AS feature_daily_snapshot_id,
                f.minute_snapshot_id AS feature_minute_snapshot_id,
                f.state_version,
                f.config_sha256 AS feature_config_sha256,
                f.code_sha256 AS feature_code_sha256,
                f.chip_input_valid,
                f.daily_hard_valid AS feature_daily_hard_valid,
                f.minute_hard_valid,
                f.state_chain_valid,
                {degraded_mode_sql},
                {source_mode_sql},
                {action_blocking_sql},
                {action_provenance_sql},
                f.warmup_count,
                f.strict_sample AS feature_strict_sample,
                f.mass_sum,
                f.state_quality,
                {known_cost_fraction_min_sql},
                f.profit_ratio,
                f.trapped_ratio,
                f.average_cost,
                f.p01,
                f.p10,
                f.p50,
                f.p90,
                f.p99,
                f.asr,
                f.space20,
                f.ckdp,
                f.ckdw,
                f.cbw,
                f.cyqk_open_pre,
                f.cyqk_close_pre,
                f.cyc5,
                f.cyc13,
                f.cyc34,
                f.cys13,
                f.cys34,
                f.rpy2,
                f.concentration_20,
                f.base_retention,
                f.peak_count,
                {dominant_band_lower_sql},
                {dominant_band_upper_sql},
                {dominant_band_mass_sql},
                {model_spread_cost_p50_sql},
                {model_spread_cost_p90_sql},
                {model_spread_main_peak_sql},
                {model_spread_dominant_peak_sql},
                {tracked_base_peak_sql},
                {peak_track_band_lower_sql},
                {peak_track_band_upper_sql},
                {peak_track_mass_sql},
                {peak_track_prominence_sql},
                {peak_track_id_sql},
                {peak_track_ambiguous_sql},
                {peak_track_split_sql},
                {peak_track_merge_sql},
                {peak_track_lost_sql},
                {peak_definition_version_sql},
                {peak_track_version_sql},
                f.opening_30m_return,
                f.closing_30m_return,
                f.close_vs_vwap,
                f.last_hour_volume_share,
                f.realized_volatility
            FROM read_parquet({daily_sql}, union_by_name=true) d
            INNER JOIN read_parquet({feature_sql}, union_by_name=true) f
              USING (symbol, trade_date)
            WHERE d.trade_date BETWEEN DATE '{history_start}' AND DATE '{maximum}'
              AND {_main_chinext_scope_sql('d.symbol')}
              {symbol_filter}
        ), raw_coordinate_input AS (
            SELECT
                *,
                lag(close) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                ) AS previous_raw_close
            FROM base_joined
        ), distribution_source AS (
            SELECT
                symbol, event_id, known_at, effective_date,
                coalesce(share_multiplier, 1.0) AS declared_share_multiplier,
                coalesce(cash_per_share_gross, 0.0) AS declared_cash_per_share,
                source_terms_complete, row_hash
            FROM read_parquet({distributions_sql})
            WHERE known_at IS NOT NULL
              AND effective_date IS NOT NULL
              AND known_at <= TIMESTAMP '{maximum} 15:30:00'
              AND effective_date >= TIMESTAMP '{history_start} 00:00:00'
        ), research_action_match AS (
            SELECT
                b.symbol,
                b.trade_date,
                r.event_id AS resolved_action_event_id,
                r.known_at AS resolved_action_known_at,
                r.declared_share_multiplier,
                r.declared_cash_per_share,
                (
                    b.previous_raw_close - r.declared_cash_per_share
                ) / r.declared_share_multiplier AS expected_action_preclose,
                abs(
                    b.preclose - (
                        b.previous_raw_close - r.declared_cash_per_share
                    ) / r.declared_share_multiplier
                ) AS action_preclose_error,
                r.row_hash AS resolved_action_row_hash
            FROM raw_coordinate_input b
            INNER JOIN distribution_source r
              ON split_part(b.symbol, '.', 1) = r.symbol
             AND b.trade_date = CAST(r.effective_date AS DATE)
             AND strpos(coalesce(b.corporate_action_ids, ''), r.event_id) > 0
            WHERE b.corporate_action_blocking
              AND r.known_at <= b.trade_date::TIMESTAMP + INTERVAL '15 hours 30 minutes'
              AND r.source_terms_complete
              AND r.declared_share_multiplier > 1.0
              AND b.previous_raw_close > r.declared_cash_per_share
              AND abs(
                    b.preclose - (
                        b.previous_raw_close - r.declared_cash_per_share
                    ) / r.declared_share_multiplier
                  ) <= greatest(0.02, b.preclose * 0.001)
            QUALIFY count(*) OVER (
                PARTITION BY b.symbol, b.trade_date
            ) = 1
        ), base_actions AS (
            SELECT
                b.* REPLACE (
                    CASE WHEN r.resolved_action_event_id IS NOT NULL
                         THEN false ELSE b.corporate_action_blocking
                    END AS corporate_action_blocking,
                    CASE WHEN r.resolved_action_event_id IS NOT NULL
                         THEN true ELSE b.corporate_action_valid
                    END AS corporate_action_valid,
                    coalesce(
                        r.declared_share_multiplier, b.share_multiplier
                    ) AS share_multiplier,
                    coalesce(
                        r.declared_cash_per_share, b.cash_per_share
                    ) AS cash_per_share
                ),
                r.resolved_action_event_id IS NOT NULL
                    AS research_action_price_reset_resolved,
                r.resolved_action_event_id,
                r.resolved_action_known_at,
                r.expected_action_preclose,
                r.action_preclose_error,
                r.resolved_action_row_hash
            FROM raw_coordinate_input b
            LEFT JOIN research_action_match r USING (symbol, trade_date)
        ), rights_source AS (
            SELECT
                symbol,
                event_id,
                known_at,
                effective_date,
                source_terms_complete,
                execution_timing_resolved,
                execution_resolved,
                resolution_status
            FROM read_parquet({rights_sql})
            WHERE known_at IS NOT NULL
              AND effective_date IS NOT NULL
              AND known_at <= TIMESTAMP '{maximum} 15:30:00'
              AND effective_date >= TIMESTAMP '{history_start} 00:00:00'
        ), announced_rights_by_day AS (
            SELECT
                b.symbol,
                b.trade_date,
                true AS announced_rights_blocking,
                string_agg(DISTINCT r.event_id, '|' ORDER BY r.event_id)
                    AS announced_rights_event_ids,
                max(r.known_at) AS announced_rights_available_at,
                bool_or(
                    NOT coalesce(r.source_terms_complete, false) OR
                    NOT coalesce(r.execution_timing_resolved, false) OR
                    NOT coalesce(r.execution_resolved, false) OR
                    coalesce(r.resolution_status, '') <> 'resolved'
                ) AS announced_rights_unresolved
            FROM base_actions b
            INNER JOIN rights_source r
              ON split_part(b.symbol, '.', 1) = r.symbol
             AND r.known_at <= b.trade_date::TIMESTAMP + INTERVAL '15 hours 30 minutes'
             AND b.trade_date < r.effective_date::DATE
            GROUP BY b.symbol, b.trade_date
        ), joined AS (
            SELECT
                b.*,
                coalesce(a.announced_rights_blocking, false)
                    AS announced_rights_blocking,
                a.announced_rights_event_ids,
                a.announced_rights_available_at,
                coalesce(a.announced_rights_unresolved, false)
                    AS announced_rights_unresolved
            FROM base_actions b
            LEFT JOIN announced_rights_by_day a USING (symbol, trade_date)
        ), coordinate_input AS (
            SELECT * FROM joined
        ), coordinate_factors AS (
            SELECT
                *,
                exp(sum(ln(
                    CASE
                        WHEN coalesce(corporate_action_count, 0) > 0
                         AND previous_raw_close > 0
                         AND preclose > 0
                        THEN preclose / previous_raw_close
                        ELSE 1.0
                    END
                )) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )) AS price_coordinate_factor
            FROM coordinate_input
        ), normalized_raw AS (
            SELECT
                *,
                trade_date::TIMESTAMP + INTERVAL '15 hours 30 minutes' AS strategy_decision_at,
                greatest(
                    available_at,
                    feature_available_at,
                    coalesce(announced_rights_available_at, available_at)
                ) AS strategy_available_at,
                corporate_action_blocking OR announced_rights_blocking
                    AS strategy_corporate_action_blocking,
                concat_ws('|', corporate_action_ids, announced_rights_event_ids)
                    AS strategy_corporate_action_ids,
                {_board_sql()} AS board,
                nullif(nullif(trim(industry), ''), 'UNKNOWN') AS observed_industry,
                CASE WHEN preclose > 0 THEN close / preclose - 1.0 END AS stock_return,
                greatest(
                    high - low,
                    abs(high - preclose),
                    abs(low - preclose)
                ) AS true_range,
                abs(close - preclose) / greatest(turnover_fraction, 1e-8) AS price_impact,
                CASE
                    WHEN trading_state_valid AND trade_status = 1 THEN true
                    ELSE false
                END AS tradable_state
            FROM coordinate_factors
        ), normalized AS (
            SELECT
                *,
                open / price_coordinate_factor AS analysis_open,
                high / price_coordinate_factor AS analysis_high,
                low / price_coordinate_factor AS analysis_low,
                close / price_coordinate_factor AS analysis_close,
                average_cost / price_coordinate_factor AS analysis_average_cost,
                p10 / price_coordinate_factor AS analysis_p10,
                p50 / price_coordinate_factor AS analysis_p50,
                p90 / price_coordinate_factor AS analysis_p90,
                dominant_band_lower / price_coordinate_factor
                    AS analysis_dominant_band_lower,
                dominant_band_upper / price_coordinate_factor
                    AS analysis_dominant_band_upper,
                true_range / price_coordinate_factor AS analysis_true_range,
                price_impact / price_coordinate_factor AS analysis_price_impact
            FROM normalized_raw
        ), chain_validity AS (
            SELECT
                *,
                (
                    strategy_available_at <= strategy_decision_at AND
                    bar_valid AND trading_state_valid AND float_valid AND
                    corporate_action_valid AND market_valid AND market_rule_valid AND
                    historical_identity_valid AND chip_input_valid AND state_chain_valid AND
                    NOT action_blocking AND
                    NOT strategy_corporate_action_blocking AND
                    abs(mass_sum - 1.0) <= {mass_tol} AND
                    known_cost_fraction_min IS NOT NULL AND
                    known_cost_fraction_min BETWEEN 0.0 AND 1.0 AND
                    peak_track_id IS NOT NULL AND
                    NOT peak_track_ambiguous AND
                    NOT peak_track_split AND
                    NOT peak_track_merge AND
                    NOT peak_track_lost AND
                    peak_definition_version = '{PEAK_DEFINITION_VERSION}' AND
                    peak_track_version = '{PEAK_TRACK_VERSION}'
                ) AS pre_chain_valid
            FROM normalized
        ), chain_epoch_rows AS (
            SELECT
                *,
                sum(CASE WHEN pre_chain_valid THEN 0 ELSE 1 END) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )::BIGINT AS chain_epoch
            FROM chain_validity
        ), valid_window_metrics AS (
            SELECT
                symbol,
                trade_date,
                chain_epoch,
                last_value(observed_industry IGNORE NULLS) OVER (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS effective_industry,
                last_value(
                    CASE WHEN observed_industry IS NOT NULL THEN industry_source END
                    IGNORE NULLS
                ) OVER (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS effective_industry_source,
                last_value(
                    CASE WHEN observed_industry IS NOT NULL THEN pit_grade END
                    IGNORE NULLS
                ) OVER (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS effective_industry_pit_grade,
                row_number() OVER (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                ) AS history_count,
                lag(analysis_close, 20) OVER symbol_window AS close_lag20,
                lag(analysis_average_cost, {recent}) OVER symbol_window
                    * price_coordinate_factor AS average_cost_lag20,
                lag(analysis_p50, {recent}) OVER symbol_window
                    * price_coordinate_factor AS p50_lag20,
                lag(asr, {recent}) OVER symbol_window AS asr_lag20,
                lag(cbw, {recent}) OVER symbol_window AS cbw_lag20,
                lag(concentration_20, {recent}) OVER symbol_window AS concentration_lag20,
                lag(peak_count, {recent}) OVER symbol_window AS peak_count_lag20,
                lag(peak_track_id, {recent}) OVER symbol_window AS peak_track_id_lag20,
                lag(analysis_p10, {recent}) OVER symbol_window
                    * price_coordinate_factor AS p10_lag20,
                lag(analysis_p90, {recent}) OVER symbol_window
                    * price_coordinate_factor AS p90_lag20,
                lag(analysis_p10, 5) OVER symbol_window
                    * price_coordinate_factor AS p10_lag5,
                lag(analysis_p90, 5) OVER symbol_window
                    * price_coordinate_factor AS p90_lag5,
                lag(cbw, 5) OVER symbol_window AS cbw_lag5,
                lag(peak_count, 5) OVER symbol_window AS peak_count_lag5,
                lag(analysis_dominant_band_lower) OVER symbol_window
                    * price_coordinate_factor AS prior_dominant_band_lower,
                lag(analysis_dominant_band_upper) OVER symbol_window
                    * price_coordinate_factor AS prior_dominant_band_upper,
                lag(peak_track_id) OVER symbol_window AS prior_peak_track_id,
                lag(analysis_p50) OVER symbol_window
                    * price_coordinate_factor AS prior_p50,
                lag(analysis_p90) OVER symbol_window
                    * price_coordinate_factor AS prior_p90,
                lag(analysis_average_cost) OVER symbol_window
                    * price_coordinate_factor AS prior_average_cost,
                avg(analysis_true_range) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
                ) * price_coordinate_factor AS atr14,
                avg(turnover_fraction) OVER recent_window AS turnover_mean20,
                avg(amount) OVER recent_window AS amount_mean20,
                avg(analysis_price_impact) OVER recent_window AS price_impact_mean20,
                quantile_cont(
                    turnover_fraction,
                    {config.fixed.high_turnover_quantile}
                ) OVER accumulation_prior AS turnover_q60_prior,
                quantile_cont(
                    analysis_price_impact,
                    {config.fixed.low_price_impact_quantile}
                ) OVER accumulation_prior AS impact_q50_prior,
                max(analysis_high) OVER accumulation_prior
                    * price_coordinate_factor AS causal_price_resistance,
                avg(last_hour_volume_share) OVER recent_window AS tail_volume_mean20,
                avg(realized_volatility) OVER recent_window AS realized_vol_mean20
            FROM chain_epoch_rows
            WHERE pre_chain_valid
            WINDOW
                symbol_window AS (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                ),
                recent_window AS (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                    ROWS BETWEEN {recent - 1} PRECEDING AND CURRENT ROW
                ),
                accumulation_prior AS (
                    PARTITION BY symbol, chain_epoch ORDER BY trade_date
                    ROWS BETWEEN {accumulation} PRECEDING AND 1 PRECEDING
                )
        ), causal_industry AS (
            SELECT
                c.*,
                v.* EXCLUDE (symbol, trade_date, chain_epoch)
            FROM chain_epoch_rows c
            LEFT JOIN valid_window_metrics v
              USING (symbol, trade_date, chain_epoch)
        ), market_series AS (
            SELECT DISTINCT
                trade_date,
                index_symbol,
                market_close
            FROM causal_industry
            WHERE index_symbol IS NOT NULL AND market_close IS NOT NULL
        ), market_daily AS (
            SELECT
                trade_date,
                index_symbol,
                CASE
                    WHEN lag(market_close) OVER (
                        PARTITION BY index_symbol ORDER BY trade_date
                    ) > 0
                    THEN market_close / lag(market_close) OVER (
                        PARTITION BY index_symbol ORDER BY trade_date
                    ) - 1.0
                END AS market_return
            FROM market_series
        ), with_market AS (
            SELECT
                causal_industry.*,
                market_daily.market_return
            FROM causal_industry
            LEFT JOIN market_daily USING (trade_date, index_symbol)
        ), {peer_sums_cte}, retention_semantics AS (
            SELECT
                *,
                CASE
                    WHEN p90_lag20 > p10_lag20 THEN least(
                        1.0,
                        greatest(
                            0.0,
                            least(p90, p90_lag20) - greatest(p10, p10_lag20)
                        ) / (p90_lag20 - p10_lag20)
                    )
                END AS recent_band_overlap,
                CASE
                    WHEN p90_lag5 > p10_lag5 THEN least(
                        1.0,
                        greatest(
                            0.0,
                            least(p90, p90_lag5) - greatest(p10, p10_lag5)
                        ) / (p90_lag5 - p10_lag5)
                    )
                END AS short_band_overlap
            FROM peer_sums
        ), evidence AS (
            SELECT
                *,
                CASE
                    WHEN effective_industry IS NOT NULL AND industry_return_count > 1
                    THEN (industry_return_sum - stock_return) / (industry_return_count - 1)
                    WHEN board_return_count > 1
                    THEN (board_return_sum - stock_return) / (board_return_count - 1)
                END AS sector_return_loo,
                CASE
                    WHEN effective_industry IS NOT NULL AND industry_return_count > 1
                    THEN 'INDUSTRY_LOO'
                    WHEN board_return_count > 1
                    THEN 'BOARD_LOO'
                    ELSE 'UNAVAILABLE'
                END AS sector_fallback,
                CASE
                    WHEN effective_industry IS NOT NULL AND industry_return_count >= 5 THEN 0.90
                    WHEN effective_industry IS NOT NULL AND industry_return_count > 1 THEN 0.70
                    WHEN board_return_count > 1 THEN 0.50
                    ELSE 0.0
                END AS sector_confidence,
                CASE
                    WHEN peak_track_id IS NOT NULL AND NOT peak_track_ambiguous
                    THEN greatest(peak_track_band_upper, causal_price_resistance)
                END AS structure_support,
                CASE WHEN atr14 > 0 THEN
                    (
                        close - CASE
                            WHEN peak_track_id IS NOT NULL AND NOT peak_track_ambiguous
                            THEN greatest(peak_track_band_upper, causal_price_resistance)
                        END
                    ) / atr14
                END AS breakout_excess_atr,
                (
                    turnover_mean20 >= turnover_q60_prior AND
                    price_impact_mean20 <= impact_q50_prior
                ) AS ev_turnover_absorption,
                (asr > asr_lag20 AND profit_ratio >= 0.45) AS ev_near_price_chip_growth,
                (
                    cbw <= cbw_lag20 AND
                    concentration_20 >= concentration_lag20 AND
                    peak_count <= peak_count_lag20 + 1
                ) AS ev_concentration_improves,
                (
                    peak_track_id = peak_track_id_lag20 AND
                    recent_band_overlap >= {recent_floor} AND
                    abs(p50 - p50_lag20) <= greatest(atr14, 1e-8)
                ) AS ev_sticky_base,
                (
                    close_vs_vwap >= 0 AND closing_30m_return >= 0
                ) AS ev_downside_absorption,
                CAST(NULL AS BOOLEAN) AS dist_base_loss,
                'UNKNOWN' AS exact_lineage_state,
                (cbw > cbw_lag5 * 1.10) AS dist_cost_band_expands,
                (peak_count >= peak_count_lag5 + 2) AS dist_peak_splits,
                (
                    turnover_fraction >= turnover_q60_prior AND
                    stock_return <= coalesce(market_return, 0)
                ) AS dist_high_turnover_weak_impact,
                (
                    stock_return < coalesce(market_return, 0) - 0.01 AND
                    stock_return < coalesce(
                        CASE WHEN effective_industry IS NOT NULL AND industry_return_count > 1
                             THEN (industry_return_sum - stock_return) / (industry_return_count - 1)
                             WHEN board_return_count > 1
                             THEN (board_return_sum - stock_return) / (board_return_count - 1)
                        END,
                        0
                    ) - 0.01
                ) AS dist_relative_reversal,
                pre_chain_valid AS research_hard_valid,
                (
                    pre_chain_valid AND
                    hard_valid AND feature_strict_sample AND
                    {action_strict_pit} AND
                    NOT strategy_corporate_action_blocking AND
                    effective_industry IS NOT NULL AND
                    NOT regexp_matches(
                        lower(coalesce(effective_industry_source, '')),
                        'current|static|snapshot'
                    ) AND
                    upper(coalesce(effective_industry_pit_grade, '')) = 'A' AND
                    abs(mass_sum - 1.0) <= {mass_tol}
                ) AS strict_hard_valid
            FROM retention_semantics
        ), regime AS (
            SELECT
                *,
                exp(sum(ln(greatest(1.0 + coalesce(market_return, 0.0), 1e-8))) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                )) - 1.0 AS market_return_20,
                exp(sum(ln(greatest(1.0 + coalesce(sector_return_loo, 0.0), 1e-8))) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                )) - 1.0 AS sector_return_20
            FROM evidence
        ), scored AS (
            SELECT
                *,
                (
                    ev_turnover_absorption::INTEGER +
                    ev_near_price_chip_growth::INTEGER +
                    ev_concentration_improves::INTEGER +
                    ev_sticky_base::INTEGER +
                    ev_downside_absorption::INTEGER
                ) / 5.0 AS setup_score,
                (
                    coalesce(dist_base_loss::INTEGER, 0) +
                    dist_cost_band_expands::INTEGER +
                    dist_peak_splits::INTEGER +
                    dist_high_turnover_weak_impact::INTEGER +
                    dist_relative_reversal::INTEGER
                ) / 5.0 AS distribution_score
            FROM regime
        )
        SELECT
            symbol,
            trade_date,
            strategy_decision_at AS decision_at,
            '+08:00' AS decision_timezone,
            strategy_available_at AS available_at,
            daily_snapshot_id,
            feature_daily_snapshot_id,
            feature_minute_snapshot_id,
            state_version,
            feature_config_sha256,
            feature_code_sha256,
            '{config.sha256}' AS strategy_config_sha256,
            '{config.strategy_version}' AS strategy_version,
            board,
            observed_industry,
            effective_industry AS industry,
            effective_industry_source AS industry_source,
            effective_industry_pit_grade,
            CASE
                WHEN effective_industry IS NULL THEN {current_industry_grade}
                WHEN regexp_matches(
                    lower(coalesce(effective_industry_source, '')),
                    'current|static|snapshot'
                ) THEN {current_industry_grade}
                ELSE effective_industry_pit_grade
            END AS industry_pit_grade,
            history_count,
            chain_epoch,
            pre_chain_valid,
            tradable_state,
            sector_fallback,
            sector_confidence,
            sector_return_loo,
            CASE
                WHEN market_return_20 > 0.02 THEN 'RISK_ON'
                WHEN market_return_20 < -0.02 THEN 'RISK_OFF'
                ELSE 'NEUTRAL'
            END AS market_state,
            CASE
                WHEN sector_return_20 > 0.02 THEN 'STRONG'
                WHEN sector_return_20 < -0.02 THEN 'WEAK'
                ELSE 'NEUTRAL'
            END AS sector_state,
            open, high, low, close, preclose, volume, amount,
            turnover_fraction, trade_status, is_st, up_limit_price, down_limit_price,
            buy_blocked_open, sell_blocked_open, corporate_action_count,
            strategy_corporate_action_ids AS corporate_action_ids,
            strategy_corporate_action_blocking AS corporate_action_blocking,
            announced_rights_blocking,
            announced_rights_event_ids,
            announced_rights_available_at,
            announced_rights_unresolved,
            {action_snapshot_id} AS corporate_action_snapshot_id,
            {action_pit_grade} AS corporate_action_pit_grade,
            research_action_price_reset_resolved,
            resolved_action_event_id,
            resolved_action_known_at,
            expected_action_preclose,
            action_preclose_error,
            resolved_action_row_hash,
            share_multiplier,
            cash_per_share, rights_ratio, rights_price,
            market_rule_id, market_return, market_return_20, stock_return,
            sector_return_20,
            industry_return_sum, industry_return_count,
            board_return_sum, board_return_count,
            amount_mean20,
            price_coordinate_factor,
            analysis_close,
            CASE WHEN close_lag20 > 0 THEN analysis_close / close_lag20 - 1.0 END
                AS momentum_20,
            atr14 AS atr,
            average_cost,
            p01 AS cost_p01,
            p10 AS cost_p10,
            p50 AS cost_p50,
            p90 AS cost_p90,
            p99 AS cost_p99,
            prior_average_cost, prior_p50 AS prior_cost_p50,
            dominant_band_lower,
            dominant_band_upper,
            dominant_band_mass,
            prior_dominant_band_lower,
            prior_dominant_band_upper,
            model_spread_cost_p50,
            model_spread_cost_p90,
            model_spread_main_peak,
            model_spread_dominant_peak_today,
            tracked_base_peak,
            peak_track_band_lower,
            peak_track_band_upper,
            peak_track_mass,
            peak_track_prominence,
            peak_track_id,
            peak_track_ambiguous,
            peak_track_split,
            peak_track_merge,
            peak_track_lost,
            peak_definition_version,
            peak_track_version,
            prior_peak_track_id,
            peak_track_id_lag20,
            known_cost_fraction_min,
            degraded_mode,
            source_mode,
            action_blocking,
            action_provenance,
            CASE WHEN peak_track_band_upper IS NOT NULL
                 AND peak_track_id IS NOT NULL
                 AND NOT peak_track_ambiguous
                 THEN 'TRACKED_BASE_PEAK_BAND'
                 ELSE 'UNAVAILABLE'
            END AS breakout_cost_ceiling_source,
            profit_ratio, trapped_ratio, asr, cbw, concentration_20,
            base_retention AS source_base_retention,
            recent_band_overlap,
            short_band_overlap,
            peak_count, state_quality, mass_sum,
            opening_30m_return, closing_30m_return, close_vs_vwap,
            last_hour_volume_share, realized_volatility,
            structure_support,
            breakout_excess_atr,
            close >= structure_support - {support_tolerance} * greatest(atr14, 1e-8)
                AND close_vs_vwap >= 0 AS support_regained,
            close < structure_support - 1.5 * greatest(atr14, 1e-8)
                AS structure_broken,
            setup_score,
            distribution_score,
            ev_turnover_absorption,
            ev_near_price_chip_growth,
            ev_concentration_improves,
            ev_sticky_base,
            ev_downside_absorption,
            dist_base_loss,
            exact_lineage_state,
            dist_cost_band_expands,
            dist_peak_splits,
            dist_high_turnover_weak_impact,
            dist_relative_reversal,
            research_hard_valid,
            strict_hard_valid,
            research_hard_valid AND NOT strategy_corporate_action_blocking
                AND history_count >= {accumulation} AND atr14 > 0
                AND tradable_state AS strategy_eligible,
            trade_date BETWEEN DATE '{start}' AND DATE '{end}' AS is_evaluation_row,
            concat_ws('|',
                CASE WHEN strategy_available_at > strategy_decision_at THEN 'TIME_TRAVEL' END,
                CASE WHEN NOT bar_valid THEN 'BAR_INVALID' END,
                CASE WHEN NOT trading_state_valid THEN 'TRADING_STATE_UNKNOWN' END,
                CASE WHEN NOT float_valid THEN 'FLOAT_UNKNOWN' END,
                CASE WHEN NOT corporate_action_valid THEN 'CORPORATE_ACTION_UNKNOWN' END,
                CASE
                    WHEN strategy_corporate_action_blocking
                    THEN 'CORPORATE_ACTION_BLOCKING'
                END,
                CASE
                    WHEN announced_rights_blocking
                    THEN 'ANNOUNCED_RIGHTS_PRE_EX'
                END,
                CASE
                    WHEN announced_rights_unresolved
                    THEN 'RIGHTS_EXECUTION_UNRESOLVED'
                END,
                CASE WHEN NOT market_valid THEN 'MARKET_INVALID' END,
                CASE WHEN NOT market_rule_valid THEN 'MARKET_RULE_UNKNOWN' END,
                CASE WHEN NOT historical_identity_valid THEN 'IDENTITY_UNKNOWN' END,
                CASE WHEN NOT chip_input_valid THEN 'CHIP_INPUT_INVALID' END,
                CASE WHEN NOT state_chain_valid THEN 'STATE_CHAIN_INVALID' END,
                CASE WHEN abs(mass_sum - 1.0) > {mass_tol} THEN 'CHIP_MASS_NOT_CONSERVED' END,
                CASE WHEN effective_industry IS NULL THEN 'INDUSTRY_BOARD_FALLBACK' END,
                CASE
                    WHEN effective_industry IS NOT NULL AND (
                        regexp_matches(
                            lower(coalesce(effective_industry_source, '')),
                            'current|static|snapshot'
                        ) OR upper(coalesce(effective_industry_pit_grade, '')) <> 'A'
                    ) THEN 'INDUSTRY_B_RESEARCH_ONLY'
                END,
                CASE WHEN history_count < {accumulation} THEN 'ACCUMULATION_WARMUP' END,
                CASE WHEN NOT tradable_state THEN 'NOT_TRADABLE_AT_DECISION' END
            ) AS reason_codes,
            year(trade_date)::INTEGER AS partition_year,
            abs(hash(symbol) % 32)::INTEGER AS symbol_bucket
        FROM scored
        WHERE trade_date BETWEEN DATE '{history_start}' AND DATE '{end}'
        """
    )


def _assert_unique_panel_input(
    con: duckdb.DuckDBPyConnection, *, source_sql: str, source_name: str
) -> None:
    duplicate = con.execute(
        f"""
        SELECT symbol, trade_date, count(*) AS row_count
        FROM read_parquet({source_sql}, union_by_name=true)
        GROUP BY symbol, trade_date
        HAVING count(*) <> 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise ValueError(
            f"{source_name} is not unique on (symbol, trade_date): {duplicate}"
        )


def _assert_predictor_schema(con: duckdb.DuckDBPyConnection) -> None:
    columns = {row[1] for row in con.execute("PRAGMA table_info('causal_panel')").fetchall()}
    overlap = sorted(columns.intersection(FORBIDDEN_SIGNAL_FIELDS))
    if overlap:
        raise RuntimeError("predictor panel contains forbidden label fields: " + ", ".join(overlap))
    required = {
        "symbol",
        "trade_date",
        "decision_at",
        "available_at",
        "setup_score",
        "breakout_excess_atr",
        "distribution_score",
        "industry_pit_grade",
        "history_count",
        "tradable_state",
        "research_hard_valid",
        "strategy_eligible",
        "corporate_action_snapshot_id",
        "corporate_action_pit_grade",
        "announced_rights_blocking",
        "is_evaluation_row",
    }
    missing = sorted(required - columns)
    if missing:
        raise RuntimeError("predictor panel missing required fields: " + ", ".join(missing))
    time_travel = _fetch_one(
        con,
        "SELECT count(*) FROM causal_panel WHERE available_at > decision_at",
    )[0]
    if time_travel:
        raise RuntimeError(f"causal panel contains {time_travel} future-available rows")
    _assert_industry_features(con)
    _assert_corporate_action_features(con)


def _assert_corporate_action_features(con: duckdb.DuckDBPyConnection) -> None:
    """Fail closed when announced actions leak through a risk or PIT gate."""

    failures = _fetch_one(
        con,
        """
        SELECT
            count(*) FILTER (
                WHERE announced_rights_blocking AND NOT corporate_action_blocking
            ) AS rights_not_combined,
            count(*) FILTER (
                WHERE announced_rights_blocking AND strategy_eligible
            ) AS rights_risk_allowed,
            count(*) FILTER (
                WHERE announced_rights_blocking AND (
                    nullif(announced_rights_event_ids, '') IS NULL OR
                    announced_rights_available_at IS NULL OR
                    corporate_action_snapshot_id IS NULL
                )
            ) AS rights_lineage_missing,
            count(*) FILTER (
                WHERE announced_rights_blocking
                  AND available_at < announced_rights_available_at
            ) AS rights_available_at_ignored,
            count(*) FILTER (
                WHERE corporate_action_pit_grade <> 'A' AND strict_hard_valid
            ) AS non_strict_source_marked_strict,
            count(*) FILTER (
                WHERE corporate_action_blocking AND strict_hard_valid
            ) AS blocker_marked_strict
        FROM causal_panel
        """,
    )
    names = (
        "rights_not_combined",
        "rights_risk_allowed",
        "rights_lineage_missing",
        "rights_available_at_ignored",
        "non_strict_source_marked_strict",
        "blocker_marked_strict",
    )
    violated = [
        f"{name}={count}"
        for name, count in zip(names, failures, strict=True)
        if count
    ]
    if violated:
        raise RuntimeError(
            "corporate-action causal feature audit failed: " + ", ".join(violated)
        )


def _assert_industry_features(con: duckdb.DuckDBPyConnection) -> None:
    """Recompute causal ASOF and leave-one-out invariants from panel columns."""

    failures = _fetch_one(
        con,
        """
        WITH checked AS (
            SELECT
                *,
                lag(industry) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                ) AS previous_industry
            FROM causal_panel
        )
        SELECT
            count(*) FILTER (
                WHERE observed_industry IS NOT NULL
                  AND industry IS DISTINCT FROM observed_industry
            ) AS observed_not_effective,
            count(*) FILTER (
                WHERE observed_industry IS NULL
                  AND previous_industry IS NOT NULL
                  AND industry IS DISTINCT FROM previous_industry
            ) AS asof_not_carried,
            count(*) FILTER (
                WHERE sector_fallback = 'INDUSTRY_LOO' AND (
                    industry IS NULL OR industry_return_count <= 1 OR
                    sector_return_loo IS NULL OR
                    abs(
                        sector_return_loo -
                        (industry_return_sum - stock_return) /
                        (industry_return_count - 1)
                    ) > 1e-12
                )
            ) AS industry_loo_invalid,
            count(*) FILTER (
                WHERE sector_fallback = 'BOARD_LOO' AND (
                    board_return_count <= 1 OR sector_return_loo IS NULL OR
                    abs(
                        sector_return_loo -
                        (board_return_sum - stock_return) /
                        (board_return_count - 1)
                    ) > 1e-12
                )
            ) AS board_loo_invalid,
            count(*) FILTER (
                WHERE sector_fallback = 'UNAVAILABLE' AND (
                    sector_return_loo IS NOT NULL OR sector_confidence <> 0.0
                )
            ) AS unavailable_invalid,
            count(*) FILTER (
                WHERE sector_fallback NOT IN (
                    'INDUSTRY_LOO', 'BOARD_LOO', 'UNAVAILABLE'
                )
            ) AS fallback_unknown,
            count(*) FILTER (
                WHERE sector_confidence < 0.0 OR sector_confidence > 0.90
            ) AS confidence_invalid
        FROM checked
        """,
    )
    names = (
        "observed_not_effective",
        "asof_not_carried",
        "industry_loo_invalid",
        "board_loo_invalid",
        "unavailable_invalid",
        "fallback_unknown",
        "confidence_invalid",
    )
    violated = [
        f"{name}={count}"
        for name, count in zip(names, failures, strict=True)
        if count
    ]
    if violated:
        raise RuntimeError("industry causal feature audit failed: " + ", ".join(violated))


def _panel_metrics(
    con: duckdb.DuckDBPyConnection,
    config: MarkupRetestConfig,
    stage: StrategyStage,
) -> dict[str, Any]:
    row = _fetch_one(
        con,
        """
        SELECT
            count(*) FILTER (WHERE is_evaluation_row) AS rows,
            count(DISTINCT symbol) FILTER (WHERE is_evaluation_row) AS symbols,
            count(*) FILTER (
                WHERE is_evaluation_row AND strategy_eligible
            ) AS eligible_rows,
            count(*) FILTER (
                WHERE is_evaluation_row AND strict_hard_valid
            ) AS strict_rows,
            count(*) FILTER (
                WHERE is_evaluation_row AND industry IS NULL
            ) AS board_fallback_rows,
            count(DISTINCT symbol) FILTER (
                WHERE is_evaluation_row AND industry IS NULL
            ) AS board_fallback_symbols,
            count(*) FILTER (WHERE reason_codes LIKE '%CHIP_MASS_NOT_CONSERVED%') AS mass_failures,
            min(trade_date) AS minimum_date,
            max(trade_date) AS maximum_date,
            count(*) AS state_rows,
            count(DISTINCT symbol) AS state_symbols
        FROM causal_panel
        """,
    )
    coverage_denominator, coverage_numerator = _fetch_one(
        con,
        """
        SELECT
            count(*) FILTER (
                WHERE in_market_row
            ),
            count(*) FILTER (
                WHERE in_market_row AND research_hard_valid
            )
        FROM (
            SELECT
                research_hard_valid,
                reason_codes NOT LIKE '%IDENTITY_UNKNOWN%' AS in_market_row
            FROM causal_panel
            WHERE is_evaluation_row
        )
        """,
    )
    coverage = (
        float(coverage_numerator) / float(coverage_denominator)
        if coverage_denominator
        else 0.0
    )
    if row[6] != 0:
        raise RuntimeError(f"chip mass conservation failed on {row[6]} rows")
    return {
        "rows": int(row[0]),
        "symbols": int(row[1]),
        "eligible_rows": int(row[2]),
        "strict_rows": int(row[3]),
        "board_fallback_rows": int(row[4]),
        "board_fallback_symbols": int(row[5]),
        "mass_failures": int(row[6]),
        "minimum_date": row[7].isoformat() if row[7] else None,
        "maximum_date": row[8].isoformat() if row[8] else None,
        "state_rows": int(row[9]),
        "state_symbols": int(row[10]),
        "coverage_definition": (
            "research_hard_valid / registered in-market rows; suspensions count as covered"
        ),
        "coverage_denominator": int(coverage_denominator),
        "coverage_numerator": int(coverage_numerator),
        "coverage": coverage,
        "coverage_gate": coverage >= config.quality.minimum_board_coverage,
        "stage": stage.value,
    }


def _load_manifest(
    path: Path,
    *,
    expected_config_sha: str,
    expected_schema_version: int,
    expected_builder_sha: str,
    expected_source_inventory: list[dict[str, Any]],
) -> PanelBuildResult:
    payload = json.loads(path.read_text())
    require_active_semantic_epoch(payload, artifact_name="panel")
    if payload.get("status") != "COMPLETE":
        raise ValueError(f"panel manifest is not complete: {path}")
    if payload.get("config_sha256") != expected_config_sha:
        raise ValueError(f"panel config hash mismatch: {path}")
    if payload.get("schema_version") != expected_schema_version:
        raise ValueError(f"panel schema version mismatch: {path}")
    if payload.get("builder_sha256") != expected_builder_sha:
        raise ValueError(f"panel builder hash mismatch: {path}")
    _verify_inventory(path.parent, payload)
    _verify_source_inventory(payload, expected_source_inventory)
    snapshot_payload = {
        **semantic_fingerprint_fields(),
        "schema_version": payload.get("schema_version"),
        "strategy_version": payload.get("strategy_version"),
        "stage": payload.get("stage"),
        "state_history_start": payload.get("state_history_start"),
        "warmup_policy": payload.get("warmup_policy"),
        "config_sha256": payload.get("config_sha256"),
        "builder_sha256": payload.get("builder_sha256"),
        "input_paths": payload.get("input_paths"),
        "source_input_inventory": payload.get("source_input_inventory"),
        "corporate_action_snapshot_id": payload.get(
            "corporate_action_snapshot_id"
        ),
        "inventory": payload.get("inventory"),
        "metrics": payload.get("metrics"),
    }
    expected_snapshot = "panel-" + hashlib.sha256(
        json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if payload.get("panel_snapshot_id") != expected_snapshot:
        raise ValueError(f"panel snapshot hash mismatch: {path}")
    metrics = payload["metrics"]
    return PanelBuildResult(
        stage=str(payload["stage"]),
        status=str(payload["status"]),
        path=path.parent / "data",
        manifest_path=path,
        rows=int(metrics["rows"]),
        symbols=int(metrics["symbols"]),
        eligible_rows=int(metrics["eligible_rows"]),
        strict_rows=int(metrics["strict_rows"]),
        coverage=float(metrics["coverage"]),
        config_sha256=str(payload["config_sha256"]),
        panel_snapshot_id=str(payload["panel_snapshot_id"]),
    )


def _sql_list(paths: tuple[Path, ...]) -> str:
    return "[" + ",".join(_sql_text(str(path)) for path in paths) + "]"


def _fetch_one(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[Any, ...]:
    row = con.execute(sql).fetchone()
    if row is None:
        raise RuntimeError("query unexpectedly returned no row")
    return row


def _verify_inventory(root: Path, payload: dict[str, Any]) -> None:
    inventory = payload.get("inventory")
    if not isinstance(inventory, list) or not inventory:
        raise ValueError(f"artifact inventory is missing or empty: {root}")
    for raw_item in inventory:
        if not isinstance(raw_item, dict):
            raise ValueError(f"invalid artifact inventory entry: {root}")
        relative = Path(str(raw_item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe artifact inventory path: {relative}")
        artifact = root / relative
        if not artifact.is_file():
            raise ValueError(f"artifact inventory path is missing: {artifact}")
        if artifact.stat().st_size != raw_item.get("size"):
            raise ValueError(f"artifact inventory size mismatch: {artifact}")
        if _sha256(artifact) != raw_item.get("sha256"):
            raise ValueError(f"artifact inventory hash mismatch: {artifact}")


def _resolve_corporate_action_inputs(
    config: MarkupRetestConfig,
) -> CorporateActionInputs:
    """Resolve QD-010 only through its registered, immutable inventory."""

    registry = DataAssetRegistry.load(config.registry_path)
    asset_id = config.assets.corporate_action_asset_id
    try:
        asset = registry.assets[asset_id]
    except KeyError as exc:
        raise ValueError(f"corporate-action asset is not registered: {asset_id}") from exc
    if asset.status != "RESEARCH_CONDITIONAL":
        raise ValueError(
            f"corporate-action asset {asset_id} is not research eligible: {asset.status}"
        )
    if asset.physical_state != "MATERIALIZED" or asset.location is None:
        raise ValueError(f"corporate-action asset {asset_id} is not materialized")

    source_manifest_path = _registered_lineage_path(
        asset.lineage, "source_manifest_path", asset_id
    )
    inventory_manifest_path = _registered_lineage_path(
        asset.lineage, "manifest_path", asset_id
    )
    source_manifest_sha256 = _registered_lineage_sha256(
        asset.lineage, "source_manifest_sha256", asset_id
    )
    inventory_manifest_sha256 = _registered_lineage_sha256(
        asset.lineage, "manifest_sha256", asset_id
    )
    if source_manifest_path != asset.location / "manifest.json":
        raise ValueError(
            f"corporate-action source manifest is outside the registered root: {asset_id}"
        )
    _verify_file_identity(source_manifest_path, source_manifest_sha256)
    _verify_file_identity(inventory_manifest_path, inventory_manifest_sha256)

    inventory = json.loads(inventory_manifest_path.read_text())
    if not isinstance(inventory, dict):
        raise ValueError(f"invalid corporate-action inventory: {inventory_manifest_path}")
    inventory_root = Path(str(inventory.get("root", ""))).expanduser().resolve()
    if inventory_root != asset.location:
        raise ValueError(
            f"corporate-action inventory root mismatch: {inventory_manifest_path}"
        )
    raw_files = inventory.get("files")
    if not isinstance(raw_files, list):
        raise ValueError(f"corporate-action inventory files missing: {inventory_manifest_path}")
    by_path: dict[str, dict[str, Any]] = {}
    for item in raw_files:
        if not isinstance(item, dict):
            raise ValueError(f"invalid corporate-action inventory entry: {item!r}")
        relative = Path(str(item.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError(f"unsafe corporate-action inventory path: {relative}")
        key = relative.as_posix()
        if key in by_path:
            raise ValueError(f"duplicate corporate-action inventory path: {key}")
        by_path[key] = item
    required = {
        "manifest.json",
        "normalized/distributions.parquet",
        "normalized/rights_issues.parquet",
    }
    if set(by_path) != required:
        raise ValueError(
            "corporate-action inventory does not exactly match required inputs: "
            f"{sorted(by_path)}"
        )
    for relative_path_str, item in by_path.items():
        path = inventory_root / relative_path_str
        expected_size = item.get("size")
        expected_sha = item.get("sha256")
        if not isinstance(expected_size, int) or not isinstance(expected_sha, str):
            raise ValueError(
                "invalid corporate-action inventory identity: "
                f"{relative_path_str}"
            )
        _verify_file_identity(path, expected_sha, expected_size=expected_size)
    if by_path["manifest.json"].get("sha256") != source_manifest_sha256:
        raise ValueError("corporate-action source manifest hashes disagree")

    source_manifest = json.loads(source_manifest_path.read_text())
    if not isinstance(source_manifest, dict):
        raise ValueError(
            f"invalid corporate-action source manifest: {source_manifest_path}"
        )
    knowledge_contract = source_manifest.get("knowledge_contract", {})
    if not isinstance(knowledge_contract, dict):
        raise ValueError("corporate-action knowledge contract is missing")
    strict_pit_eligible = knowledge_contract.get("strict_pit_eligible")
    if not isinstance(strict_pit_eligible, bool):
        raise ValueError("corporate-action strict PIT eligibility is not boolean")
    return CorporateActionInputs(
        source_manifest_path=source_manifest_path,
        inventory_manifest_path=inventory_manifest_path,
        distributions_path=inventory_root / "normalized/distributions.parquet",
        rights_path=inventory_root / "normalized/rights_issues.parquet",
        source_manifest_sha256=source_manifest_sha256,
        inventory_manifest_sha256=inventory_manifest_sha256,
        distributions_sha256=str(
            by_path["normalized/distributions.parquet"]["sha256"]
        ),
        rights_sha256=str(by_path["normalized/rights_issues.parquet"]["sha256"]),
        snapshot_id=f"{asset_id}-{source_manifest_sha256[:16]}",
        strict_pit_eligible=strict_pit_eligible and asset.pit_grade == "A",
    )


def _registered_lineage_path(
    lineage: dict[str, Any], key: str, asset_id: str
) -> Path:
    raw = lineage.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"registered asset {asset_id} has no {key}")
    return Path(raw).expanduser().resolve()


def _registered_lineage_sha256(
    lineage: dict[str, Any], key: str, asset_id: str
) -> str:
    raw = lineage.get(key)
    if (
        not isinstance(raw, str)
        or len(raw) != 64
        or any(char not in "0123456789abcdef" for char in raw.lower())
    ):
        raise ValueError(f"registered asset {asset_id} has invalid {key}")
    return raw.lower()


def _verify_file_identity(
    path: Path, expected_sha256: str, *, expected_size: int | None = None
) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"registered input is missing: {path}")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError(f"registered input size mismatch: {path}")
    if _sha256(path) != expected_sha256:
        raise ValueError(f"registered input hash mismatch: {path}")


def _absolute_inventory_item(path: Path, sha256: str) -> dict[str, Any]:
    _verify_file_identity(path, sha256)
    return {"path": str(path), "size": path.stat().st_size, "sha256": sha256}


def _verify_source_inventory(
    payload: dict[str, Any], expected: list[dict[str, Any]]
) -> None:
    actual = payload.get("source_input_inventory")
    if actual != expected:
        raise ValueError("panel source input inventory changed")
    for item in expected:
        path = Path(str(item["path"]))
        _verify_file_identity(
            path,
            str(item["sha256"]),
            expected_size=int(item["size"]),
        )


def _sql_text(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
