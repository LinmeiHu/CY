from __future__ import annotations

import duckdb


def test_dryness_quintile_orientation() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH x(activity_ratio) AS (
            VALUES (0.5), (0.6), (0.7), (0.8), (0.9),
                   (1.0), (1.1), (1.2), (1.3), (1.4)
        )
        SELECT activity_ratio,
               ntile(5) OVER (ORDER BY activity_ratio) AS q
        FROM x ORDER BY activity_ratio
        """
    ).fetchall()
    assert rows[0][1] == 1  # most active
    assert rows[-1][1] == 5  # driest


def test_dedup_cooldown_is_measured_in_trading_rows() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH x AS (
            SELECT range AS seq, range IN (1, 2, 3, 25) AS low_flag
            FROM range(1, 26)
        )
        SELECT seq, dedup
        FROM (
            SELECT seq,
               low_flag AND NOT coalesce(bool_or(low_flag) OVER (
                   ORDER BY seq ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
               ), false) AS dedup,
               low_flag
            FROM x
        ) marked
        WHERE low_flag ORDER BY seq
        """
    ).fetchall()
    assert rows == [(1, True), (2, False), (3, False), (25, True)]


def test_matching_cell_floor_excludes_sparse_cells() -> None:
    con = duckdb.connect()
    rows = con.execute(
        """
        WITH x(cell, value) AS (
            VALUES ('large', 1), ('large', 2), ('large', 3), ('large', 4), ('large', 5),
                   ('large', 6), ('large', 7), ('large', 8), ('large', 9), ('large', 10),
                   ('small', 1), ('small', 2), ('small', 3)
        ), sized AS (
            SELECT *, count(*) OVER (PARTITION BY cell) AS cell_n FROM x
        )
        SELECT count(*) FROM sized WHERE cell_n >= 10
        """
    ).fetchone()
    assert rows[0] == 10
