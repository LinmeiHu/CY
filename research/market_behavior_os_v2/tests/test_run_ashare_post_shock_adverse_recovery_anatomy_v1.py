from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts"
    / "run_ashare_post_shock_adverse_recovery_anatomy_v1.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments"
    / "ASHARE-POST-SHOCK-ADVERSE-RECOVERY-ANATOMY-V1_spec.json"
)


def _module():
    module_spec = importlib.util.spec_from_file_location("adverse_recovery_anatomy_test", SCRIPT)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def _outcome_frame(values: list[float], buckets: list[int]) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "recovery_quintile": buckets,
            "mae_h20": [-0.12, -0.08, -0.06, -0.04, -0.02],
        }
    )
    for horizon in (1, 3, 5, 10, 20):
        frame[f"net_return_h{horizon}"] = values
        frame[f"industry_relative_h{horizon}"] = np.asarray(values) - 0.001
    return frame


def test_frozen_anatomy_contract_reuses_exact_family_and_forbids_replay() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["status"] == "FROZEN_BEFORE_NEW_POST_HOC_ANATOMY_OUTCOME_AGGREGATION"
    assert spec["sample"]["parameter_cells"] == 18
    assert spec["sample"]["absolute_simple_return_thresholds"] == [-0.04, -0.06, -0.08]
    assert spec["sample"]["industry_relative_simple_return_thresholds"] == [-0.02, -0.04]
    assert spec["sample"]["absorption_windows_sessions"] == [2, 3, 5]
    assert spec["execution"]["portfolio_replay"] is False
    assert "POST_HOC" in spec["claim_boundary"]


def test_q1_q5_mapping_and_bucket_metrics_report_long_leg_directly() -> None:
    module = _module()
    frame = _outcome_frame([0.05, 0.03, 0.01, -0.01, -0.03], [1, 2, 3, 4, 5])
    q1 = module.bucket_metrics(frame.loc[frame.recovery_quintile.eq(1)], 20)
    q5 = module.bucket_metrics(frame.loc[frame.recovery_quintile.eq(5)], 20)
    assert q1["n"] == 1
    assert q1["absolute_mean"] == pytest.approx(0.05)
    assert q1["absolute_positive_rate"] == pytest.approx(1.0)
    assert q1["severe_loss_incidence"] == pytest.approx(1.0)
    assert q5["absolute_mean"] == pytest.approx(-0.03)


def test_event_baseline_decomposition_conserves_q1_q5_spread() -> None:
    module = _module()
    frame = _outcome_frame([0.05, 0.03, 0.01, -0.01, -0.03], [1, 2, 3, 4, 5])
    result = module.baseline_decomposition(frame, 5)["absolute"]
    assert result["event_mean"] == pytest.approx(0.01)
    assert result["q1_minus_event"] == pytest.approx(0.04)
    assert result["q5_minus_event"] == pytest.approx(-0.04)
    assert result["q1_minus_q5"] == pytest.approx(0.08)
    assert result["q1_strength_contribution_share"] == pytest.approx(0.5)
    assert result["q1_minus_event"] - result["q5_minus_event"] == pytest.approx(
        result["q1_minus_q5"]
    )


def test_monotonicity_counts_steps_and_bucket_spearman() -> None:
    module = _module()
    rows = pd.DataFrame(
        {
            "bucket": [1, 2, 3, 4, 5],
            "absolute_mean": [0.05, 0.04, 0.02, 0.00, -0.01],
            "industry_relative_mean": [0.04, 0.03, 0.01, -0.01, -0.02],
        }
    )
    result = module.monotonicity(rows)
    assert result["absolute"]["adjacent_favorable_steps"] == 4
    assert result["absolute"]["bucket_spearman"] == pytest.approx(-1.0)
    assert result["both_coordinates_broadly_monotonic"] is True


def test_horizon_alignment_uses_requested_column_only() -> None:
    module = _module()
    frame = _outcome_frame([0.01] * 5, [1, 2, 3, 4, 5])
    frame["net_return_h5"] = [0.10] * 5
    frame["industry_relative_h5"] = [0.09] * 5
    frame["net_return_h10"] = [-0.20] * 5
    frame["industry_relative_h10"] = [-0.21] * 5
    assert module.bucket_metrics(frame, 5)["absolute_mean"] == pytest.approx(0.10)
    assert module.bucket_metrics(frame, 10)["absolute_mean"] == pytest.approx(-0.20)


def test_chronological_table_uses_frozen_signal_year_split() -> None:
    module = _module()
    rows = []
    for year, value in ((2021, 0.01), (2022, -0.01)):
        for cell in ("A", "B"):
            for horizon in module.HORIZONS:
                rows.append(
                    {
                        "scope": "BLOCK",
                        "period": "EARLY_2018_2021" if year == 2021 else "LATE_2022_2023",
                        "cell_id": cell,
                        "horizon": horizon,
                        "bucket": 1,
                        "absolute_mean": value,
                        "industry_relative_mean": value / 2,
                    }
                )
    rows.extend(
        {
            "scope": "YEAR",
            "period": str(year),
            "cell_id": "A",
            "horizon": horizon,
            "bucket": 1,
            "absolute_mean": 0.01,
            "industry_relative_mean": 0.005,
        }
        for year in range(2018, 2024)
        for horizon in module.HORIZONS
    )
    result = module._chronology(pd.DataFrame(rows))
    assert result["blocks"]["EARLY_2018_2021"]["h5"]["absolute_mean_equal_cell"] == 0.01
    assert result["blocks"]["LATE_2022_2023"]["h5"]["absolute_mean_equal_cell"] == -0.01
    assert set(result["years"]) == {str(year) for year in range(2018, 2024)}


def test_post_2023_outcome_fails_closed() -> None:
    module = _module()
    row = {"signal_date": pd.Timestamp("2023-11-01")}
    for horizon in module.HORIZONS:
        row[f"outcome_date_h{horizon}"] = pd.Timestamp("2023-12-29")
    assert module.validate_outcome_boundary(pd.DataFrame([row])).isoformat() == "2023-12-29"
    row["outcome_date_h20"] = pd.Timestamp("2024-01-02")
    with pytest.raises(module.AdverseRecoveryAnatomyError, match="post-2023 outcome"):
        module.validate_outcome_boundary(pd.DataFrame([row]))


def test_serialization_is_deterministic_and_nonfinite_safe() -> None:
    module = _module()
    value = {"z": np.float64(np.nan), "a": np.int64(3), "b": np.bool_(True)}
    first = json.dumps(module._clean(value), sort_keys=True)
    second = json.dumps(module._clean(value), sort_keys=True)
    assert first == second == '{"a": 3, "b": true, "z": null}'
