from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_style_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_style_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
style = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(style)


def test_frozen_spec_and_contract_identities() -> None:
    spec, data_spec = style._load_spec()
    assert style.sha256_file(style.SPEC_PATH) == style.EXPECTED_SPEC_SHA256
    assert list(spec["roles"]) == spec["role_priority"]
    assert spec["security_coordinate"]["bucket_assignment"].startswith("within each")
    assert spec["security_coordinate"]["current_close_sort"] == "forbidden"
    paths, _ = style._verify_bound_source(data_spec)
    assert len(paths) == 6
    assert style.DUCKDB_THREADS == 1


def test_normalized_entropy_boundaries() -> None:
    assert np.isclose(style.normalized_entropy([1.0, 1.0, 1.0]), 1.0)
    assert np.isclose(style.normalized_entropy([1.0, 0.0, 0.0]), 0.0)
    assert np.isnan(style.normalized_entropy([0.0, 0.0, 0.0]))


def test_size_rank_fraction_uses_full_partition_denominator() -> None:
    connection = duckdb.connect()
    observed = connection.execute(
        f"""
        SELECT {style.SIZE_RANK_FRACTION_EXPRESSION} AS size_rank_fraction
        FROM (VALUES (1),(2),(3),(4)) AS sample(value)
        WINDOW w AS (ORDER BY value), p AS ()
        ORDER BY value
        """
    ).fetchnumpy()["size_rank_fraction"]
    connection.close()
    assert np.allclose(observed, [0.125, 0.375, 0.625, 0.875])


def test_fixed_priority_compression() -> None:
    correlation = pd.DataFrame(
        [[1.0, 0.90, 0.1], [0.90, 1.0, 0.2], [0.1, 0.2, 1.0]],
        index=["a", "b", "c"],
        columns=["a", "b", "c"],
    )
    accepted, excluded = style._compress(correlation, ["a", "b", "c"], ["a", "b", "c"], 0.85)
    assert accepted == ["a", "c"]
    assert excluded == {"b": "redundant_with:a"}


def test_completed_artifact_boundaries_when_present() -> None:
    if not style.RESULT_PATH.exists() or not style.PANEL_PATH.exists():
        return
    result = json.loads(style.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["usefulness_claim"] == "NONE"
    assert result["small_cap_premium_claim"] == "NONE"
    assert result["risk_appetite_claim"] == "NONE"
    assert result["future_fields_read"] == []
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["unregistered_style_fields_read"] == []
    assert result["current_close_bucket_assignment_used"] is False
    assert result["post_2023_data_read"] is False
    assert result["cy011_read"] is False
    assert style.sha256_file(style.PANEL_PATH) == result["hashes"]["panel_sha256"]
