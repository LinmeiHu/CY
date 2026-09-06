import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image, ImageChops

SCRIPT = Path(__file__).resolve().parents[1] / (
    "scripts/run_ashare_industry_residual_serial_phase_change_mother_v31_charts.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("v31_charts", SCRIPT)
assert MODULE_SPEC and MODULE_SPEC.loader
charts = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(charts)


def chart_event(**overrides: object) -> pd.Series:
    values: dict[str, object] = {
        "event_id": "event",
        "chart_number": 1,
        "symbol": "000001.SZ",
        "signal_date": pd.Timestamp("2019-01-04"),
        "causal_industry": "TEST",
        "prior_serial_dependence": -0.2,
        "recent_serial_dependence": 0.3,
        "serial_phase_change": 0.5,
        "current_residual_return": 0.01,
        "status": "COMPLETED",
        "outcome_bucket": "PROFIT_GE_4PCT",
        "net_return": 0.05,
        "entry_cal_idx": 101.0,
        "entry_price": 10.5,
        "target_price": 11.55,
        "exit_cal_idx": 103.0,
        "exit_price": 11.2,
        "exit_reason": "H20_TIME_STOP",
    }
    values.update(overrides)
    return pd.Series(values)


def chart_frame() -> pd.DataFrame:
    rows = []
    closes = [9.7, 9.9, 10.0, 10.5, 10.7, 11.2, 11.0]
    for relative, close in zip(range(-3, 4), closes, strict=True):
        rows.append(
            {
                "trade_date": pd.Timestamp("2019-01-04") + pd.offsets.BDay(relative),
                "cal_idx": 100 + relative,
                "relative_session": relative,
                "coord_open": close - 0.1,
                "coord_high": close + 0.2,
                "coord_low": close - 0.2,
                "coord_close": close,
                "turnover_fraction": 0.01 + (relative + 3) * 0.001,
                "current_valid": True,
                "hard_valid": True,
            }
        )
    return pd.DataFrame(rows)


def assert_images_equal(left: Path, right: Path) -> None:
    with Image.open(left) as left_image, Image.open(right) as right_image:
        assert ImageChops.difference(left_image, right_image).getbbox() is None


def test_outcome_bucket_boundaries_are_mutually_exclusive() -> None:
    assert charts.outcome_bucket("COMPLETED", 0.04) == "PROFIT_GE_4PCT"
    assert charts.outcome_bucket("COMPLETED", np.nextafter(0.04, 0.0)) == "PROFIT_0_TO_4PCT"
    assert charts.outcome_bucket("COMPLETED", 0.0) == "PROFIT_0_TO_4PCT"
    assert charts.outcome_bucket("COMPLETED", -0.0) == "PROFIT_0_TO_4PCT"
    assert charts.outcome_bucket("COMPLETED", -1e-12) == "LOSS_0_TO_10PCT"
    assert charts.outcome_bucket("COMPLETED", np.nextafter(-0.10, 0.0)) == "LOSS_0_TO_10PCT"
    assert charts.outcome_bucket("COMPLETED", -0.10) == "SEVERE_LOSS"
    assert charts.outcome_bucket("COMPLETED", np.nan) == "NO_COMPLETED_TRADE"
    assert charts.outcome_bucket("NO_LEGAL_ENTRY", 0.50) == "NO_COMPLETED_TRADE"


def test_post_signal_values_and_markers_cannot_change_pre_plot_pixels(tmp_path: Path) -> None:
    baseline_frame = chart_frame()
    changed_frame = baseline_frame.copy()
    post = changed_frame.relative_session.gt(0)
    changed_frame.loc[post, ["coord_open", "coord_high", "coord_low", "coord_close"]] *= 7.0
    changed_frame.loc[post, "turnover_fraction"] *= 100.0

    baseline = tmp_path / "baseline.png"
    changed = tmp_path / "changed.png"
    charts.render_chart(chart_event(), baseline_frame, baseline, reveal_post=True)
    charts.render_chart(
        chart_event(
            status="COMPLETED",
            outcome_bucket="SEVERE_LOSS",
            net_return=-0.25,
            entry_cal_idx=102.0,
            entry_price=74.0,
            target_price=81.4,
            exit_cal_idx=103.0,
            exit_price=70.0,
            exit_reason="TARGET_HIT",
        ),
        changed_frame,
        changed,
        reveal_post=True,
    )

    with Image.open(baseline) as baseline_image, Image.open(changed) as changed_image:
        baseline_pre = baseline_image.crop(charts.PRE_PLOT_BOX)
        changed_pre = changed_image.crop(charts.PRE_PLOT_BOX)
        assert ImageChops.difference(baseline_pre, changed_pre).getbbox() is None
        assert ImageChops.difference(baseline_image, changed_image).getbbox() is not None


def test_masked_chronology_image_has_no_post_signal_dependency(tmp_path: Path) -> None:
    baseline_frame = chart_frame()
    changed_frame = baseline_frame.copy()
    post = changed_frame.relative_session.gt(0)
    changed_frame.loc[post, ["coord_open", "coord_high", "coord_low", "coord_close"]] = np.nan
    changed_frame.loc[post, "turnover_fraction"] = 999.0
    changed_frame.loc[post, ["current_valid", "hard_valid"]] = False

    baseline = tmp_path / "masked_baseline.png"
    changed = tmp_path / "masked_changed.png"
    charts.render_chart(chart_event(), baseline_frame, baseline, reveal_post=False)
    charts.render_chart(
        chart_event(
            status="NO_LEGAL_ENTRY",
            outcome_bucket="NO_COMPLETED_TRADE",
            net_return=np.nan,
            entry_cal_idx=np.nan,
            entry_price=np.nan,
            target_price=np.nan,
            exit_cal_idx=np.nan,
            exit_price=np.nan,
            exit_reason="",
        ),
        changed_frame,
        changed,
        reveal_post=False,
    )

    assert charts.sha256(baseline) == charts.sha256(changed)
    assert_images_equal(baseline, changed)


def test_rendering_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    event = chart_event()
    frame = chart_frame()
    charts.render_chart(event, frame, first, reveal_post=True)
    charts.render_chart(event, frame, second, reveal_post=True)

    assert charts.sha256(first) == charts.sha256(second)
    assert_images_equal(first, second)


def write_identity_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, source_local_idx: int = 90
) -> None:
    signal_date = pd.Timestamp("2019-01-31")
    candidates = pd.DataFrame(
        [
            {
                "event_id": "event",
                "symbol": "000001.SZ",
                "causal_industry": "TEST",
                "signal_date": signal_date,
                "signal_cal_idx": 90,
            }
        ]
    )
    prepared = pd.DataFrame(
        [
            {
                "event_id": "event",
                "symbol": "000001.SZ",
                "causal_industry": "TEST",
                "signal_date": signal_date,
                "source_signal_cal_idx": source_local_idx,
                "signal_cal_idx": 100,
                "invalid_step_cum": 2.0,
                "decision_at": pd.Timestamp("2019-01-31 15:30:00"),
                "available_at": pd.Timestamp("2019-01-31 15:00:00"),
                "prior_serial_dependence": -0.2,
                "recent_serial_dependence": 0.3,
                "serial_phase_change": 0.5,
                "current_residual_return": 0.01,
                "raw_return_20": 0.02,
                "raw_return_60": 0.03,
                "return_volatility_60": 0.01,
                "turnover_ratio_1_to_60": 1.2,
            }
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "event_id": "event",
                "symbol": "000001.SZ",
                "causal_industry": "TEST",
                "signal_date": signal_date,
                "signal_cal_idx": 100,
                "signal_invalid_step_cum": 2.0,
                "target_return": charts.TARGET_RETURN,
                "horizon_sessions": charts.HORIZON_SESSIONS,
                "round_trip_cost": charts.ROUND_TRIP_COST,
                "status": "COMPLETED",
                "entry_date": pd.Timestamp("2019-02-01"),
                "entry_cal_idx": 101,
                "entry_price": 10.0,
                "target_price": 11.0,
                "exit_date": pd.Timestamp("2019-02-11"),
                "exit_cal_idx": 102,
                "exit_price": 10.5,
                "exit_reason": "H20_TIME_STOP",
                "net_return": 0.046,
            }
        ]
    )
    candidates_path = tmp_path / "candidates.parquet"
    prepared_path = tmp_path / "prepared.parquet"
    outcomes_path = tmp_path / "outcomes.parquet"
    future_paths_path = tmp_path / "future_paths.parquet"
    stage_b_result_path = tmp_path / "stage_b_result.json"
    candidates.to_parquet(candidates_path, index=False)
    prepared.to_parquet(prepared_path, index=False)
    outcomes.to_parquet(outcomes_path, index=False)
    future_paths_path.write_bytes(b"bound-for-test")

    frozen_hashes = {
        prepared_path: charts.sha256(prepared_path),
        future_paths_path: charts.sha256(future_paths_path),
        outcomes_path: charts.sha256(outcomes_path),
    }
    stage_b_result_path.write_text(
        charts.json.dumps(
            {
                "stage": "SEPARATELY_AUTHORIZED_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT",
                "post_2020_row_read": False,
                "charts_rendered": False,
                "portfolio_replay_performed": False,
                "prepared_candidates_sha256": frozen_hashes[prepared_path],
                "future_paths_sha256": frozen_hashes[future_paths_path],
                "outcomes_sha256": frozen_hashes[outcomes_path],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(charts, "CANDIDATES", candidates_path)
    monkeypatch.setattr(charts, "PREPARED", prepared_path)
    monkeypatch.setattr(charts, "OUTCOMES", outcomes_path)
    monkeypatch.setattr(charts, "FUTURE_PATHS", future_paths_path)
    monkeypatch.setattr(charts, "STAGE_B_RESULT", stage_b_result_path)
    monkeypatch.setattr(charts, "FIXED_HASHES", frozen_hashes)
    monkeypatch.setattr(charts, "EXPECTED_EVENTS", 1)
    monkeypatch.setattr(charts, "EXPECTED_LOCAL_TO_GLOBAL_OFFSET", 10)
    monkeypatch.setattr(charts, "EXPECTED_GLOBAL_SIGNAL_MIN", 100)
    monkeypatch.setattr(charts, "EXPECTED_GLOBAL_SIGNAL_MAX", 100)
    monkeypatch.setattr(charts, "SIGNAL_START", signal_date)
    monkeypatch.setattr(charts, "SIGNAL_END", signal_date)


def test_identity_audit_accepts_exact_local_to_global_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_identity_bundle(tmp_path, monkeypatch)
    prepared, outcomes = charts.load_and_audit_identities()

    assert prepared.loc[0, "source_signal_cal_idx"] == 90
    assert prepared.loc[0, "signal_cal_idx"] == 100
    assert outcomes.loc[0, "signal_cal_idx"] == 100


def test_identity_audit_rejects_local_stage_a_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_identity_bundle(tmp_path, monkeypatch, source_local_idx=91)

    with pytest.raises(charts.ResearchError, match="prepared source_signal_cal_idx"):
        charts.load_and_audit_identities()
