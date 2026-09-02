import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_causal_formation_semantic_v4 as v4,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_primary_hierarchy_semantic_v3 as v3,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_zone_semantic_fidelity_v2 as v2,
)


def test_true_gap_and_v3_semantic_thresholds_are_unchanged() -> None:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    assert len(ledger) == 67_970
    assert ledger.high.lt(ledger.prev_low).all()
    assert np.allclose(ledger.true_gap_lower_raw, ledger.high)
    assert np.allclose(ledger.true_gap_upper_raw, ledger.prev_low)
    assert not (ledger.importance.eq("MINOR") & ledger.collapse_primary_eligible).any()
    assert ~ledger.future_depth_used_to_define_gap_identity.any()
    spec = json.loads(v4.SPEC.read_text())
    assert spec["hard_freezes"]["memory"] == {"CORE": "age<=60", "BOUNDARY": "61<=age<=90", "STALE": "age>90"}
    assert spec["hard_freezes"]["persistence"].startswith(">=10")


def test_leg_confirmation_is_tenth_completed_session_after_end() -> None:
    anchors = pd.read_parquet(v4.ANCHORS)
    assert len(anchors) == 4_319
    assert anchors.leg_confirmation_time.gt(anchors.leg_end_time).all()
    assert anchors.original_collapse_leg_duration_sessions.gt(0).all()
    assert anchors.leg_confirmation_time.max() < pd.Timestamp("2024-01-01")


def test_causal_primary_is_frozen_at_confirmation_and_is_lowest_unresolved() -> None:
    states = pd.read_parquet(v4.FREEZE_GAPS)
    primary = pd.read_parquet(v4.CAUSAL_PRIMARY)
    expected = states.loc[states.unresolved_at_confirmation].groupby("collapse_episode_id", sort=False).true_gap_lower.min()
    observed = primary.set_index("collapse_episode_id").true_gap_lower
    assert np.allclose(observed, expected.loc[observed.index])
    assert primary.primary_gap_freeze_time.eq(primary.leg_confirmation_time).all()
    assert ~primary.primary_gap_frozen_before_confirmation.any()
    assert primary.importance.isin(["MAJOR", "SECONDARY"]).all()
    assert primary.in_original_impulsive_collapse_leg.all()


def test_final_disposition_is_mutually_exclusive_and_complete() -> None:
    cross = pd.read_parquet(v4.CROSSWALK)
    allowed = {
        "RETAINED_CAUSAL_FIRST_RETURN",
        "REJECTED_RETURN_BEFORE_LEG_END",
        "REJECTED_RETURN_AFTER_END_BEFORE_CONFIRMATION",
        "REJECTED_PRECONFIRM_PRIMARY_TOUCH",
        "PRIMARY_CHANGED_AT_CAUSAL_FREEZE",
        "NO_CAUSAL_PRIMARY",
    }
    assert len(cross) == 4_319
    assert set(cross.final_disposition) == allowed
    assert cross.final_disposition.notna().all()
    assert cross.source_memory_state.value_counts().to_dict() == {"CORE": 3_822, "BOUNDARY": 497}


def test_retained_events_are_strictly_causal_and_never_reset_touch_clock() -> None:
    cross = pd.read_parquet(v4.CROSSWALK)
    retained = cross.loc[cross.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN")]
    assert len(retained) == 1_793
    assert retained.causal_first_return_time.gt(retained.leg_confirmation_time).all()
    assert ~retained.preconfirm_primary_touch.any()
    assert ~cross.preconfirm_touch_reset_as_new_first_return.any()
    assert retained.v3_primary_gap_id.eq(retained.causal_primary_gap_id).all()


def test_required_tg3_regressions_have_exact_causal_dispositions() -> None:
    rows = pd.read_parquet(v4.REGRESSIONS).set_index("chart_id")
    assert rows.loc["TG3-008", "final_disposition"] == "NO_CAUSAL_PRIMARY"
    assert rows.loc["TG3-013", "final_disposition"] == "NO_CAUSAL_PRIMARY"
    assert rows.loc["TG3-009", "final_disposition"] == "REJECTED_RETURN_AFTER_END_BEFORE_CONFIRMATION"
    assert rows.loc["TG3-014", "final_disposition"] == "PRIMARY_CHANGED_AT_CAUSAL_FREEZE"
    assert rows.loc["TG3-017", "final_disposition"] == "NO_CAUSAL_PRIMARY"
    assert rows.loc["TG3-019", "final_disposition"] == "RETAINED_CAUSAL_FIRST_RETURN"
    assert rows.loc["TG3-020", "final_disposition"] == "REJECTED_RETURN_AFTER_END_BEFORE_CONFIRMATION"


def test_duration_diagnostic_is_complete_without_new_segmentation() -> None:
    duration = pd.read_parquet(v4.DURATION)
    assert duration.duration_group.tolist() == ["<=20", "21-40", "41-60", "61-90", ">90"]
    assert duration.episode_count.sum() == 4_319
    assert duration.retained_causal_candidate_count.sum() == 1_793
    assert duration.true_gaps_in_leg.ge(duration.major_gaps_in_leg + duration.secondary_gaps_in_leg).all()
    spec = json.loads(v4.SPEC.read_text())
    assert spec["duration_diagnostic"]["segmentation_changed"] is False
    assert spec["duration_diagnostic"]["maximum_duration_rule_added"] is False


def test_new_blind_and_protracted_chart_packages_have_frozen_mix() -> None:
    blind = pd.read_csv(v4.BLIND_INDEX)
    diagnostic = pd.read_csv(v4.DIAGNOSTIC_INDEX)
    review = pd.read_csv(v4.REVIEW)
    protracted = pd.read_csv(v4.PROTRACTED_INDEX)
    retained = pd.read_parquet(v4.CANDIDATES)
    selected = diagnostic[["candidate_id"]].merge(retained[["candidate_id", "source_memory_state", "board"]], on="candidate_id", validate="one_to_one")
    assert len(blind) == len(diagnostic) == len(review) == 20
    assert selected.source_memory_state.value_counts().to_dict() == {"CORE": 14, "BOUNDARY": 6}
    assert selected.board.value_counts().to_dict() == {"MAIN": 13, "CHINEXT": 7}
    assert blind.post_event_bars.eq(0).all() and diagnostic.post_event_bars.eq(0).all()
    assert review.PATTERN_MATCH.isna().all()
    assert protracted.duration_group.value_counts().to_dict() == {">90": 10, "41-60": 5, "61-90": 5}
    assert all(Path(path).is_file() for path in blind.path)
    assert all(Path(path).is_file() for path in protracted.path)


def test_package_has_no_outcomes_and_never_crosses_2024() -> None:
    frames = [pd.read_parquet(v4.CROSSWALK), pd.read_parquet(v4.CANDIDATES), pd.read_parquet(v4.DURATION), pd.read_parquet(v4.REGRESSIONS), pd.read_csv(v4.REVIEW)]
    forbidden = ("pnl", "net_return", "gross_return", "exit_price", "win_rate", "sharpe", "cagr", "target_hit")
    assert not [column for frame in frames for column in frame if any(token in column.lower() for token in forbidden)]
    assert pd.read_parquet(v4.CANDIDATES).causal_first_return_time.max() < pd.Timestamp("2024-01-01")
    result = json.loads(v4.RESULT.read_text())
    assert result["audit"]["return_analysis_run"] == "NO"
    assert result["audit"]["strategy_backtest_run"] == "NO"
    assert result["audit"]["repository_2024_plus_data_opened"] == "NO"
