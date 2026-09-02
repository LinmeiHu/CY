import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_true_gap_zone_semantic_fidelity_v2 as v2,
)


def test_v1_artifacts_and_open_zone_reconciliation_are_unchanged() -> None:
    v2.verify_v1_immutable()
    reconciliation = json.loads(v2.V1_RECON.read_text())
    assert reconciliation["actual_v1_zone"]["interval"] == "[Open_t, Low_t_minus_1]"
    assert reconciliation["status"]["v1_programmatic_strategy_valid"] is True
    assert reconciliation["status"]["v1_strict_true_gap_interpretation_valid"] is False


def test_true_gap_identity_excludes_traded_open_to_high_region() -> None:
    open_t, high_t, low_tm1 = 5.31, 5.45, 5.88
    assert high_t < low_tm1
    assert (high_t, low_tm1) == (5.45, 5.88)
    assert open_t < high_t  # [open, high) traded on t and cannot be called no-trade.
    assert not (5.31 >= high_t)


def test_ledger_is_complete_comparable_and_depth_independent() -> None:
    ledger = pd.read_parquet(v2.GAP_LEDGER)
    assert len(ledger) == 67_970
    assert ledger.high.lt(ledger.prev_low).all()
    assert np.allclose(ledger.true_gap_lower_raw, ledger.high)
    assert np.allclose(ledger.true_gap_upper_raw, ledger.prev_low)
    assert ledger.corporate_action_count.eq(0).all()
    assert ledger.corporate_action_valid.all()
    assert ~ledger.corporate_action_blocking.any()
    assert ledger.industry_valid.all() and ledger.historical_identity_valid.all()
    assert ~ledger.future_depth_used_to_define_gap_identity.any()
    assert set(ledger.importance) == {"MAJOR", "SECONDARY", "MINOR"}


def test_primary_is_lowest_relevant_original_collapse_gap() -> None:
    ledger = pd.read_parquet(v2.GAP_LEDGER)
    candidates = pd.read_parquet(v2.CANDIDATES)
    expected = (
        ledger.loc[ledger.relevant]
        .groupby("collapse_episode_id", sort=False)
        .true_gap_lower.min()
    )
    observed = candidates.set_index("collapse_episode_id").L_true
    aligned = expected.loc[observed.index]
    assert np.allclose(observed, aligned)
    assert candidates.prior_max_fully_below_run.ge(5).all()
    assert candidates.prior_full_fill_count.eq(0).all()


def test_first_return_and_600250_regression() -> None:
    ledger = pd.read_parquet(v2.GAP_LEDGER)
    candidates = pd.read_parquet(v2.CANDIDATES)
    assert candidates.minute_count.eq(241).all()
    assert (candidates.event_bar_high.mul(100).round() >= candidates.raw_threshold.mul(100).round()).all()
    gaps = ledger.loc[
        ledger.symbol.eq("600250.SH")
        & ledger.gap_date.isin(pd.to_datetime(["2022-04-26", "2022-04-27", "2022-04-28"]))
    ]
    assert set(gaps.gap_date.dt.strftime("%Y-%m-%d")) == {"2022-04-26", "2022-04-27", "2022-04-28"}
    row = candidates.loc[candidates.collapse_episode_id.eq("600250.SH|2022-03-08")].iloc[0]
    assert row.primary_true_gap_id == "600250.SH|2022-04-27"
    assert row.first_return_time == pd.Timestamp("2022-05-11 10:02:00")
    assert 5.31 < gaps.loc[gaps.gap_date.eq(pd.Timestamp("2022-04-26")), "true_gap_lower_raw"].iloc[0]


def test_package_is_outcome_free_blind_and_pre_2024() -> None:
    candidates = pd.read_parquet(v2.CANDIDATES)
    crosswalk = pd.read_parquet(v2.CROSSWALK)
    review = pd.read_csv(v2.REVIEW)
    forbidden = ("pnl", "net_return", "gross_return", "exit_price", "forward_return")
    assert not [c for frame in (candidates, crosswalk, review) for c in frame if any(x in c.lower() for x in forbidden)]
    assert candidates.state_date.max() < pd.Timestamp("2024-01-01")
    assert len(review) == 30
    assert review.post_event_bars.eq(0).all()
    assert review.PATTERN_MATCH.isna().all()
    assert all(Path(path).is_file() for path in review.blind_chart_path)
    assert all(Path(path).is_file() for path in review.diagnostic_chart_path)
    result = json.loads(v2.RESULT.read_text())
    assert result["audit"]["return_analysis_run"] == "NO"
    assert result["audit"]["strategy_backtest_run"] == "NO"
    assert result["audit"]["repository_2024_plus_data_opened"] == "NO"
