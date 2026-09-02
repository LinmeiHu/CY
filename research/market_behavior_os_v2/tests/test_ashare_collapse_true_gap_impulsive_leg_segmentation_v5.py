import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_impulsive_leg_segmentation_v5 as v5,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_primary_hierarchy_semantic_v3 as v3,
)


def test_true_gap_and_v4_hard_semantics_are_unchanged() -> None:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    assert len(ledger) == 67_970
    assert ledger.high.lt(ledger.prev_low).all()
    assert np.allclose(ledger.true_gap_lower_raw, ledger.high)
    assert np.allclose(ledger.true_gap_upper_raw, ledger.prev_low)
    assert not (ledger.importance.eq("MINOR") & ledger.significance_primary_eligible).any()
    assert not ledger.future_depth_used_to_define_gap_identity.any()
    spec = json.loads(v5.SPEC.read_text())
    assert spec["intermediate_recovery_regime"]["condition_a"].endswith("1.15")
    assert "10 consecutive" in spec["intermediate_recovery_regime"]["condition_b"]
    assert spec["causal_termination"]["duration_cap"] is False


def test_recovery_regime_uses_fixed_running_low_and_ten_session_confirmation() -> None:
    states = pd.read_parquet(v5.RECOVERY_STATES)
    confirmed = states.loc[states.recovery_regime_confirmed]
    assert len(confirmed) > 0
    assert confirmed.material_collapse_active.all()
    assert confirmed.recovery_15pct.all()
    assert confirmed.recovery_floor_run.ge(10).all()
    assert confirmed.coord_close.ge(confirmed.running_low * 1.15).all()
    first = confirmed.sort_values(["collapse_episode_id", "trade_date"]).groupby("collapse_episode_id").head(1)
    assert len(first) == pd.read_parquet(v5.SEGMENTATION).recovery_regime_confirmation_time.notna().sum()


def test_original_episode_terminates_causally_and_never_reopens() -> None:
    segmentation = pd.read_parquet(v5.SEGMENTATION)
    assert len(segmentation) == 4_319
    assert segmentation.v5_segmentation_known_time.le(segmentation.leg_confirmation_time).all()
    early = segmentation.loc[segmentation.recovery_terminates_earlier]
    assert len(early) == 315
    assert early.v5_segmentation_known_time.eq(early.recovery_regime_confirmation_time).all()
    assert early.v5_leg_end_time.le(early.v5_segmentation_known_time).all()
    cross = pd.read_parquet(v5.CROSSWALK)
    assert not cross.retroactive_segmentation.any()


def test_later_material_decline_is_a_forward_new_episode() -> None:
    episodes = pd.read_parquet(v5.NEW_EPISODES)
    segmentation = pd.read_parquet(v5.SEGMENTATION)[["collapse_episode_id", "v5_segmentation_known_time"]]
    rows = episodes.merge(segmentation, on="collapse_episode_id", validate="one_to_one")
    assert len(rows) == 11
    assert rows.new_episode_peak_time.gt(rows.v5_segmentation_known_time).all()
    assert rows.new_episode_material_breach_time.gt(rows.new_episode_peak_time).all()
    assert rows.renewed_decline.ge(0.30).all()


def test_primary_freezes_after_segmentation_and_touch_is_never_reset() -> None:
    primary = pd.read_parquet(v5.PRIMARY)
    cross = pd.read_parquet(v5.CROSSWALK)
    assert primary.v5_primary_freeze_time.eq(primary.v5_segmentation_known_time).all()
    assert primary.importance.isin(["MAJOR", "SECONDARY"]).all()
    assert primary.gap_date.le(primary.v5_leg_end_time.dt.normalize()).all()
    assert not cross.primary_frozen_before_segmentation_known.any()
    assert not cross.pre_freeze_touch_reset_as_new_first_return.any()
    assert not cross.retained_first_return_before_primary_freeze.any()
    touched = cross.loc[cross.pre_freeze_primary_touch]
    assert touched.final_disposition.eq("REJECTED_PRE_FREEZE_TOUCH").all()


def test_tg4_concerns_show_undersegmentation_without_damaging_positive_regressions() -> None:
    rows = pd.read_parquet(v5.REGRESSIONS).set_index("chart_id")
    concerns = rows.loc[["TG4-016", "TG4-017", "TG4-019"]]
    assert concerns.final_disposition.eq("RETAINED_UNCHANGED").all()
    assert concerns.recovery_regime_confirmation_time.isna().all()
    positives = rows.loc[["TG4-001", "TG4-003", "TG4-007", "TG4-009", "TG4-013", "TG4-014", "TG4-015", "TG4-018"]]
    assert positives.v5_causal_first_return.notna().all()
    result = json.loads(v5.RESULT.read_text())
    assert result["verdict"] == "RECOVERY_REGIME_UNDERSEGMENTS_COLLAPSES"
    assert result["regression"]["positive_survival"] == 8


def test_blind_and_protracted_packages_are_complete_and_outcome_blind() -> None:
    blind = pd.read_csv(v5.BLIND_INDEX)
    diagnostic = pd.read_csv(v5.DIAGNOSTIC_INDEX)
    review = pd.read_csv(v5.REVIEW)
    protracted = pd.read_csv(v5.PROTRACTED_INDEX)
    assert len(blind) == len(diagnostic) == len(review) == 20
    assert len(protracted) == 20
    assert blind.post_event_bars.eq(0).all() and diagnostic.post_event_bars.eq(0).all()
    assert review.PATTERN_MATCH.isna().all()
    assert all(Path(path).is_file() for path in blind.path)
    assert all(Path(path).is_file() for path in protracted.path)
    source = pd.read_csv(v5.v4.PROTRACTED_INDEX)
    assert set(protracted.collapse_episode_id) == set(source.collapse_episode_id)
    result = json.loads(v5.RESULT.read_text())
    assert result["new_pilot"]["main_count"] == 13
    assert result["new_pilot"]["chinext_count"] == 7
    assert result["new_pilot"]["duration_mix"] == {"<=20": 5, "21-40": 5, "41-60": 4, "61-90": 3, ">90": 3}


def test_no_outcome_fields_and_no_2024_access() -> None:
    frames = [
        pd.read_parquet(v5.CROSSWALK), pd.read_parquet(v5.CANDIDATES),
        pd.read_parquet(v5.REGRESSIONS), pd.read_parquet(v5.DURATION), pd.read_csv(v5.REVIEW),
    ]
    forbidden = ("pnl", "net_return", "gross_return", "exit_price", "win_rate", "sharpe", "cagr", "target_hit", "mfe", "mae")
    assert not [column for frame in frames for column in frame if any(token in column.lower() for token in forbidden)]
    candidates = pd.read_parquet(v5.CANDIDATES)
    assert candidates.v5_causal_first_return.max() < pd.Timestamp("2024-01-01")
    result = json.loads(v5.RESULT.read_text())
    assert result["audit"]["return_analysis_run"] == "NO"
    assert result["audit"]["strategy_backtest_run"] == "NO"
    assert result["audit"]["repository_2024_plus_data_opened"] == "NO"
