from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from conftest import make_bar

from cyq_game.data.pit import (
    ExperimentRecord,
    FundamentalRecord,
    IndustryMembershipRecord,
    MarketRuleRecord,
    PITStore,
)

UTC = UTC


def test_bar_is_invisible_before_available_at(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    available = datetime(2024, 1, 3, 15, 30, tzinfo=UTC)
    bar = make_bar(date(2024, 1, 3), available_at=available)
    assert store.ingest_bars([bar], source="test", snapshot_id="s1", run_id="r1") == 1

    before = datetime(2024, 1, 3, 15, 29, tzinfo=UTC)
    after = datetime(2024, 1, 3, 15, 31, tzinfo=UTC)
    assert store.bars_as_of(bar.symbol, bar.trade_date, bar.trade_date, before) == []
    visible = store.bars_as_of(bar.symbol, bar.trade_date, bar.trade_date, after)
    assert len(visible) == 1
    assert visible[0].available_at == available


def test_unknown_market_rule_fails_closed_until_available(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    trade_date = date(2024, 1, 3)
    decision_at = datetime(2024, 1, 3, 9, 0, tzinfo=UTC)
    assert not store.rule_as_of("000001.SZ", "MAIN", trade_date, decision_at).known
    record = MarketRuleRecord(
        rule_id="MAIN-V1",
        board="MAIN",
        security_pattern="*.SZ",
        price_limit_pct=0.10,
        t_plus_one=True,
        lot_size=100,
        effective_from=date(2020, 1, 1),
        effective_to=None,
        available_at=datetime(2024, 1, 3, 8, 0, tzinfo=UTC),
        source="test",
        snapshot_id="rules-1",
        revision_id="1",
        run_id="r1",
    )
    assert store.ingest_market_rules([record]) == 1
    rule = store.rule_as_of("000001.SZ", "MAIN", trade_date, decision_at)
    assert rule.known and rule.lot_size == 100 and rule.t_plus_one


def test_final_holdout_taint_is_persistent(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    record = store.register_experiment(
        experiment_id="exp-1",
        hypothesis="PIT test",
        config_text="mode: research",
        run_id="r1",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert isinstance(record, ExperimentRecord)
    store.mark_holdout_tainted("exp-1")
    assert store.experiment("exp-1").final_holdout_tainted


def test_industry_membership_is_pit_effective_and_conflict_safe(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    symbol = "000001.SZ"
    records = [
        IndustryMembershipRecord(
            symbol=symbol,
            industry="BANK",
            effective_from=date(2024, 1, 1),
            effective_to=None,
            available_at=datetime(2024, 1, 2, 8, tzinfo=UTC),
            source="test",
            snapshot_id="industry-1",
            revision_id="1",
            run_id="r1",
        ),
        IndustryMembershipRecord(
            symbol=symbol,
            industry="FINANCE",
            effective_from=date(2024, 2, 1),
            effective_to=None,
            available_at=datetime(2024, 2, 2, 8, tzinfo=UTC),
            source="test",
            snapshot_id="industry-2",
            revision_id="1",
            run_id="r1",
        ),
    ]
    assert store.ingest_industry_memberships(records) == 2
    january = store.industry_memberships_as_of(
        [symbol], date(2024, 1, 31), datetime(2024, 1, 31, 9, tzinfo=UTC)
    )
    assert january[symbol].industry == "BANK"
    unpublished = store.industry_memberships_as_of(
        [symbol], date(2024, 2, 1), datetime(2024, 2, 1, 9, tzinfo=UTC)
    )
    assert unpublished[symbol].industry == "BANK"
    published = store.industry_memberships_as_of(
        [symbol], date(2024, 2, 2), datetime(2024, 2, 2, 9, tzinfo=UTC)
    )
    assert published[symbol].industry == "FINANCE"

    conflict = IndustryMembershipRecord(
        symbol=symbol,
        industry="CONFLICT",
        effective_from=date(2024, 2, 1),
        effective_to=None,
        available_at=datetime(2024, 2, 2, 8, tzinfo=UTC),
        source="test",
        snapshot_id="industry-3",
        revision_id="1",
        run_id="r1",
    )
    assert store.ingest_industry_memberships([conflict]) == 1
    ambiguous = store.industry_memberships_as_of(
        [symbol], date(2024, 2, 2), datetime(2024, 2, 2, 9, tzinfo=UTC)
    )
    assert symbol not in ambiguous


def test_fundamental_revisions_are_visible_only_after_disclosure(tmp_path: Path) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    symbol = "000001.SZ"

    def record(revision: str, available_at: datetime, growth: float) -> FundamentalRecord:
        return FundamentalRecord(
            symbol=symbol,
            period_end=date(2024, 3, 31),
            event_time=available_at,
            available_at=available_at,
            effective_from=available_at.date(),
            source="exchange-filing-test",
            snapshot_id="2024-q1",
            revision_id=revision,
            run_id="r1",
            revenue_growth=growth,
            profit_growth=0.12,
            roe=0.10,
            operating_cashflow_to_profit=1.0,
            debt_ratio=0.40,
            valuation_percentile=0.50,
            earnings_revision=0.0,
            investment_growth=0.08,
            capital_return=0.2,
            audit_or_going_concern_risk=False,
        )

    first_at = datetime(2024, 4, 25, 8, tzinfo=UTC)
    revised_at = datetime(2024, 5, 6, 8, tzinfo=UTC)
    assert store.ingest_fundamentals(
        [record("1", first_at, 0.10), record("2", revised_at, 0.04)]
    ) == 2
    assert (
        store.fundamental_as_of(
            symbol,
            date(2024, 4, 25),
            datetime(2024, 4, 25, 7, 59, tzinfo=UTC),
        )
        is None
    )
    initial = store.fundamental_as_of(
        symbol,
        date(2024, 5, 6),
        datetime(2024, 5, 6, 7, 59, tzinfo=UTC),
    )
    assert initial is not None
    assert initial.revision_id == "1"
    assert initial.revenue_growth == 0.10
    revised = store.fundamental_as_of(
        symbol,
        date(2024, 5, 6),
        datetime(2024, 5, 6, 8, 1, tzinfo=UTC),
    )
    assert revised is not None
    assert revised.revision_id == "2"
    assert revised.revenue_growth == 0.04


def test_fundamental_offsets_are_normalized_and_invalid_timing_is_rejected(
    tmp_path: Path,
) -> None:
    store = PITStore(tmp_path / "pit.sqlite3")
    store.initialize()
    china_release = datetime.fromisoformat("2024-04-25T16:00:00+08:00")
    record = FundamentalRecord(
        symbol="000001.SZ",
        period_end=date(2024, 3, 31),
        event_time=china_release,
        available_at=china_release,
        effective_from=date(2024, 4, 25),
        source="exchange-filing-test",
        snapshot_id="2024-q1-offset",
        revision_id="1",
        run_id="r1",
    )
    assert store.ingest_fundamentals([record]) == 1
    assert (
        store.fundamental_as_of(
            record.symbol,
            date(2024, 4, 25),
            datetime(2024, 4, 25, 7, 59, tzinfo=UTC),
        )
        is None
    )
    visible = store.fundamental_as_of(
        record.symbol,
        date(2024, 4, 25),
        datetime(2024, 4, 25, 8, 1, tzinfo=UTC),
    )
    assert visible is not None
    assert visible.available_at == datetime(2024, 4, 25, 8, tzinfo=UTC)

    try:
        FundamentalRecord(
            symbol="000001.SZ",
            period_end=date(2024, 3, 31),
            event_time=datetime(2024, 4, 25, 9, tzinfo=UTC),
            available_at=datetime(2024, 4, 25, 8, tzinfo=UTC),
            effective_from=date(2024, 4, 25),
            source="exchange-filing-test",
            snapshot_id="invalid",
            revision_id="1",
            run_id="r1",
        )
    except ValueError as error:
        assert "event_time" in str(error)
    else:
        raise AssertionError("future event_time should be rejected")
