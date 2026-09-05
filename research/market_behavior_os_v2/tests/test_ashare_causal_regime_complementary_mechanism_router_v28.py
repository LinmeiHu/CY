from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import run_ashare_causal_regime_complementary_mechanism_router_v28 as v28  # noqa: E402


def _synthetic_book(first_exit_reason: str) -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
    dates = [pd.Timestamp(value) for value in ("2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08")]
    rows: list[dict] = []
    path_rows: list[dict] = []
    for index in range(30):
        entry_index = index // 10
        exit_index = 3 if index == 0 else 4
        exit_reason = first_exit_reason if index == 0 else "H20_TIME_STOP"
        event_id = f"seed-{index:02d}"
        rows.append(
            {
                "event_id": event_id,
                "symbol": f"600{index:03d}.SH",
                "sleeve": "MAIN",
                "signal_date": dates[entry_index] - pd.Timedelta(days=1),
                "entry_date": dates[entry_index],
                "entry_cal_idx": entry_index,
                "entry_price": 1.0,
                "exit_date": dates[exit_index],
                "exit_cal_idx": exit_index,
                "exit_price": 1.1 if exit_reason.startswith("TARGET_") else 1.0,
                "exit_reason": exit_reason,
                "holding_sessions": exit_index - entry_index,
                "gross_return": 0.1 if exit_reason.startswith("TARGET_") else 0.0,
                "net_return": 0.096 if exit_reason.startswith("TARGET_") else -0.004,
                "source_rank_order": index,
                "source": "TEST",
                "lane": "TEST",
            }
        )
        for date in dates[entry_index : exit_index + 1]:
            path_rows.append(
                {
                    "event_id": event_id,
                    "symbol": f"600{index:03d}.SH",
                    "trade_date": date,
                    "coord_open": 1.0,
                    "coord_high": 1.2,
                    "coord_close": 1.0,
                    "invalid_step_cum": 0.0,
                }
            )
    rows.append(
        {
            "event_id": "candidate",
            "symbol": "688888.SH",
            "sleeve": "MAIN",
            "signal_date": dates[2],
            "entry_date": dates[3],
            "entry_cal_idx": 3,
            "entry_price": 1.0,
            "exit_date": dates[4],
            "exit_cal_idx": 4,
            "exit_price": 1.0,
            "exit_reason": "H20_TIME_STOP",
            "holding_sessions": 1,
            "gross_return": 0.0,
            "net_return": -0.004,
            "source_rank_order": 0,
            "source": "TEST",
            "lane": "TEST",
        }
    )
    for date in dates[3:]:
        path_rows.append(
            {
                "event_id": "candidate",
                "symbol": "688888.SH",
                "trade_date": date,
                "coord_open": 1.0,
                "coord_high": 1.0,
                "coord_close": 1.0,
                "invalid_step_cum": 0.0,
            }
        )
    return pd.DataFrame(rows), pd.DataFrame(path_rows), dates


def _redirect_outputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(v28, "ACCEPTED", tmp_path / "accepted.parquet")
    monkeypatch.setattr(v28, "SKIPPED", tmp_path / "skipped.parquet")
    monkeypatch.setattr(v28, "NAV", tmp_path / "nav.parquet")


def test_intraday_target_does_not_finance_same_open(monkeypatch, tmp_path: Path) -> None:
    _redirect_outputs(monkeypatch, tmp_path)
    trades, paths, dates = _synthetic_book("TARGET_10")
    accepted, skipped, _nav, audit = v28.replay_shared_portfolio(trades, paths, dates)
    assert len(accepted) == 30
    assert skipped.loc[skipped.event_id.eq("candidate"), "skip_reason"].item() == "MAX_K_30"
    assert audit["target_cash_reused_at_same_open_count"] == 0


def test_open_exit_releases_capacity_before_same_open(monkeypatch, tmp_path: Path) -> None:
    _redirect_outputs(monkeypatch, tmp_path)
    trades, paths, dates = _synthetic_book("H20_TIME_STOP")
    accepted, skipped, _nav, _audit = v28.replay_shared_portfolio(trades, paths, dates)
    assert len(accepted) == 31
    assert "candidate" in set(accepted.event_id)
    assert skipped.empty


def test_execution_audit_enforces_entry_open_target_high_and_t1() -> None:
    frame = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "signal_date": pd.Timestamp("2020-01-02"),
                "entry_date": pd.Timestamp("2020-01-03"),
                "entry_cal_idx": 1,
                "entry_price": 10.0,
                "exit_date": pd.Timestamp("2020-01-06"),
                "exit_cal_idx": 2,
                "exit_price": 11.0,
                "exit_reason": "TARGET_10",
                "gross_return": 0.1,
                "net_return": 0.096,
            }
        ]
    )
    paths = pd.DataFrame(
        [
            {
                "event_id": "e1",
                "trade_date": pd.Timestamp("2020-01-03"),
                "coord_open": 10.0,
                "coord_high": 10.5,
            },
            {
                "event_id": "e1",
                "trade_date": pd.Timestamp("2020-01-06"),
                "coord_open": 10.8,
                "coord_high": 11.1,
            },
        ]
    )
    assert all(value == 0 for value in v28.execution_audit(frame, paths).values())
    paths.loc[paths.trade_date.eq("2020-01-06"), "coord_high"] = 10.9
    assert v28.execution_audit(frame, paths)["target_above_daily_high_count"] == 1


def test_contract_freezes_only_complementary_source_lanes() -> None:
    contract = json.loads(v28.CONTRACT.read_text(encoding="utf-8"))
    routes = contract["routing"]
    assert routes["BEAR_WORSENING"]["source_lane"] == "BEAR_WORSENING_FAST_CAPITULATION"
    assert routes["BEAR_STABILIZING"]["source_lane"] == "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"
    assert routes["BULL_MEDIUM_PARTICIPATION"]["source_lane"] == "MEDIUM_PARTICIPATION"
    assert routes["EARLY_DIFFUSION"]["source_lane"] == "EARLY_TRANSITION"
    assert contract["routing"]["OTHER"]["action"] == "CASH"
    assert contract["governance"]["new_threshold_search"] is False
