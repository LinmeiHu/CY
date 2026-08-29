import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_PIT = "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_phase6_frozen_lineage_invariants() -> None:
    summary = json.loads((REPORTS / "chinext_v1_phase6_exit_lineage_summary.json").read_text())
    assert summary["trade_count"] == 111
    assert summary["generic_reason_total"] == 34
    decomposition = summary["generic_decomposition"]
    assert decomposition["multiple_condition_count"] == 34
    assert decomposition["still_unresolved_count"] == 0
    assert summary["market_exit_trade_count"] == 77
    assert summary["individual_exit_trade_count"] == 0
    assert summary["set_change_exit_trade_count"] == 0
    assert summary["top20_exit_reason_distribution"] == {
        "MARKET_EXIT_CONFIRMED": 18,
        "MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE": 2,
    }
    assert digest(ROOT / "strategy/chinext_v1_exploratory.py") == EXPECTED_STRATEGY
    assert digest(REPORTS / "chinext_v1_pit_master_manifest.json") == EXPECTED_PIT

    lineage = list(csv.DictReader((REPORTS / "chinext_v1_phase6_trade_exit_lineage.csv").open(newline="")))
    assert len(lineage) == 111
    assert len({r["trade_id"] for r in lineage}) == 111
    frozen = json.loads((REPORTS / "chinext_v1_pit_replay_summary.json").read_text())
    assert frozen["execution"]["completed_round_trip_count"] == 111
    assert all(r["entry_execution_date"] and r["exit_execution_date"] for r in lineage)

    top20 = {r["trade_id"] for r in json.loads((REPORTS / "chinext_v1_winner_attribution_summary.json").read_text())["top20_trades"]}
    assert sum(r["trade_id"] in top20 for r in lineage) == 20
    intervals = {r["trade_id"]: (r["entry_execution_date"], r["exit_signal_date"]) for r in lineage}
    daily = list(csv.DictReader((REPORTS / "chinext_v1_phase6_daily_exit_state.csv").open(newline="")))
    assert daily
    assert all(r["trade_id"] in intervals for r in daily)
    assert all(intervals[r["trade_id"]][0] <= r["date"] <= intervals[r["trade_id"]][1] for r in daily)


def test_phase6_csvs_are_lf_only() -> None:
    for name in ("chinext_v1_phase6_trade_exit_lineage.csv", "chinext_v1_phase6_daily_exit_state.csv"):
        data = (REPORTS / name).read_bytes()
        assert b"\r\n" not in data
        assert b"\r" not in data
