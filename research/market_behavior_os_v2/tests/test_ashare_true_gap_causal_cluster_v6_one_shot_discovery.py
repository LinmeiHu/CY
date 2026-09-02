import json

import pandas as pd

from research.market_behavior_os_v2.scripts import run_ashare_true_gap_causal_cluster_v6_one_shot_discovery as v6


def test_stage_a_freeze_and_causal_machine_gate() -> None:
    result = json.loads(v6.SEMANTIC_RESULT.read_text())
    assert v6.sha256(v6.SPEC) == v6.EXPECTED_SPEC_HASH
    assert result["v6_semantics_frozen"] == "YES"
    assert result["outcomes_opened"] == "NO"
    assert not {k: value for k, value in result["audit"].items() if k.endswith("_count") and value}
    for item in result["artifacts"].values():
        assert v6.sha256(v6.Path(item["path"])) == item["sha256"]


def test_true_gap_significance_is_formation_time_causal() -> None:
    gaps = pd.read_parquet(v6.CAUSAL_GAPS)
    assert len(gaps) == 120_038
    assert gaps.high.lt(gaps.prev_low_raw).all()
    assert gaps.true_gap_lower.lt(gaps.true_gap_upper).all()
    assert gaps.importance.isin(["MAJOR", "SECONDARY", "MINOR"]).all()
    assert not gaps.future_information_used_for_gap_significance.any()
    assert gaps.reference_high_date.lt(gaps.gap_date).all()


def test_cluster_freeze_touch_and_first_return_are_causal() -> None:
    clusters = pd.read_parquet(v6.CLUSTER_LEDGER)
    candidates = pd.read_parquet(v6.CANDIDATE_LEDGER)
    retained = clusters.loc[clusters.final_disposition.eq("RETAINED_CAUSAL_FIRST_RETURN")]
    assert len(candidates) == 4_454
    assert not retained.pre_freeze_touch.fillna(False).any()
    assert pd.to_datetime(candidates.causal_first_return).gt(pd.to_datetime(candidates.cluster_freeze_time)).all()
    assert candidates.memory_state.value_counts().to_dict() == {"CORE": 3615, "STALE": 495, "BOUNDARY": 344}
    assert clusters.final_disposition.eq("SUPERSEDED_BY_NEW_LOWER_CLUSTER").sum() == 2_686


def test_tg5_regressions_are_complete_before_outcomes() -> None:
    regression = pd.read_parquet(v6.TG5_REGRESSION)
    assert len(regression) == 20
    assert regression.chart_id.tolist() == [f"TG5-{i:03d}" for i in range(1, 21)]
    assert regression.regression_status.value_counts().to_dict() == {
        "EXACT_PRIMARY_SURVIVES": 13,
        "LOCAL_CLUSTER_PRIMARY_DIFFERS": 7,
    }


def test_entry_search_can_confirm_after_signal_day_and_never_same_bar() -> None:
    candidates = pd.read_parquet(v6.CANDIDATE_LEDGER, columns=["candidate_id", "causal_first_return"])
    confirmations = pd.read_parquet(v6.CONFIRMATIONS)
    entries = pd.read_parquet(v6.ENTRIES)
    source = entries.merge(
        candidates.rename(columns={"causal_first_return": "candidate_first_return"}),
        on="candidate_id",
    )
    assert len(confirmations) == 3_925
    assert len(entries) == 3_897
    assert pd.to_datetime(source.entry_time).gt(pd.to_datetime(source.confirmation_time)).all()
    assert pd.to_datetime(source.confirmation_date).gt(
        pd.to_datetime(source.candidate_first_return).dt.normalize()
    ).any()
    assert not source.entry_uses_future_bar.any()


def test_fixed_trade_lanes_t1_cost_and_no_2024() -> None:
    trades = pd.read_parquet(v6.TRADES)
    assert set(trades.time_stop.unique()) == {10, 20, 40}
    assert len(trades) == len(pd.read_parquet(v6.ENTRIES)) * 3
    target = trades.loc[trades.exit_reason.eq("TARGET")]
    assert target.exit_cal_idx.gt(target.entry_cal_idx).all()
    assert pd.to_datetime(trades.signal_date).max() < pd.Timestamp("2024-01-01")
    assert pd.to_datetime(trades.exit_date).dropna().max() < pd.Timestamp("2024-01-01")


def test_portfolio_and_final_result_audits() -> None:
    result = json.loads(v6.OUTCOME_RESULT.read_text())
    assert result["semantic_gate"] == "PASS"
    assert result["v6_frozen"] == "YES"
    assert result["verdict"] == "V6_CAUSAL_TRUE_GAP_STRUCTURE_ONLY"
    assert result["best_descriptive_t"] == 40
    assert not {k: value for k, value in result["audit"].items() if k.endswith("_count") and value}
    assert result["audit"]["repository_2024_plus_data_opened"] == "NO"
    assert result["development"]["structural"]["CORE_PLUS_BOUNDARY"]["signal_count"] == 3_324
    for horizon in (10, 20, 40):
        item = result["development"]["summary"]["CORE_PLUS_BOUNDARY"][f"T{horizon}"]["COMBINED"]["10"]
        assert item["signals"] == 3_324
        assert item["cagr"] < 0
        assert item["mean_net_trade_return"] < 0 < item["median_net_trade_return"]


def test_portfolio_ledger_has_no_leverage_or_limit_violation() -> None:
    nav = pd.read_parquet(v6.NAV)
    assert nav.cash.min() >= -1e-12
    assert nav.active_positions.ge(0).all()
    assert (nav.gross_exposure <= nav.nav + 1e-12).all()
    for k in (5, 10, 20):
        assert nav.loc[nav.k.eq(k), "active_positions"].max() <= 2 * k
