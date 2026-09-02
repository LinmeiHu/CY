import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_primary_hierarchy_semantic_v3 as v3,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_zone_semantic_fidelity_v2 as v2,
)


def test_true_gap_primitive_is_byte_semantically_unchanged() -> None:
    old = pd.read_parquet(v2.GAP_LEDGER).sort_values("true_gap_id").reset_index(drop=True)
    new = pd.read_parquet(v3.GAP_LEDGER).sort_values("true_gap_id").reset_index(drop=True)
    assert len(old) == len(new) == 67_970
    assert old.true_gap_id.equals(new.true_gap_id)
    assert np.allclose(old.true_gap_lower, new.true_gap_lower)
    assert np.allclose(old.true_gap_upper, new.true_gap_upper)
    assert new.high.lt(new.prev_low).all()
    assert ~new.future_depth_used_to_define_gap_identity.any()


def test_original_leg_termination_rule_is_satisfied() -> None:
    ends = pd.read_parquet(v3.LEG_ENDS)
    assert len(ends) == 52_839
    assert ends.drawdown_at_leg_end.ge(0.30).all()
    assert ends.next10_min_low.ge(0.95 * ends.original_leg_end_coord_low).all()
    assert ends.next10_major_gap_count.eq(0).all()
    assert ends.segmentation_rule.eq("FIRST_30PCT_TROUGH_WITH_10_SESSION_STABILIZATION").all()


def test_post_local_and_minor_gaps_stay_visible_but_cannot_be_primary() -> None:
    ledger = pd.read_parquet(v3.GAP_LEDGER)
    assert ledger.post_collapse_local_gap.any()
    assert not (ledger.post_collapse_local_gap & ledger.collapse_primary_eligible).any()
    assert ledger.importance.eq("MINOR").any()
    assert not (ledger.importance.eq("MINOR") & ledger.collapse_primary_eligible).any()
    assert ledger.loc[ledger.importance.eq("MAJOR") & ledger.in_original_impulsive_collapse_leg, "collapse_primary_eligible"].all()
    assert ledger.loc[ledger.importance.eq("SECONDARY") & ledger.in_original_impulsive_collapse_leg, "collapse_primary_eligible"].all()


def test_persistence_memory_and_first_return_contracts() -> None:
    events = pd.read_parquet(v3.ALL_GAP_EVENTS)
    assert events.gap_age_sessions.ge(10).all()
    assert events.prior_max_fully_below_run.ge(5).all()
    assert events.prior_full_fill_count.eq(0).all()
    assert events.first_return_reaches_true_l.all()
    assert events.loc[events.gap_age_sessions.le(60), "memory_state"].eq("CORE").all()
    assert events.loc[events.gap_age_sessions.between(61, 90), "memory_state"].eq("BOUNDARY").all()
    assert events.loc[events.gap_age_sessions.gt(90), "memory_state"].eq("STALE").all()


def test_lowest_active_eligible_in_leg_gap_is_selected() -> None:
    events = pd.read_parquet(v3.ALL_GAP_EVENTS)
    candidates = pd.read_parquet(v3.CANDIDATES)
    active_min = (
        events.loc[events.memory_state.isin(["CORE", "BOUNDARY"])]
        .groupby("collapse_episode_id", sort=False)
        .true_gap_lower.min()
    )
    observed = candidates.set_index("collapse_episode_id").true_gap_lower
    assert np.allclose(observed, active_min.loc[observed.index])
    assert candidates.importance.isin(["MAJOR", "SECONDARY"]).all()
    assert candidates.in_original_impulsive_collapse_leg.all()


def test_frozen_tg2_regressions() -> None:
    regression = pd.read_parquet(v3.REGRESSION).set_index("chart_id")
    assert regression.loc["TG2-015", "v3_final_status"] == "REJECTED_POST_COLLAPSE_LOCAL"
    assert regression.loc["TG2-018", "v3_final_status"] == "REJECTED_STALE"
    assert regression.loc["TG2-024", "v3_final_status"] == "CORE_CANDIDATE"
    # TG2-010 remains a legitimate multi-gap episode, but V3 replaces the old
    # layer because that old layer cannot establish the frozen persistence clock.
    assert regression.loc["TG2-010", "primary_changed"]
    assert regression.loc["TG2-010", "episode_v3_final_status"] == "CORE_CANDIDATE"
    assert regression.loc["TG2-010", "v3_final_status"] == "REJECTED_INSUFFICIENT_PERSISTENCE"


def test_new_pilot_is_exact_blind_mix_and_has_no_post_event_bars() -> None:
    review = pd.read_csv(v3.REVIEW)
    blind = pd.read_csv(v3.BLIND_INDEX)
    diagnostic = pd.read_csv(v3.DIAGNOSTIC_INDEX)
    candidates = pd.read_parquet(v3.CANDIDATES)
    selected = diagnostic[["candidate_id"]].merge(candidates[["candidate_id", "memory_state", "board", "episode_true_gap_count"]], on="candidate_id", validate="one_to_one")
    assert len(review) == len(blind) == len(diagnostic) == 20
    assert selected.memory_state.value_counts().to_dict() == {"CORE": 14, "BOUNDARY": 6}
    assert selected.board.value_counts().to_dict() == {"MAIN": 13, "CHINEXT": 7}
    assert selected.episode_true_gap_count.le(8).all()
    assert blind.post_event_bars.eq(0).all() and diagnostic.post_event_bars.eq(0).all()
    assert review.PATTERN_MATCH.isna().all()
    assert all(Path(path).is_file() for path in blind.path)
    assert all(Path(path).is_file() for path in diagnostic.path)


def test_package_has_no_outcome_fields_or_2024_reads() -> None:
    frames = [pd.read_parquet(v3.CANDIDATES), pd.read_parquet(v3.REGRESSION), pd.read_parquet(v3.MAPPING), pd.read_csv(v3.REVIEW)]
    forbidden = ("pnl", "net_return", "gross_return", "exit_price", "win_rate", "sharpe", "cagr")
    assert not [column for frame in frames for column in frame if any(token in column.lower() for token in forbidden)]
    assert pd.read_parquet(v3.CANDIDATES).first_return_time.max() < pd.Timestamp("2024-01-01")
    result = json.loads(v3.RESULT.read_text())
    assert result["audit"]["return_analysis_run"] == "NO"
    assert result["audit"]["strategy_backtest_run"] == "NO"
    assert result["audit"]["repository_2024_plus_data_opened"] == "NO"
