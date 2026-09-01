from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb

MODULE_PATH = Path(__file__).resolve().parents[1] / "experiment.py"
SPEC = importlib.util.spec_from_file_location("volume_exhaustion_experiment", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_close_signal_uses_next_session_open_and_forward_windows() -> None:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE toy(
            symbol VARCHAR, trade_date DATE, adjusted_close DOUBLE,
            adjusted_high DOUBLE, adjusted_low DOUBLE, open DOUBLE, preclose DOUBLE
        );
        INSERT INTO toy VALUES
          ('X', '2024-01-02', 1.00, 1.01, 0.99, 10.0, 10.0),
          ('X', '2024-01-03', 1.10, 1.12, 1.05, 11.0, 10.0),
          ('X', '2024-01-04', 1.20, 1.22, 1.15, 12.0, 11.0);
        """
    )
    row = con.execute(
        """
        SELECT trade_date,
               lead(trade_date) OVER w AS entry_date,
               lead(preclose) OVER w / lead(open) OVER w
                   * lead(adjusted_close) OVER w / adjusted_close - 1 AS ret_1,
               max(adjusted_high) OVER (
                   PARTITION BY symbol ORDER BY trade_date
                   ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING
               ) AS future_high
        FROM toy
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        ORDER BY trade_date LIMIT 1
        """
    ).fetchone()
    assert str(row[0]) == "2024-01-02"
    assert str(row[1]) == "2024-01-03"
    assert abs(row[2]) < 1e-12  # entry open is 11; next close is also 11
    assert row[3] == 1.12


def test_bad_lineage_inside_rolling_history_fails_closed() -> None:
    con = duckdb.connect()
    con.execute(
        """
        CREATE TABLE toy(seq INTEGER, bad_cum INTEGER);
        -- The invalid raw row at seq=2 is absent from the valid trading sequence,
        -- but its cumulative count is carried by every later valid row.
        INSERT INTO toy VALUES (1, 0), (3, 1), (4, 1), (5, 1);
        """
    )
    rows = con.execute(
        """
        SELECT seq, bad_cum = lag(bad_cum, 2) OVER (ORDER BY seq) AS clean_three
        FROM toy ORDER BY seq
        """
    ).fetchall()
    assert rows[2][1] is False
    assert rows[3][1] is True


def test_raw_price_chain_handles_split_reference_coordinate() -> None:
    # A 2-for-1 split changes raw price from 100 to 50 without creating a -50% return.
    closes = [100.0, 50.0, 52.0]
    precloses = [100.0, 50.0, 50.0]
    chained = 1.0
    for close, preclose in zip(closes, precloses, strict=True):
        chained *= close / preclose
    assert abs(chained - 1.04) < 1e-12


def test_input_identity_validation_without_rehashing_data_files() -> None:
    config = MODULE.json.loads(MODULE.DEFAULT_CONFIG.read_text())
    identities = MODULE.validate_inputs(config, hash_data_files=False)
    assert identities["snapshot_id"] == "CYQ-PIT-B-DAILY-2018-2026-V2"
    assert identities["pit_grade"] == "B"
    assert len(identities["data_files"]) == 9
