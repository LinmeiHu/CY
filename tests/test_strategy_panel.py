from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import duckdb
import pytest

from cyq_game.strategy import panel as panel_module


def _industry_panel() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE causal_panel AS
        SELECT * FROM (VALUES
            ('A', DATE '2020-01-01', 'TECH', 'TECH', 'INDUSTRY_LOO',
             2, 0.20, 0.30, 0.10, 3, 0.35, 0.90),
            ('B', DATE '2020-01-01', 'TECH', 'TECH', 'INDUSTRY_LOO',
             2, 0.10, 0.30, 0.20, 3, 0.35, 0.90),
            ('C', DATE '2020-01-01', NULL, NULL, 'BOARD_LOO',
             0, 0.15, NULL, 0.05, 3, 0.35, 0.50),
            ('D', DATE '2020-01-01', NULL, NULL, 'UNAVAILABLE',
             0, NULL, NULL, 0.01, 1, 0.01, 0.00),
            ('A', DATE '2020-01-02', NULL, 'TECH', 'INDUSTRY_LOO',
             2, 0.06, 0.10, 0.04, 2, 0.10, 0.90),
            ('B', DATE '2020-01-02', 'TECH', 'TECH', 'INDUSTRY_LOO',
             2, 0.04, 0.10, 0.06, 2, 0.10, 0.90)
        ) AS rows(
            symbol, trade_date, observed_industry, industry, sector_fallback,
            industry_return_count, sector_return_loo, industry_return_sum,
            stock_return, board_return_count, board_return_sum, sector_confidence
        )
        """
    )
    return con


def test_industry_asof_and_leave_one_out_are_recomputed() -> None:
    con = _industry_panel()
    try:
        panel_module._assert_industry_features(con)
    finally:
        con.close()


def test_missing_industry_never_becomes_full_confidence() -> None:
    con = _industry_panel()
    try:
        con.execute(
            "UPDATE causal_panel SET sector_confidence = 1.0 WHERE symbol = 'C'"
        )
        with pytest.raises(RuntimeError, match="confidence_invalid=1"):
            panel_module._assert_industry_features(con)
    finally:
        con.close()


def _corporate_action_panel() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE causal_panel AS
        SELECT * FROM (VALUES
            (
                true, true, false, 'RIGHTS-1',
                TIMESTAMP '2020-01-01 09:00:00',
                TIMESTAMP '2020-01-01 15:30:00',
                'QD-010-snapshot', 'B_RESEARCH_ONLY', false
            ),
            (
                false, false, true, NULL, NULL,
                TIMESTAMP '2020-01-02 15:30:00',
                'QD-010-snapshot', 'B_RESEARCH_ONLY', false
            )
        ) AS rows(
            announced_rights_blocking,
            corporate_action_blocking,
            strategy_eligible,
            announced_rights_event_ids,
            announced_rights_available_at,
            available_at,
            corporate_action_snapshot_id,
            corporate_action_pit_grade,
            strict_hard_valid
        )
        """
    )
    return con


def test_announced_rights_block_new_risk_with_lineage() -> None:
    con = _corporate_action_panel()
    try:
        panel_module._assert_corporate_action_features(con)
    finally:
        con.close()


def test_announced_rights_cannot_be_marked_strategy_eligible() -> None:
    con = _corporate_action_panel()
    try:
        con.execute(
            "UPDATE causal_panel SET strategy_eligible = true "
            "WHERE announced_rights_blocking"
        )
        with pytest.raises(RuntimeError, match="rights_risk_allowed=1"):
            panel_module._assert_corporate_action_features(con)
    finally:
        con.close()


def test_b_grade_corporate_actions_cannot_be_strict() -> None:
    con = _corporate_action_panel()
    try:
        con.execute(
            "UPDATE causal_panel SET strict_hard_valid = true "
            "WHERE announced_rights_blocking"
        )
        with pytest.raises(RuntimeError, match="non_strict_source_marked_strict=1"):
            panel_module._assert_corporate_action_features(con)
    finally:
        con.close()


def test_source_inventory_verification_detects_mutation(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"frozen-input")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    inventory = [
        {"path": str(source), "size": source.stat().st_size, "sha256": digest}
    ]
    payload = {"source_input_inventory": inventory}

    panel_module._verify_source_inventory(payload, inventory)
    source.write_bytes(b"mutated-input")

    with pytest.raises(ValueError, match="registered input size mismatch"):
        panel_module._verify_source_inventory(payload, inventory)


def test_registered_302_alias_is_preserved_as_chinext() -> None:
    con = duckdb.connect()
    try:
        row = con.execute(
            f"""
            SELECT
                {panel_module._main_chinext_scope_sql('symbol')} AS in_scope,
                {panel_module._board_sql('symbol')} AS board
            FROM (VALUES ('302132.SZ')) AS samples(symbol)
            """
        ).fetchone()
    finally:
        con.close()

    assert row == (True, "CHINEXT")


def test_panel_uses_only_predecision_atr_and_never_reuses_ranked_peak_json() -> None:
    """A close decision cannot use its own range or a re-ranked peak identity."""

    source = inspect.getsource(panel_module._create_panel_table)

    assert "ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING" in source
    assert "peaks_json" not in source
    assert "chain_epoch_rows" in source
    assert "FROM chain_epoch_rows\n            WHERE pre_chain_valid" in source
    assert "PARTITION BY symbol, chain_epoch" in source
    assert "P90_FALLBACK" not in source


def test_panel_rejects_duplicate_input_keys_before_join(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
                SELECT * FROM (VALUES
                    ('000001.SZ', DATE '2020-01-02'),
                    ('000001.SZ', DATE '2020-01-02')
                ) AS rows(symbol, trade_date)
            ) TO '{path}' (FORMAT PARQUET)
            """
        )
        with pytest.raises(ValueError, match="not unique"):
            panel_module._assert_unique_panel_input(
                con,
                source_sql=f"['{path}']",
                source_name="test input",
            )
    finally:
        con.close()
