#!/usr/bin/env python3
"""Append the registered current market delta to daily PIT-B, fail closed.

This builder never mutates CY-006.  It reuses its frozen 2018-2025 files,
merges only the 2026 partition, and strengthens the current delta with raw
reference-price continuity and turnover-implied float cross-checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb

from cyq_game.data.full_market import (
    _create_action_events,
    _create_enriched,
    _create_float_timeline,
    _create_raw_actions,
)

ROOT = Path(__file__).resolve().parents[1]
START = date(2026, 8, 13)
END = date(2026, 8, 24)
BASE_ASSET = "CY-006"
MARKET_ASSET = "CY-022"
INDUSTRY_ASSET = "CY-023"
BASE_INDUSTRY_ASSET = "QD-008-BS-MERGED-20260821"
FLOAT_ASSET = "QD-009"
ACTION_ASSET = "QD-010"
PIPELINE_VERSION = "daily-pit-b-current-extension-v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sql(path: Path | str) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _asset(registry: dict[str, Any], asset_id: str) -> dict[str, Any]:
    matches = [item for item in registry["assets"] if item.get("asset_id") == asset_id]
    if len(matches) != 1:
        raise ValueError(f"registry must contain exactly one {asset_id}")
    asset = matches[0]
    if asset.get("status") != "RESEARCH_CONDITIONAL":
        raise ValueError(f"{asset_id} is not research-conditional")
    lineage = asset.get("lineage", {})
    manifest_path = Path(str(lineage.get("manifest_path", "")))
    expected = str(lineage.get("manifest_sha256", ""))
    if not manifest_path.is_file() or _sha256(manifest_path) != expected:
        raise ValueError(f"{asset_id} immutable manifest mismatch")
    return asset


def _verify_inventory(asset: dict[str, Any]) -> None:
    lineage = asset["lineage"]
    manifest = json.loads(Path(lineage["manifest_path"]).read_text(encoding="utf-8"))
    root = Path(manifest["root"]).resolve()
    if root != Path(asset["location"]).resolve():
        raise ValueError(f"{asset['asset_id']} inventory root mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError(f"{asset['asset_id']} inventory is empty")
    for item in files:
        path = root / item["path"]
        if not path.is_file() or path.stat().st_size != int(item["size"]):
            raise ValueError(f"inventory file missing or resized: {path}")
        if _sha256(path) != item["sha256"]:
            raise ValueError(f"inventory file hash mismatch: {path}")


def _verify_asset_file_hashes(asset: dict[str, Any]) -> None:
    root = Path(asset["location"])
    manifest = json.loads(Path(asset["lineage"]["manifest_path"]).read_text(encoding="utf-8"))
    hashes = manifest.get("hashes")
    if not isinstance(hashes, dict):
        raise ValueError(f"{asset['asset_id']} asset manifest has no hashes")
    candidates = {
        "raw_daily_sha256": root / "raw_daily.parquet",
        "raw_5m_sha256": root / "raw_5m.parquet",
        "data_sha256": root / "industry_daily.parquet",
        "quality_report_sha256": root / "quality_report.json",
    }
    checked = 0
    for key, path in candidates.items():
        if key not in hashes:
            continue
        if not path.is_file() or _sha256(path) != hashes[key]:
            raise ValueError(f"{asset['asset_id']} file hash mismatch: {path}")
        checked += 1
    if checked == 0:
        raise ValueError(f"{asset['asset_id']} has no verifiable data file")


@dataclass(frozen=True)
class _SnapshotManifest:
    snapshots: dict[str, tuple[str, str]]

    def binding(self, role: str) -> Any:
        asset_id, snapshot_id = self.snapshots[role]
        return SimpleNamespace(
            snapshot_id=snapshot_id,
            asset=SimpleNamespace(asset_id=asset_id),
            source=asset_id,
        )


def _symbol_sql(code_column: str) -> str:
    return (
        f"SUBSTR({code_column}, 4, 6) || CASE WHEN LEFT({code_column}, 2) = 'sh' "
        "THEN '.SH' ELSE '.SZ' END"
    )


def _create_delta_sources(
    connection: duckdb.DuckDBPyConnection,
    *,
    market_root: Path,
    industry_root: Path,
    base_industry_root: Path,
    base_daily_root: Path,
    float_root: Path,
    action_root: Path,
) -> None:
    raw_daily = market_root / "raw_daily.parquet"
    base_2026 = base_daily_root / "partition_year=2026" / "data_0.parquet"
    symbol_sql = _symbol_sql("code")
    connection.execute(
        f"""
        CREATE TEMP TABLE raw_delta AS
        SELECT CAST(date AS DATE) AS trade_date,
               {symbol_sql} AS symbol,
               CAST(code AS VARCHAR) AS source_code,
               TRY_CAST(open AS DOUBLE) AS open,
               TRY_CAST(high AS DOUBLE) AS high,
               TRY_CAST(low AS DOUBLE) AS low,
               TRY_CAST(close AS DOUBLE) AS close,
               TRY_CAST(preclose AS DOUBLE) AS preclose,
               TRY_CAST(volume AS DOUBLE) AS volume,
               TRY_CAST(amount AS DOUBLE) AS amount,
               TRY_CAST(turn AS DOUBLE) AS source_turnover_rate,
               TRY_CAST(tradestatus AS INTEGER) AS trade_status,
               CASE WHEN isST = '1' THEN TRUE WHEN isST = '0' THEN FALSE END AS is_st
        FROM read_parquet({_sql(raw_daily)})
        WHERE CAST(date AS DATE) BETWEEN DATE '{START}' AND DATE '{END}';

        CREATE TEMP TABLE base_history AS
        SELECT symbol, trade_date, close
        FROM read_parquet({_sql(base_2026)})
        WHERE trade_date < DATE '{START}';

        CREATE TEMP TABLE previous_prices AS
        WITH prices AS (
          SELECT symbol, trade_date, close FROM base_history WHERE close > 0
          UNION ALL
          SELECT symbol, trade_date, close FROM raw_delta WHERE close > 0
        ), lagged AS (
          SELECT symbol, trade_date,
                 LAG(close) OVER (PARTITION BY symbol ORDER BY trade_date) AS previous_close
          FROM prices
        )
        SELECT * FROM lagged WHERE trade_date BETWEEN DATE '{START}' AND DATE '{END}';

        CREATE TEMP TABLE daily AS
        SELECT r.trade_date, r.symbol, 'none' AS adjust,
               r.open, r.high, r.low, r.close, r.preclose, r.volume, r.amount,
               r.source_turnover_rate
        FROM raw_delta r;

        CREATE TEMP TABLE delta_rank AS
        SELECT r.*,
               ROW_NUMBER() OVER (PARTITION BY r.symbol ORDER BY r.trade_date) AS delta_session,
               b.symbol IS NOT NULL AS existed_before_delta,
               p.previous_close
        FROM raw_delta r
        LEFT JOIN (SELECT DISTINCT symbol FROM base_history) b USING (symbol)
        LEFT JOIN previous_prices p USING (symbol, trade_date);

        CREATE TEMP TABLE state AS
        WITH rules AS (
          SELECT *,
            CASE
              WHEN NOT existed_before_delta AND delta_session <= 5 THEN NULL
              WHEN is_st THEN 0.05
              WHEN LEFT(symbol, 3) IN ('300', '301', '688', '689') THEN 0.20
              ELSE 0.10
            END AS limit_pct,
            COALESCE(preclose, previous_close) AS reference_price
          FROM delta_rank
        ), limits AS (
          SELECT *, ROUND(reference_price * (1 + limit_pct), 2) AS up_limit_price,
                    ROUND(reference_price * (1 - limit_pct), 2) AS down_limit_price
          FROM rules
        )
        SELECT trade_date, symbol, trade_status, is_st, limit_pct,
               up_limit_price, down_limit_price,
               CASE WHEN trade_status = 0 THEN TRUE
                    WHEN open IS NULL OR up_limit_price IS NULL THEN NULL
                    ELSE open >= up_limit_price END AS buy_blocked_open,
               CASE WHEN trade_status = 0 THEN TRUE
                    WHEN open IS NULL OR down_limit_price IS NULL THEN NULL
                    ELSE open <= down_limit_price END AS sell_blocked_open,
               'baostock_none_daily' AS state_source
        FROM limits;
        """
    )

    base_industry = base_industry_root / "industry_daily.parquet"
    new_industry = industry_root / "industry_daily.parquet"
    connection.execute(
        f"""
        CREATE TEMP TABLE industry AS
        WITH combined AS (
          SELECT trade_date,
                 symbol || CASE WHEN LEFT(symbol, 1) IN ('5','6','9')
                                THEN '.SH' ELSE '.SZ' END AS symbol,
                 industry, source_notice_date,
                 source_report_date, source AS industry_source
          FROM read_parquet({_sql(base_industry)})
          UNION ALL
          SELECT CAST(decision_date AS DATE) AS trade_date,
                 symbol || CASE WHEN LEFT(symbol, 1) IN ('5','6','9')
                                THEN '.SH' ELSE '.SZ' END AS symbol,
                 industry,
                 CAST(source_update_date AS DATE) AS source_notice_date,
                 NULL::DATE AS source_report_date,
                 source AS industry_source
          FROM read_parquet({_sql(new_industry)})
          WHERE CAST(source_update_date AS DATE) < CAST(decision_date AS DATE)
        )
        SELECT * FROM combined
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY trade_date, symbol
          ORDER BY source_notice_date DESC, industry_source DESC
        ) = 1;
        """
    )

    index = market_root / "index_daily" / "csi000300.parquet"
    connection.execute(
        f"""
        CREATE TEMP TABLE market AS
        SELECT CAST(date AS DATE) AS trade_date,
               'csi000300' AS index_symbol, '沪深300' AS index_name,
               TRY_CAST(open AS DOUBLE) AS market_open,
               TRY_CAST(high AS DOUBLE) AS market_high,
               TRY_CAST(low AS DOUBLE) AS market_low,
               TRY_CAST(close AS DOUBLE) AS market_close,
               TRY_CAST(volume AS DOUBLE) AS market_volume,
               TRY_CAST(amount AS DOUBLE) AS market_amount
        FROM read_parquet({_sql(index)})
        WHERE CAST(date AS DATE) BETWEEN DATE '{START}' AND DATE '{END}';

        CREATE TEMP TABLE float_facts AS
        WITH parsed AS (
          SELECT UPPER(CAST(qmt_code AS VARCHAR)) AS symbol,
                 TRY_STRPTIME(CAST(m_timetag AS VARCHAR), '%Y%m%d')::DATE
                   AS float_effective_date,
                 TRY_STRPTIME(CAST(m_anntime AS VARCHAR), '%Y%m%d')::DATE
                   AS float_announced_date,
                 CAST(circulating_capital AS DOUBLE) AS circulating_shares,
                 CAST(source AS VARCHAR) AS float_source
          FROM read_parquet({_sql(float_root / 'qmt_capital.parquet')})
        )
        SELECT *, CASE WHEN float_effective_date IS NOT NULL
                            AND float_announced_date IS NOT NULL
                       THEN GREATEST(float_effective_date, float_announced_date) END
                    AS float_available_date
        FROM parsed;
        """
    )
    _create_raw_actions(
        connection,
        {
            "distributions": action_root / "normalized" / "distributions.parquet",
            "rights": action_root / "normalized" / "rights_issues.parquet",
        },
    )


def _strengthen_delta(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE extension_checks AS
        SELECT e.symbol, e.trade_date,
          CASE
            WHEN e.trade_status = 0 THEN TRUE
            WHEN p.previous_close IS NULL OR e.preclose IS NULL THEN FALSE
            WHEN ABS(e.preclose - p.previous_close) <= 0.005 THEN TRUE
            WHEN e.corporate_action_count > 0
                 AND NOT e.corporate_action_blocking THEN TRUE
            ELSE FALSE
          END AS reference_price_continuity_valid,
          CASE
            WHEN NOT e.float_valid THEN FALSE
            WHEN e.trade_status = 0 OR e.volume <= 0 THEN TRUE
            WHEN e.source_turnover_rate IS NULL OR e.source_turnover_rate <= 0 THEN TRUE
            ELSE ABS(
              e.volume / (e.source_turnover_rate / 100.0) - e.circulating_shares
            ) / e.circulating_shares <= 0.05
          END AS float_turnover_crosscheck_valid,
          CASE
            WHEN e.source_turnover_rate > 0 AND e.circulating_shares > 0
            THEN ABS(
              e.volume / (e.source_turnover_rate / 100.0) - e.circulating_shares
            ) / e.circulating_shares
          END AS float_turnover_relative_error,
          p.previous_close
        FROM enriched e
        LEFT JOIN previous_prices p USING (symbol, trade_date);

        CREATE TEMP TABLE delta_enriched AS
        SELECT e.* REPLACE (
          e.float_valid AND c.float_turnover_crosscheck_valid AS float_valid,
          e.corporate_action_valid AND c.reference_price_continuity_valid
            AS corporate_action_valid,
          e.hard_valid AND c.float_turnover_crosscheck_valid
            AND c.reference_price_continuity_valid AS hard_valid,
          e.trade_status = 1 AND e.hard_valid
            AND c.float_turnover_crosscheck_valid
            AND c.reference_price_continuity_valid AS current_day_data_tradable,
          CONCAT_WS('|', NULLIF(e.invalid_reasons, ''),
            CASE WHEN NOT c.reference_price_continuity_valid
                 THEN 'UNRESOLVED_REFERENCE_PRICE_DISCONTINUITY' END,
            CASE WHEN NOT c.float_turnover_crosscheck_valid
                 THEN 'FLOAT_TURNOVER_CROSSCHECK_FAILED' END
          ) AS invalid_reasons
        ),
        c.reference_price_continuity_valid,
        c.float_turnover_crosscheck_valid,
        c.float_turnover_relative_error,
        c.previous_close,
        'CY022_CY023_QD009_QD010_FAIL_CLOSED_V1' AS metadata_extension_policy
        FROM enriched e JOIN extension_checks c USING (symbol, trade_date);
        """
    )


