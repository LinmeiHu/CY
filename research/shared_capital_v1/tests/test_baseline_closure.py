import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from five_strategy_bundle.compare import compare_parquet as production_compare
from five_strategy_bundle.strategies.smv6 import CashPlatform
from research.shared_capital_v1.causal_adapters import CausalCashPlatform, entered_population, select_fast_capacity
from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount
from research.shared_capital_v1.validation import account_validation, compare_layers, compare_parquet, validation_status
from research.shared_capital_v1.causal_adapters import causal_fixed_target_outcomes
from research.shared_capital_v1.stock_p0 import replay


def platform(cls, future_close=10.0, minute_close=10.0, missing=False):
    day = pd.Timestamp("2020-01-03")
    daily = {s: pd.DataFrame({"pre_adj_close": [10., future_close], "volume_raw": [1000., 1000.], "amount_cny": [10000., 10000.]}, index=[day-pd.Timedelta(days=1), day]) for s in ("A", "B")}
    minute = {s: pd.DataFrame([{"trade_date": day.date(), "bar_role": "OPEN_BAR_09_30", "pre_adj_open": np.nan if missing and s == "A" else 10., "pre_adj_close": np.nan if missing and s == "A" else minute_close, "volume_shares": 1_000_000.}]) for s in daily}
    avail = pd.DataFrame([{"trade_date": day.date(), "symbol": s, "executable_09_30": True} for s in daily])
    p = cls(daily, minute, avail, [day], initial_cash=10000., lot_size=100, fee_bps=2.)
    p.event_stage = "open"
    p.shares["A"] = 100
    return p


def test_legacy_smv6_future_close_defect_reproduced():
    a, b = platform(CashPlatform, missing=True), platform(CashPlatform, future_close=1000., missing=True)
    a.order_target_percent("B", .5)
    b.order_target_percent("B", .5)
    assert a.events[-1]["requested_qty"] != b.events[-1]["requested_qty"]


def test_future_close_and_unfinished_open_bar_cannot_change_order():
    a, b = platform(CausalCashPlatform), platform(CausalCashPlatform, future_close=1000., minute_close=500.)
    a.order_target_percent("B", .5)
    b.order_target_percent("B", .5)
    assert a.events == b.events
    assert a.cash == b.cash and a.shares == b.shares


def test_missing_legal_mark_fails_before_order_mutation():
    for future in (10., 1000.):
        p = platform(CausalCashPlatform, future_close=future, missing=True)
        with pytest.raises(RuntimeError, match="MISSING_LEGAL_OPEN_MARK"):
            p.order_target_percent("B", .5)
        assert p.cash == 10000. and p.shares == {"A": 100} and not p.events


def test_history_excludes_current_incomplete_day():
    p = platform(CausalCashPlatform, future_close=1000.)
    assert p.history(["A"], ["close"], 10, "1d")["A"].close.tolist() == [10.]


def outcomes(status="COMPLETED"):
    return pd.DataFrame([dict(event_id="E1", symbol="A", sleeve="MAIN", signal_date=pd.Timestamp("2020-01-02"), entry_date=pd.Timestamp("2020-01-03"), entry_price=10., status=status, exit_date=pd.Timestamp("2020-02-01") if status == "COMPLETED" else pd.NaT, exit_reason="TARGET_10", stock_minus_industry_ret20=.2, close_vs_prior10_high=.1, close_location_x=.8)])


def test_future_completion_does_not_create_or_remove_entry(tmp_path):
    a, b = entered_population(outcomes("INCOMPLETE_PATH")), entered_population(outcomes())
    fields = ["event_id", "symbol", "entry_date", "entry_price"]
    pd.testing.assert_frame_equal(a[fields], b[fields])
    for frame in (a, b):
        assert select_fast_capacity(frame, tmp_path / "capacity.parquet").event_id.tolist() == ["E1"]
    assert outcomes("INCOMPLETE_PATH").loc[lambda f: f.status.eq("COMPLETED")].empty


@pytest.mark.parametrize("side,keys", [("actual", ["E1", "E1"]), ("golden", ["E1", "E1"]), ("actual", [None]), ("golden", [None]), ("actual", ["E1", "E2"])])
def test_comparison_identity_failures(tmp_path, side, keys):
    paths = {s: tmp_path / f"{s}.parquet" for s in ("actual", "golden")}
    for s, p in paths.items():
        ks = keys if s == side else ["E1"]
        pd.DataFrame({"id": ks, "v": [1.] * len(ks)}).to_parquet(p)
    assert compare_parquet(paths["actual"], paths["golden"], ["id"], ["v"])["status"] == "FAIL"
    assert production_compare(paths["actual"], paths["golden"], ["id"], ["v"])["status"] == "FAIL"


