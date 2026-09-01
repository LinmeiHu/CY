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
    / "run_ashare_post_shock_strong_recovery_avoidance_anatomy_v1.py"
)
SPEC = (
    ROOT
    / "research/market_behavior_os_v2/experiments"
    / "ASHARE-POST-SHOCK-STRONG-RECOVERY-AVOIDANCE-ANATOMY-V1_spec.json"
)


def _module():
    module_spec = importlib.util.spec_from_file_location("strong_recovery_avoidance_test", SCRIPT)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def _frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "recovery_quintile": [1, 2, 3, 4, 5],
            "mae_h20": [-0.02, -0.04, -0.06, -0.08, -0.12],
        }
    )
    for horizon in (1, 3, 5, 10, 20):
        frame[f"net_return_h{horizon}"] = [0.04, 0.02, 0.00, -0.02, -0.06]
        frame[f"industry_relative_h{horizon}"] = [0.03, 0.01, -0.01, -0.03, -0.07]
    return frame


def test_frozen_contract_selects_q5_only_and_forbids_replay() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["status"] == "FROZEN_BEFORE_NEW_Q5_POST_HOC_OUTCOME_AGGREGATION"
    assert spec["sample"]["parameter_cells"] == 18
    assert spec["sample"]["selected_bucket"] == 5
    assert spec["sample"]["horizons_sessions"] == [1, 3, 5, 10, 20]
    assert spec["execution"]["portfolio_replay"] is False
    assert spec["execution"]["admission_veto_replay"] is False
    assert "POST_HOC" in spec["claim_boundary"]


def test_q5_selection_reports_only_strongest_recovery_bucket() -> None:
    module = _module()
    result = module.q5_metrics(_frame(), 20)
    assert result["n"] == 1
    assert result["absolute_mean"] == pytest.approx(-0.06)
    assert result["industry_relative_mean"] == pytest.approx(-0.07)
    assert result["absolute_positive_rate"] == 0.0
    assert result["severe_loss_incidence"] == 1.0
    assert result["mean_mae"] == pytest.approx(-0.12)


def test_q5_baseline_decomposition_conserves_weakness_share() -> None:
    module = _module()
    result = module.q5_baseline(_frame(), 5)["absolute"]
    assert result["event_mean"] == pytest.approx(-0.004)
    assert result["q1_mean"] == pytest.approx(0.04)
    assert result["q5_mean"] == pytest.approx(-0.06)
    assert result["q5_minus_event"] == pytest.approx(-0.056)
    assert result["q1_minus_q5"] == pytest.approx(0.10)
    assert result["q5_weakness_contribution_share"] == pytest.approx(0.56)


def test_horizon_alignment_uses_requested_columns() -> None:
    module = _module()
    frame = _frame()
    frame.loc[frame.recovery_quintile.eq(5), "net_return_h5"] = 0.20
    frame.loc[frame.recovery_quintile.eq(5), "net_return_h10"] = -0.30
    assert module.q5_metrics(frame, 5)["absolute_mean"] == pytest.approx(0.20)
    assert module.q5_metrics(frame, 10)["absolute_mean"] == pytest.approx(-0.30)


def test_chronology_keeps_frozen_blocks_and_years_separate() -> None:
    module = _module()
    rows = []
    for scope, period, value in (
        ("BLOCK", "EARLY_2018_2021", -0.01),
        ("BLOCK", "LATE_2022_2023", -0.02),
    ):
        for cell in ("A", "B"):
            for horizon in module.HORIZONS:
                rows.append(
                    {
                        "scope": scope,
                        "period": period,
                        "cell_id": cell,
                        "horizon": horizon,
                        "n": 10,
                        "absolute_mean": value,
                        "absolute_median": value,
                        "absolute_positive_rate": 0.4,
                        "industry_relative_mean": value / 2,
                    }
                )
    rows.extend(
        {
            "scope": "YEAR",
            "period": str(year),
            "cell_id": "A",
            "horizon": horizon,
            "n": 5,
            "absolute_mean": -0.01,
            "absolute_median": -0.02,
            "absolute_positive_rate": 0.4,
            "industry_relative_mean": -0.005,
        }
        for year in range(2018, 2024)
        for horizon in module.HORIZONS
    )
    result = module._chronology(pd.DataFrame(rows))
    assert result["blocks"]["EARLY_2018_2021"]["h5"]["q5_n"] == 20
    assert result["blocks"]["LATE_2022_2023"]["h5"]["absolute_mean_equal_cell"] == -0.02
    assert set(result["years"]) == {str(year) for year in range(2018, 2024)}


def test_control_group_requires_supported_adverse_q5_at_all_primary_horizons() -> None:
    module = _module()
    frame = pd.concat([_frame()] * 100, ignore_index=True)
    adverse = module._group_diagnostic(frame)
    assert adverse["q5_observations"] == 100
    assert adverse["adverse_supported"] is True
    frame.loc[frame.recovery_quintile.eq(5), "net_return_h10"] = 0.01
    assert module._group_diagnostic(frame)["adverse_supported"] is False


def test_post_2023_outcome_fails_closed() -> None:
    module = _module()
    row = {"signal_date": pd.Timestamp("2023-11-01")}
    for horizon in module.HORIZONS:
        row[f"outcome_date_h{horizon}"] = pd.Timestamp("2023-12-29")
    assert module.validate_outcome_boundary(pd.DataFrame([row])).isoformat() == "2023-12-29"
    row["outcome_date_h20"] = pd.Timestamp("2024-01-02")
    with pytest.raises(module.StrongRecoveryAvoidanceError, match="post-2023 outcome"):
        module.validate_outcome_boundary(pd.DataFrame([row]))


def test_deterministic_serialization_sorts_and_cleans_nonfinite_values() -> None:
    module = _module()
    value = {"z": np.float64(np.nan), "a": np.int64(3), "b": np.bool_(True)}
    first = module.deterministic_json(value)
    second = module.deterministic_json(value)
    assert first == second
    assert json.loads(first) == {"a": 3, "b": True, "z": None}
