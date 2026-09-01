from __future__ import annotations

import importlib.util
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/run_ashare_former_leader_prebreak_suffocation_v4.py"
)


@lru_cache(maxsize=1)
def _module():
    spec = importlib.util.spec_from_file_location(
        "former_leader_prebreak_suffocation_v4_test", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _features() -> pd.DataFrame:
    module = _module()
    frame = pd.read_parquet(module.FEATURES_EXTERNAL)
    for column in (
        "gap_date",
        "reclaim_date",
        "latest_prebreak_session",
        "earliest_reference_session",
    ):
        frame[column] = pd.to_datetime(frame[column])
    return frame


@lru_cache(maxsize=1)
def _result() -> dict:
    module = _module()
    return json.loads(module.RESULT.read_text(encoding="utf-8"))


def _event(entry_id: str, symbol: str, *, dryup: float = 0.5) -> dict:
    day = pd.Timestamp("2020-01-02")
    dates = [day + pd.offsets.BDay(i) for i in range(4)]
    return {
        "entry_id": entry_id,
        "gap_id": entry_id,
        "symbol": symbol,
        "reclaim_date": day,
        "bar_end_time": day + pd.Timedelta(hours=10),
        "entry_price": 10.0,
        "next_legal_open_date": dates[1],
        "t1_legal_open_price": 10.0,
        "t1_date": dates[1],
        "t2_date": dates[2],
        "t3_date": dates[3],
        "trigger_close": 10.0,
        "t1_close_price": 10.0,
        "t2_close_price": 10.0,
        "t3_close_price": 10.0,
        "prebreak_dryup_3_20": dryup,
        "strict_gap_width_pct": 0.1,
    }


def test_prebreak_sessions_are_strictly_before_reclaim():
    frame = _features().loc[lambda x: x.prebreak_dryup_3_20.notna()]
    assert frame.latest_prebreak_session.lt(frame.reclaim_date).all()
    assert frame.earliest_reference_session.lt(frame.reclaim_date).all()


def test_dryup_requires_exact_three_plus_seventeen_sessions():
    frame = _features().loc[lambda x: x.prebreak_dryup_3_20.notna()]
    assert frame.prebreak_count20.eq(20).all()
    assert frame.recent3_count.eq(3).all()
    assert frame.reference17_count.eq(17).all()


def test_dryup_formula_is_exact_median_ratio():
    frame = _features().loc[lambda x: x.prebreak_dryup_3_20.notna()]
    expected = frame.recent3_median / frame.reference17_median
    assert np.allclose(frame.prebreak_dryup_3_20, expected, rtol=0, atol=0)


def test_same_day_reclaims_use_prior_completed_sessions():
    frame = _features().loc[lambda x: x.reclaim_date.eq(x.gap_date) & x.prebreak_dryup_3_20.notna()]
    assert len(frame) > 0
    assert frame.latest_prebreak_session.lt(frame.gap_date).all()


def test_compression_uses_exact_last_two_over_prior_three():
    frame = _features().loc[lambda x: x.prebreak_compression_5.notna()]
    assert frame.last2_count.eq(2).all()
    assert frame.prior3_count.eq(3).all()
    expected = frame.last2_median / frame.prior3_median
    assert np.allclose(frame.prebreak_compression_5, expected, rtol=0, atol=0)


def test_fixed_dryup_bins_have_exact_boundaries():
    labels = pd.cut(
        pd.Series([0.30, 0.31, 0.50, 0.51, 0.70, 0.71, 1.00, 1.01]),
        [-np.inf, 0.30, 0.50, 0.70, 1.00, np.inf],
        labels=_module().DRYUP_BINS,
        right=True,
    )
    assert labels.astype(str).tolist() == [
        "<=0.30",
        "(0.30,0.50]",
        "(0.30,0.50]",
        "(0.50,0.70]",
        "(0.50,0.70]",
        "(0.70,1.00]",
        "(0.70,1.00]",
        ">1.00",
    ]


def test_duplicate_gap_rows_collapse_outcome_blind_to_unique_entries():
    module = _module()
    source = module.build_features()
    events = module.analysis_events(source)
    assert len(source) == 3746
    assert len(events) == 3734
    assert not events.entry_id.duplicated().any()
    duplicates = source.loc[source.source_gap_multiplicity.gt(1)]
    chosen = duplicates.loc[duplicates.entry_collapse_order.eq(1)]
    assert (
        chosen.groupby("entry_id")
        .strict_gap_width_pct.first()
        .equals(duplicates.groupby("entry_id").strict_gap_width_pct.max())
    )


def test_same_date_analysis_uses_minimum_five_events_and_separate_boards():
    module = _module()
    events = module.analysis_events(module.build_features())
    for sleeve in ("MAIN", "CHINEXT"):
        complete = events.loc[
            events.sleeve.eq(sleeve)
            & events.prebreak_dryup_3_20.notna()
            & events.t1_open_net.notna()
        ]
        counts = complete.groupby("reclaim_date").size()
        expected = int(counts[counts >= 5].sum())
        assert _result()["same_date"][sleeve]["eligible_events"] == expected
    assert _result()["audit"]["cross_board_contamination_count"] == 0


def test_same_date_residual_medians_are_exactly_zero():
    for sleeve in ("MAIN", "CHINEXT", "COMBINED_BOARD_DATES"):
        assert _result()["same_date"][sleeve]["maximum_absolute_residual_median"] == 0


def test_chronological_rule_is_fixed_and_never_uses_test_year():
    module = _module()
    assert all(train_end == test_year - 1 for _, train_end, test_year in module.FOLDS)
    result = _result()
    for sleeve in ("MAIN", "CHINEXT"):
        assert all(
            fold["training_use"] == "NONE_FIXED_RULE_ONLY"
            for fold in result["chronological"][sleeve]["folds"]
        )
    assert result["audit"]["test_year_used_in_own_chronological_rule_count"] == 0


def test_portfolio_enforces_k_cash_duplicates_and_forty_bp_cost():
    module = _module()
    calendar = pd.bdate_range("2020-01-02", periods=6)
    events = pd.DataFrame([_event(f"e{i}", f"S{i}", dryup=0.01 * i) for i in range(25)])
    nav, trades, metrics = module.simulate_portfolio(
        events, calendar, calendar[0], calendar[-1], "SUFFOCATION", 1.0
    )
    assert metrics["maximum_concurrent_positions"] == module.K == 20
    assert metrics["max_concurrent_positions_violation_count"] == 0
    assert metrics["negative_cash_or_leverage_violation_count"] == 0
    assert metrics["duplicate_position_entry_count"] == 0
    assert nav.cash.ge(-1e-12).all()
    expected = (1 - module.EXIT_COST) / (1 + module.ENTRY_COST) - 1
    assert np.allclose(trades.net_return, expected)
    assert module.ENTRY_COST == module.EXIT_COST == 0.002


def test_completed_result_keeps_validation_and_final_oos_sealed():
    result = _result()
    assert result["chronology_boundary"]["post_2021_outcome_read_count"] == 0
    assert result["chronology_boundary"]["validation_opened"] is False
    assert result["chronology_boundary"]["final_oos_opened"] is False
    for key, value in result["audit"].items():
        if key in ("validation_opened", "final_oos_opened"):
            assert value is False
        else:
            assert value == 0