def test_many_to_many_and_missing_layers_fail(tmp_path):
    p = tmp_path / "dupes.parquet"
    pd.DataFrame({"id": ["E1", "E1"]}).to_parquet(p)
    assert compare_parquet(p, p, ["id"])["status"] == "FAIL"
    assert compare_layers([]).status.tolist() == ["FAIL"]
    assert compare_layers([{"layer": "required", "actual": str(p), "golden": str(tmp_path / "absent"), "keys": ["id"]}]).status.tolist() == ["FAIL"]


def test_comparison_cli_nonzero_and_generation_not_validation(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text("[]")
    result = subprocess.run([sys.executable, "-m", "research.shared_capital_v1.validation", "--spec", str(spec)], capture_output=True, text=True)
    assert result.returncode == 1
    assert validation_status("PASS", "FAIL", "PASS", "PASS")["status"] == "NOT_VALIDATED"


@pytest.mark.parametrize("field,value", [(f, v) for f in ("nav", "cash", "gross_exposure") for v in (np.nan, np.inf, -np.inf)])
def test_nonfinite_account_never_passes(field, value):
    frame = account_frame()
    frame.loc[0, field] = value
    assert account_validation(frame, frame.trade_date)["status"] == "FAIL"


def account_frame():
    return pd.DataFrame({"trade_date": pd.to_datetime(["2020-01-02", "2020-01-03"]), "cash": [50., 50.], "gross_exposure": [50., 50.], "nav": [100., 100.]})


def test_account_calendar_and_equation_fail_closed():
    frame = account_frame()
    assert account_validation(frame, frame.trade_date)["status"] == "PASS"
    assert account_validation(frame)["status"] == "UNKNOWN"
    assert account_validation(pd.concat([frame, frame]), frame.trade_date)["status"] == "FAIL"
    assert account_validation(frame.iloc[:1], frame.trade_date)["status"] == "FAIL"
    assert account_validation(frame.drop(columns="cash"), frame.trade_date)["status"] == "FAIL"
    for nav in (0., -1., 99.):
        broken = frame.copy(); broken.loc[0, "nav"] = nav
        assert account_validation(broken, frame.trade_date)["status"] == "FAIL"


def test_one_account_cannot_hide_another_accounts_missing_day():
    a = account_frame().assign(account_id="A")
    b = account_frame().iloc[:1].assign(account_id="B")
    assert account_validation(pd.concat([a, b]), a.trade_date, keys=("trade_date", "account_id"))["status"] == "FAIL"


def test_production_financing_auditor_rejects_nonfinite_and_unknown_calendar():
    from verify_no_financing import _audit_row
    frame = account_frame().rename(columns={"nav": "account_nav"})
    frame["gross_exposure_ratio"] = frame.gross_exposure / frame.account_nav
    frame["cash_ratio"] = frame.cash / frame.account_nav
    assert _audit_row("SMV6", "test", frame, frame, (0, 0, 0))["status"] == "UNKNOWN"
    bad = frame.copy(); bad.loc[0, "cash"] = np.nan
    assert _audit_row("SMV6", "test", bad, bad, (0, 0, 0), frame.trade_date)["status"] == "FAIL"


def intent(event="E1", strategy="ATRDR", qty=50000.):
    return Intent(strategy, "BULL", "DEMAND" if strategy in ("ATRDR", "MCB") else "GAP", event, "", "A", pd.Timestamp("2020-01-02 15:00"), pd.Timestamp("2020-01-03 09:30"), (0,), qty, 10., .002)


HOME = {s: 1_000_000. for s in ("ATRDR", "MCB", "OGR", "SMV6")}
WHEN = pd.Timestamp("2020-01-03 09:30")


def test_physical_virtual_equity_quantity_and_costs():
    p = PhysicalAccount("OGR")
    p.fund([intent(), intent("E2", "MCB")], HOME, "P0", WHEN)
    assert p.positions == {"A": 100000.}
    p.mark({"A": 11.})
    assert abs(p.checkpoint(WHEN, "MARK")["pnl_delta"]) < 1e-6
    p.close("E1", 11., WHEN + pd.Timedelta(days=1), .002)
    assert p.positions == {"A": 50000.}
    assert p.realized["ATRDR"] == pytest.approx(47900.)
    p.positions["A"] += 1
    with pytest.raises(ValueError, match="quantity"):
        p.checkpoint(WHEN, "CORRUPTION")


def test_base_first_shared_state_and_home_independent():
    p = PhysicalAccount("OGR")
    large = intent(qty=150000.)
    p.fund([large, intent("E2", "MCB")], HOME, "P1", WHEN)
    assert [f["funding_type"] for f in p.fills] == ["BASE", "SHARED"]
    assert p.lots["E1"]["funding_type"] == "SHARED"
    assert p.lots["E1"]["funded_notional"] <= large.native_requested_notional
    p.close("E1", 12., WHEN + pd.Timedelta(days=1), .002)
    assert HOME["ATRDR"] == 1_000_000.
    with pytest.raises(ValueError, match="enlarge"):
        p.fund([large], HOME, "P1", WHEN)


def test_starvation_no_financing_and_determinism():
    rows = []
    for _ in range(2):
        p = PhysicalAccount("OGR")
        p.fund([intent(qty=350000.)], HOME, "P1", WHEN)
        p.fund([intent("E2", "MCB", qty=90000.)], HOME, "P1", WHEN)
        assert p.shortfalls[0]["reason"] == "BASE_ENTITLEMENT_SHORTFALL"
        assert p.cash >= 0 and p.exposure() <= p.cash + p.exposure()
        rows.append(p.checkpoints)
    assert rows[0] == rows[1]


def test_exact_confirmation_mcb_only_and_gap_exclusion():
    p = PhysicalAccount("OGR")
    a = replace(intent(), parent_event_id="P")
    b = replace(intent("E2", "MCB"), parent_event_id="P")
    c = replace(intent("E3", "MCB"), symbol="B", parent_event_id="P")
    p.fund([c, b, a], HOME, "P0", WHEN, mcb_mode="confirmation_tag")
    assert set(p.lots) == {"E1", "E3"}
    with pytest.raises(ValueError, match="active strategy"):
        p.fund([intent("E4", "IFCGR")], HOME, "P0", WHEN)


def test_drawdown_gate_does_not_liquidate():
    p = PhysicalAccount("OGR")
    p.fund([intent()], HOME, "P0", WHEN)
    qty = p.positions.copy()
    p.fund([intent("E2", "MCB")], HOME, "P3_D4", WHEN, gate_multiplier=0.)
    assert p.positions == qty and "E2" not in p.lots


def test_gate_budget_is_not_reapplied_recursively_by_funding_phase():
    p = PhysicalAccount("OGR")
    requests = [replace(intent(f"E{n}", s, qty=90000.), symbol=str(n)) for n, s in enumerate(HOME)]
    p.fund(requests, HOME, "P3_D4", WHEN, gate_multiplier=.5)
    assert p.initial_cash - p.cash <= p.initial_cash * .5 + 1e-8


def test_largest_remainder_does_not_leave_affordable_whole_native_slot_idle():
    p = PhysicalAccount("OGR")
    requests = [replace(intent("A", "ATRDR", qty=250000.), symbol="A"), replace(intent("B", "MCB", qty=200000.), symbol="B")]
    p.fund(requests, HOME, "P1", WHEN)
    assert p.lots and p.cash < min(i.native_requested_notional for i in requests)


def test_atrdr_historical_prefix_entries_cash_positions_nav():
    dates = pd.bdate_range("2020-01-02", periods=5)
    rows = []
    for idx, day in enumerate(dates):
        rows.append(dict(symbol="A", trade_date=day, cal_idx=idx, coord_open=10., coord_close=10., coord_high=12. if idx == 4 else 10., open=10., close=10., coordinate_factor=1., corporate_action_count=0, up_limit_price=13., down_limit_price=8., invalid_step_cum=0., trade_status=1,
                         hard_valid=True, history_valid=True, current_valid=True, corporate_action_valid=True, current_day_data_tradable=True, historical_identity_valid=True,market_rule_valid=True, corporate_action_blocking=False))
    daily = pd.DataFrame(rows)
    signal = pd.DataFrame([dict(event_id="E1", symbol="A", sleeve="MAIN", signal_date=dates[0], cal_idx=0, invalid_step_cum=0.)])
    T = dates[3]
    replays = []
    for data in (daily.loc[daily.trade_date.le(T)], daily):
        out = causal_fixed_target_outcomes(signal, data, target=.1, horizon=20, profile="T10_H20_NO_STOP")
        entries = entered_population(out)
        entries["source_rank_order"] = 0
        entries["route"] = "BULL"
        account, intents, rejected, nav, blocker = replay("ATRDR", entries, data, str(dates[0].date()), str(T.date()))
        assert blocker is None
        replays.append((account, intents, nav))
    a, b = replays
    pd.testing.assert_frame_equal(a[1], b[1])
    pd.testing.assert_frame_equal(a[2], b[2])
    assert a[0].positions == b[0].positions and a[0].cash == b[0].cash


def test_coordinate_change_is_not_silently_marked_or_deleted():
    entries = outcomes()
    entries["source_rank_order"] = 0
    daily = pd.DataFrame({"symbol": ["A", "A"], "trade_date": pd.to_datetime(["2020-01-03", "2020-01-06"]), "coord_open": [10., 5.], "coord_close": [10., 5.], "invalid_step_cum": [0., 1.]})
    daily['open']=daily.coord_open; daily['close']=daily.coord_close; daily['coord_high']=daily.coord_close
    daily['coordinate_factor']=1.; daily['corporate_action_count']=0; daily['cal_idx']=[1,2]
    daily['trade_status']=1; daily['down_limit_price']=1.;daily['corporate_action_blocking']=False
    for field in ('hard_valid','history_valid','current_valid','corporate_action_valid','current_day_data_tradable','market_rule_valid','historical_identity_valid'):daily[field]=True
    entries['route']='BULL'
    account, _, _, nav, blocker = replay("ATRDR", entries, daily, "2020-01-01", "2020-01-31")
    assert blocker.startswith("ACTIVE_COORDINATE_LINEAGE_CHANGE")
    assert "E1" in account.lots and len(nav) == 1


def test_generation_command_required_comparison_failure_nonzero(tmp_path, monkeypatch):
    from five_strategy_bundle import reproduce as runner
    inp = tmp_path / "inputs.json"
    golden = tmp_path / "golden.json"
    inp.write_text(json.dumps({'inputs': {k: str(tmp_path) for k in ('daily_hist', 'daily_tail', 'mcb_market_industry_state')}}))
    golden.write_text('{"inputs": {}}')
    def generate(_inputs, target):
        target.mkdir(parents=True, exist_ok=True)
        return {"status": "FULL_END_TO_END_REPRODUCIBLE"}
    monkeypatch.setattr(runner, "run_mcb", generate)
    assert runner.main(["--strategy", "MCB", "--input-config", str(inp), "--golden-config", str(golden), "--output-root", str(tmp_path / "result")]) == 1
    result = json.loads((tmp_path / "result/mcb/result.json").read_text())
    assert result["GENERATION_STATUS"] == "PASS" and result["COMPARISON_STATUS"] == "FAIL"
    assert result["status"] == "NOT_VALIDATED"


def test_generation_failure_cannot_leave_a_stale_full_status(tmp_path, monkeypatch):
    from five_strategy_bundle import reproduce as runner
    inp = tmp_path / "inputs.json"
    inp.write_text('{"inputs": {}}')
    target = tmp_path / "mcb"
    target.mkdir()
    (target / "result.json").write_text('{"status":"FULL"}')
    def broken(*_):
        raise ValueError("broken producer")
    monkeypatch.setattr(runner, "run_mcb", broken)
    assert runner.main(["--strategy", "MCB", "--input-config", str(inp), "--output-root", str(tmp_path)]) == 1
    status = json.loads((target / "result.json").read_text())
    assert status["GENERATION_STATUS"] == "FAIL" and status["status"] == "NOT_VALIDATED"


def test_integral_native_request_survives_money_roundtrip():
    # This price makes (q * price) / price slightly smaller than q.
    when = pd.Timestamp('2020-01-03 09:30')
    for price in (1.2801, 1.0016, 1.0168, 3.5984, 4.2464):
        account = PhysicalAccount('OGR')
        intent = Intent('SMV6', 'NATIVE', 'ETF_TIMING', 'ROUND', '', 'ETF',
            pd.Timestamp('2020-01-02 15:00'), when, (0,), 100, price, 0., lot_size=100)
        account.fund([intent], {s: 1e6 for s in account.strategies}, 'P0', when)
        assert account.positions['ETF'] == 100
        assert account.cash >= 0


def test_continuous_initial_state_explicit_user_contract():
    contract = json.loads((Path(__file__).parents[1] / 'contracts/initial_state_v05.json').read_text())
    assert contract['formal_boundary'] == 'NATIVE_CONTINUOUS'
    assert contract['diagnostic_reset_results'] == 'CONTROL_ONLY_NOT_COMMON_P0'
    assert contract['missing_credit_state'].startswith('ACCOUNTING_BLOCKED')
