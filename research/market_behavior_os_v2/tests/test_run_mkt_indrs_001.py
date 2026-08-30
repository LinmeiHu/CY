from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_indrs_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_indrs_001", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
indrs = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(indrs)


def test_frozen_spec_identity_and_input_ids() -> None:
    spec = indrs._load_spec()
    assert indrs.sha256_file(indrs.SPEC_PATH) == indrs.EXPECTED_SPEC_SHA256
    assert spec["input"]["asset_id"] == "CY-006"
    assert spec["input"]["manifest_sha256"] == indrs.MANIFEST_SHA
    assert len(spec["input"]["selected_partition_sha256"]) == 6
    assert all(f"partition_year={year}" in " ".join(spec["input"]["selected_partition_sha256"])
               for year in range(2018, 2024))


def test_role_map_does_not_reopen_failed_ma_industry_fields() -> None:
    fields = [field for primary, neighbors in indrs.ROLE_MAP.values() for field in (primary, *neighbors)]
    lowered = " ".join(fields).lower()
    assert "industry_diffusion_ma" not in lowered
    assert "breadth_industry_divergence" not in lowered
    assert tuple(indrs.ROLE_MAP) == indrs.PRIORITY


def test_leave_one_out_median_exact_examples() -> None:
    odd = [1.0, 2.0, 2.0, 3.0, 4.0]
    assert [indrs.leave_one_out_median(odd, position) for position in range(len(odd))] == [
        2.5, 2.5, 2.5, 2.0, 2.0,
    ]
    even = [1.0, 2.0, 2.0, 2.0, 4.0, 5.0]
    assert [indrs.leave_one_out_median(even, position) for position in range(len(even))] == [2.0] * 6


def test_rotation_panel_identical_and_reversed_rankings() -> None:
    labels = [f"I{position:02d}" for position in range(10)]
    rows = []
    for position, label in enumerate(labels):
        rows.append(("ALL_A", "ALL_STATUS", "2023-01-02", 10, label, 5, float(10 - position)))
        rows.append(("ALL_A", "ALL_STATUS", "2023-01-09", 15, label, 5, float(position + 1)))
    frame = pd.DataFrame(rows, columns=[
        "market_view", "denominator", "trade_date", "cal_idx", "causal_industry",
        "member_count", "industry_ret20_median",
    ])
    rotation = indrs._rotation_panel(frame, minimum_common=10)
    assert len(rotation) == 1
    row = rotation.iloc[0]
    assert row["common_industry_count_lag5"] == 10
    assert row["industry_label_union_lag5"] == 10
    assert row["industry_leadership_jaccard_top5_lag5"] == 0.0
    assert np.isclose(row["industry_rank_rotation_spearman_lag5"], 1.0)
    assert np.isclose(row["industry_rank_rotation_kendall_lag5"], 1.0)


def test_completed_artifact_boundaries_when_present() -> None:
    if not indrs.RESULT_PATH.exists() or not indrs.PANEL_PATH.exists():
        return
    result = json.loads(indrs.RESULT_PATH.read_text(encoding="utf-8"))
    assert result["strategy_or_outcome_fields_read"] == []
    assert result["failed_ma_industry_fields_read"] == []
    assert result["cy011_read"] is False
    assert result["usefulness_claim"] == "NONE"
    assert result["leave_one_out_audit"]["maximum_absolute_difference"] == 0.0
    assert indrs.sha256_file(indrs.PANEL_PATH) == result["hashes"]["panel_sha256"]
