from __future__ import annotations

from dataclasses import replace

import duckdb
import pytest

from cyq_game.strategy.labels import build_future_labels
from cyq_game.strategy.markup_retest import load_markup_retest_config
from cyq_game.strategy.panel import PanelBuildResult


def _synthetic_panel(tmp_path, config) -> PanelBuildResult:
    panel_root = tmp_path / "panel" / "data"
    panel_root.mkdir(parents=True)
    panel_file = panel_root / "rows.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
                SELECT
                    '000001.SZ' AS symbol,
                    DATE '2020-01-01' + i::INTEGER AS trade_date,
                    TIMESTAMP '2020-01-01 15:30:00' + i * INTERVAL 1 DAY
                        AS decision_at,
                    'MAIN' AS board,
                    'BANK' AS industry,
                    'INDUSTRY_LOO' AS sector_fallback,
                    100000000.0 AS amount_mean20,
                    0.02 AS realized_volatility,
                    0.01 AS momentum_20,
                    'daily-' || i::VARCHAR AS daily_snapshot_id,
                    'feature-daily-' || i::VARCHAR AS feature_daily_snapshot_id,
                    'feature-minute-' || i::VARCHAR AS feature_minute_snapshot_id,
                    '{config.sha256}' AS strategy_config_sha256,
                    true AS is_evaluation_row,
                    10.0 + i * 0.01 AS open,
                    10.0 + i * 0.02 AS close,
                    10.1 + i * 0.02 AS high,
                    9.9 + i * 0.01 AS low,
                    0 AS corporate_action_count
                FROM range(30) AS sequence(i)
            ) TO '{panel_file}' (FORMAT PARQUET)
            """
        )
    finally:
        con.close()
    return PanelBuildResult(
        stage="week",
        status="COMPLETE",
        path=panel_root,
        manifest_path=tmp_path / "panel" / "manifest.json",
        rows=30,
        symbols=1,
        eligible_rows=30,
        strict_rows=0,
        coverage=1.0,
        config_sha256=config.sha256,
        panel_snapshot_id="panel-synthetic",
    )


def test_future_labels_are_physically_isolated_and_inventory_verified(tmp_path) -> None:
    base = load_markup_retest_config()
    outputs = replace(base.outputs, label_root=tmp_path / "labels")
    config = replace(base, outputs=outputs)
    panel = _synthetic_panel(tmp_path, config)

    result = build_future_labels(config, panel, "week")

    assert result.path != panel.path
    assert result.rows == 30
    # Entry occurs in the next legal 5-minute window; the 20-session horizon
    # therefore starts after that fill, leaving nine fully observed decisions.
    assert result.valid_rows == 9
    columns = {
        row[0]
        for row in duckdb.sql(
            f"DESCRIBE SELECT * FROM read_parquet('{result.path}/**/*.parquet')"
        ).fetchall()
    }
    assert {
        "net_return_20d",
        "mfe_20d",
        "mae_20d",
        "label_valid",
        "execution_status",
        "entry_snapshot_id",
    } <= columns

    artifact = next(result.path.rglob("*.parquet"))
    artifact.write_bytes(artifact.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="inventory size mismatch"):
        build_future_labels(config, panel, "week", reuse=True)