def _copy_base_and_write_current(
    connection: duckdb.DuckDBPyConnection,
    base_root: Path,
    output: Path,
) -> list[dict[str, Any]]:
    destination = output / "daily"
    for year in range(2018, 2026):
        source = base_root / f"partition_year={year}" / "data_0.parquet"
        target = destination / f"partition_year={year}" / "data_0.parquet"
        target.parent.mkdir(parents=True, exist_ok=False)
        shutil.copy2(source, target)
    base_2026 = base_root / "partition_year=2026" / "data_0.parquet"
    current = destination / "partition_year=2026" / "data_0.parquet"
    current.parent.mkdir(parents=True, exist_ok=False)
    connection.execute(
        f"""
        COPY (
          SELECT * FROM read_parquet({_sql(base_2026)})
          UNION ALL BY NAME
          SELECT * FROM delta_enriched
          ORDER BY trade_date, symbol
        ) TO {_sql(current)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
    )
    files = sorted(destination.glob("partition_year=*/data_0.parquet"))
    return [
        {
            "path": path.relative_to(output).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]


def _audit(
    connection: duckdb.DuckDBPyConnection,
    *,
    output: Path,
    build_id: str,
    component_hashes: dict[str, str],
) -> dict[str, Any]:
    delta = connection.execute(
        """
        SELECT COUNT(*), COUNT(*) FILTER (WHERE hard_valid),
               COUNT(*) - COUNT(DISTINCT (symbol, trade_date)),
               COUNT(*) FILTER (WHERE available_at > decision_at),
               COUNT(*) FILTER (WHERE NOT reference_price_continuity_valid),
               COUNT(*) FILTER (WHERE NOT float_turnover_crosscheck_valid),
               COUNT(*) FILTER (WHERE industry IS NULL OR industry = 'UNKNOWN'),
               COUNT(*) FILTER (WHERE NOT market_valid),
               MAX(float_turnover_relative_error)
        FROM delta_enriched
        """
    ).fetchone()
    assert delta is not None
    current = output / "daily" / "partition_year=2026" / "data_0.parquet"
    full = connection.execute(
        """
        SELECT COUNT(*), MIN(trade_date), MAX(trade_date), COUNT(DISTINCT symbol),
               COUNT(*) - COUNT(DISTINCT (symbol, trade_date)),
               COUNT(*) FILTER (WHERE hard_valid)
        FROM read_parquet(?)
        """,
        [str(current)],
    ).fetchone()
    reasons = connection.execute(
        """
        SELECT invalid_reasons, COUNT(*)
        FROM delta_enriched WHERE NOT hard_valid
        GROUP BY invalid_reasons ORDER BY COUNT(*) DESC, invalid_reasons
        """
    ).fetchall()
    assert full is not None
    delta_ratio = int(delta[1]) / int(delta[0]) if delta[0] else 0.0
    checks = {
        "delta_rows_match_raw": int(delta[0]) == 41668,
        "delta_hard_valid_at_least_95pct": delta_ratio >= 0.95,
        "delta_unique": int(delta[2]) == 0,
        "delta_no_time_travel": int(delta[3]) == 0,
        "current_partition_unique": int(full[4]) == 0,
        "current_partition_end_is_2026_08_24": str(full[2]) == END.isoformat(),
        "current_partition_preserves_base_rows": int(full[0]) == 765643 + 41668,
        "invalid_rows_have_reasons": connection.execute(
            "SELECT COUNT(*)=0 FROM delta_enriched WHERE NOT hard_valid "
            "AND COALESCE(invalid_reasons,'')=''"
        ).fetchone()[0],
    }
    return {
        "schema_version": 1,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "gate": "CURRENT_DAILY_PIT_B_20260824_V1",
        "build_id": build_id,
        "pipeline_version": PIPELINE_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "coverage": {
            "start": "2018-01-02",
            "end": END.isoformat(),
            "delta_start": START.isoformat(),
            "delta_end": END.isoformat(),
            "delta_rows": int(delta[0]),
            "delta_hard_valid_rows": int(delta[1]),
            "delta_hard_valid_ratio": delta_ratio,
            "current_2026_rows": int(full[0]),
            "current_2026_symbols": int(full[3]),
            "current_2026_hard_valid_rows": int(full[5]),
        },
        "diagnostics": {
            "reference_price_discontinuity_rows": int(delta[4]),
            "float_turnover_crosscheck_failure_rows": int(delta[5]),
            "missing_or_unknown_industry_rows": int(delta[6]),
            "invalid_market_rows": int(delta[7]),
            "maximum_float_turnover_relative_error": delta[8],
            "invalid_reason_counts": [
                {"invalid_reasons": reason, "rows": count}
                for reason, count in reasons
            ],
        },
        "checks": checks,
        "component_manifest_sha256": component_hashes,
        "limitations": [
            "PIT-B only; supplier revision histories are incomplete.",
            "Reference-price discontinuities without a registered action fail closed.",
            "Turnover-implied float disagreement above 5 percent fails closed.",
            "New listings remain invalid during their first five unlimited sessions.",
            "No strategy, outcome, parameter or backtest data is read by this builder.",
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=ROOT / "configs" / "data_asset_registry.json"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    required = {
        asset_id: _asset(registry, asset_id)
        for asset_id in (
            BASE_ASSET,
            MARKET_ASSET,
            INDUSTRY_ASSET,
            BASE_INDUSTRY_ASSET,
            FLOAT_ASSET,
            ACTION_ASSET,
        )
    }
    for asset_id in (BASE_ASSET, BASE_INDUSTRY_ASSET, FLOAT_ASSET, ACTION_ASSET):
        _verify_inventory(required[asset_id])
    _verify_asset_file_hashes(required[MARKET_ASSET])
    _verify_asset_file_hashes(required[INDUSTRY_ASSET])
    component_hashes = {
        asset_id: required[asset_id]["lineage"]["manifest_sha256"]
        for asset_id in required
    }
    identity = _canonical_json(
        {"pipeline": PIPELINE_VERSION, "components": component_hashes}
    )
    build_id = "PITB-CURRENT-" + hashlib.sha256(identity.encode()).hexdigest()[:20].upper()
    snapshot_manifest = _SnapshotManifest(
        {
            "daily_bars": (MARKET_ASSET, required[MARKET_ASSET]["lineage"]["snapshot_id"]),
            "trading_state": (MARKET_ASSET, required[MARKET_ASSET]["lineage"]["snapshot_id"]),
            "index_daily": (MARKET_ASSET, required[MARKET_ASSET]["lineage"]["snapshot_id"]),
            "industry_membership": (
                INDUSTRY_ASSET,
                required[INDUSTRY_ASSET]["lineage"]["snapshot_id"],
            ),
            "circulating_shares": (
                FLOAT_ASSET,
                "QD-009-QMT-CAPITAL-20260820",
            ),
            "corporate_actions": (
                ACTION_ASSET,
                "QD-010-CNINFO-CURRENT-HISTORY-20260820",
            ),
        }
    )
    temporary = output.parent / f".{output.name}.building-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect()
    try:
        connection.execute("SET threads=4")
        connection.execute("SET memory_limit='8GiB'")
        connection.execute("SET preserve_insertion_order=false")
        _create_delta_sources(
            connection,
            market_root=Path(required[MARKET_ASSET]["location"]),
            industry_root=Path(required[INDUSTRY_ASSET]["location"]),
            base_industry_root=Path(required[BASE_INDUSTRY_ASSET]["location"]),
            base_daily_root=Path(required[BASE_ASSET]["location"]),
            float_root=Path(required[FLOAT_ASSET]["location"]),
            action_root=Path(required[ACTION_ASSET]["location"]),
        )
        _create_float_timeline(connection, END)
        _create_action_events(connection, START, END)
        _create_enriched(connection, snapshot_manifest, build_id)  # type: ignore[arg-type]
        _strengthen_delta(connection)
        files = _copy_base_and_write_current(
            connection, Path(required[BASE_ASSET]["location"]), temporary
        )
        audit = _audit(
            connection,
            output=temporary,
            build_id=build_id,
            component_hashes=component_hashes,
        )
        audit["files"] = files
        (temporary / "audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            + "\n",
            encoding="utf-8",
        )
        if audit["status"] != "PASS":
            failure = output.parent / f"{output.name}.failed-{build_id}"
            temporary.replace(failure)
            print(json.dumps({"status": "FAIL", "audit": str(failure / 'audit.json')}))
            return 1
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(output)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "output": str(output),
                    "audit": str(output / "audit.json"),
                    "coverage": audit["coverage"],
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        connection.close()
        if temporary.exists():
            shutil.rmtree(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
