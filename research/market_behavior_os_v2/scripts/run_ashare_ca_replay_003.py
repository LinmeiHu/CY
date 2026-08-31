#!/usr/bin/env python3
"""Run the frozen independent strategies under one minimum QD-010 exit contract."""

from __future__ import annotations

import bisect
import hashlib
import importlib.util
import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CA-REPLAY-003_spec.json"
PRIOR_PANEL = PROGRAM / "artifacts/ASHARE-DIVERSIFIED-CYCLE-002_candidate_panel.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-CA-REPLAY-003_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-CA-REPLAY-003_risk_exits.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CA-REPLAY-003_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-CA-REPLAY-003_report.md"
PRIOR_SCRIPT = PROGRAM / "scripts/run_ashare_diversified_cycle_002.py"
EXPECTED_SPEC_SHA256 = "db71f4d03eefcba4f5e2b8c75913ddc1f92d475362a8cd91971ecd325145c90b"
COST = 0.002
FAMILIES = ("industry_diffusion_20", "low_idiosyncratic_volatility_20")


class CorporateActionReplayError(RuntimeError):
    """Fail-closed error for the frozen execution-contract replay."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_prior_module() -> Any:
    module_spec = importlib.util.spec_from_file_location("ashare_cycle_002", PRIOR_SCRIPT)
    if module_spec is None or module_spec.loader is None:
        raise CorporateActionReplayError("cannot load frozen prior runner")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


PRIOR = _load_prior_module()


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CorporateActionReplayError("execution-contract spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_EXECUTION_CONTRACT_AND_STRATEGY_GATES_BEFORE_REPLAY_OUTCOMES":
        raise CorporateActionReplayError("contract was not frozen before replay outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CorporateActionReplayError(f"bound input changed: {name}")
    if set(spec["frozen_replays"]) != set(FAMILIES):
        raise CorporateActionReplayError("frozen replay family set changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "no alpha", "no habitat", "no combined"):
        if phrase not in prohibited:
            raise CorporateActionReplayError(f"missing prohibition: {phrase}")
    return spec


@dataclass(frozen=True)
class RiskEvent:
    symbol: str
    event_id: str
    event_kind: str
    known_date: date
    decision_date: date | None
    effective_date: date


@dataclass
class Lot:
    symbol: str
    industry: str
    due_index: int
    shares: float
    invested_cost: float
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def _market_symbol(raw: str) -> str:
    value = str(raw).strip().split(".")[0]
    if len(value) != 6 or not value.isdigit():
        raise CorporateActionReplayError(f"invalid QD-010 symbol: {raw}")
    if value.startswith("6"):
        return f"{value}.SH"
    if value.startswith(("0", "3")):
        return f"{value}.SZ"
    return f"{value}.OTHER"


def _first_decision_date(known: date, effective: date, calendar: list[date]) -> date | None:
    index = bisect.bisect_left(calendar, known)
    if index >= len(calendar) or calendar[index] >= effective:
        return None
    return calendar[index]


def _load_risk_events(
    spec: dict[str, Any], calendar: list[date]
) -> tuple[list[RiskEvent], dict[str, Any]]:
    distributions = _resolve(spec["inputs"]["qd010_distributions"]["path"])
    rights = _resolve(spec["inputs"]["qd010_rights"]["path"])
    connection = duckdb.connect()
    rows = connection.execute(
        """
        SELECT symbol,event_id,'SHARE_DISTRIBUTION' AS event_kind,
          CAST(known_at AS DATE) AS known_date,CAST(effective_date AS DATE) AS effective_date
        FROM read_parquet(?)
        WHERE effective_date BETWEEN DATE '2018-01-01' AND DATE '2023-12-31'
          AND coalesce(share_multiplier,1)>1 AND source_terms_complete IS TRUE
        UNION ALL
        SELECT symbol,event_id,'RIGHTS_ISSUE' AS event_kind,
          CAST(known_at AS DATE) AS known_date,CAST(effective_date AS DATE) AS effective_date
        FROM read_parquet(?)
        WHERE effective_date BETWEEN DATE '2018-01-01' AND DATE '2023-12-31'
        ORDER BY symbol,effective_date,event_id
        """,
        [str(distributions), str(rights)],
    ).fetchdf()
    connection.close()
    if rows.event_id.isna().any() or rows.duplicated("event_id").any():
        raise CorporateActionReplayError("missing or duplicate QD-010 risk event identity")
    events: list[RiskEvent] = []
    invalid_timing = 0
    for row in rows.itertuples(index=False):
        if pd.isna(row.known_date) or pd.isna(row.effective_date):
            invalid_timing += 1
            continue
        known = pd.Timestamp(row.known_date).date()
        effective = pd.Timestamp(row.effective_date).date()
        decision = _first_decision_date(known, effective, calendar) if known < effective else None
        invalid_timing += int(decision is None)
        events.append(
            RiskEvent(
                symbol=_market_symbol(row.symbol),
                event_id=str(row.event_id),
                event_kind=str(row.event_kind),
                known_date=known,
                decision_date=decision,
                effective_date=effective,
            )
        )
    audit = {
        "risk_events_2018_2023": len(events),
        "share_distribution_events": sum(x.event_kind == "SHARE_DISTRIBUTION" for x in events),
        "rights_events": sum(x.event_kind == "RIGHTS_ISSUE" for x in events),
        "events_without_pre_effective_decision_session": invalid_timing,
        "first_effective_date": min(x.effective_date for x in events).isoformat(),
        "last_effective_date": max(x.effective_date for x in events).isoformat(),
    }
    return events, audit


def _event_maps(
    events: list[RiskEvent],
) -> tuple[dict[tuple[str, date], list[RiskEvent]], dict[str, list[RiskEvent]]]:
    by_decision: dict[tuple[str, date], list[RiskEvent]] = {}
    by_symbol: dict[str, list[RiskEvent]] = {}
    for event in events:
        by_symbol.setdefault(event.symbol, []).append(event)
        if event.decision_date is not None:
            by_decision.setdefault((event.symbol, event.decision_date), []).append(event)
    return by_decision, by_symbol


def _entry_blocked(
    symbol: str,
    signal_date: date,
    entry_date: date,
    events: dict[str, list[RiskEvent]],
) -> bool:
    return any(
        event.decision_date is not None
        and event.decision_date <= signal_date
        and entry_date <= event.effective_date
        for event in events.get(symbol, ())
    )


def _load_market_inputs(spec: dict[str, Any]) -> tuple[list[Path], list[date], dict[str, Any]]:
    prior_spec = PRIOR._load_spec()
    paths, identity = PRIOR._validate_inputs(prior_spec)
    prior_result = json.loads(_resolve(spec["inputs"]["blocked_cycle_result"]["path"]).read_text())
    if prior_result["track_b_promoted"] != list(FAMILIES):
        raise CorporateActionReplayError("frozen promoted family identity changed")
    if sha256_file(PRIOR_PANEL) != prior_result["hashes"]["panel_sha256"]:
        raise CorporateActionReplayError("frozen candidate panel identity changed")
    connection = duckdb.connect()
    calendar = [
        row[0]
        for row in connection.execute(
            "SELECT DISTINCT trade_date FROM read_parquet(?) "
            "WHERE trade_date<=DATE '2023-12-29' ORDER BY trade_date",
            [[str(path) for path in paths]],
        ).fetchall()
    ]
    connection.close()
    return paths, calendar, identity


def _plans(calendar: list[date]) -> pd.DataFrame:
    panel = pd.read_csv(PRIOR_PANEL, parse_dates=["trade_date"])
    panel = panel.loc[panel.family.isin(FAMILIES) & panel.signal_rank.le(10)].copy()
    index = {day: position for position, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for item in panel.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        entry_index = index[signal_date] + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        rows.append(
            {
                "family": item.family,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": 20,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.groupby(["family", "signal_date"]).size().max() != 10:
        raise CorporateActionReplayError("frozen top-10 plan breadth changed")
    return plans


def _sellable(row: Any) -> bool:
    return (
        int(row.trade_status) == 1
        and bool(row.current_day_data_tradable)
        and not bool(row.sell_blocked_open)
    )


def _holding_row_usable(row: Any) -> bool:
    if PRIOR._valid_market_row(row):
        return True
    return (
        int(row.trade_status) == 0
        and not bool(row.current_day_data_tradable)
        and str(row.invalid_reasons).strip() == "invalid_daily_bar"
        and not bool(row.corporate_action_blocking)
        and pd.Timestamp(row.available_at).date() <= pd.Timestamp(row.trade_date).date()
        and math.isfinite(float(row.open))
        and float(row.open) > 0
        and math.isfinite(float(row.close))
        and float(row.close) > 0
    )


def _replay(
    family: str,
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[RiskEvent],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    family_plans = plans.loc[plans.family == family]
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in family_plans.groupby("entry_index", sort=True)
    }
    event_decisions, symbol_events = _event_maps(events)
    initial = 10_000_000.0
    cash = initial
    lots: list[Lot] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    risk_blocked_entries = 0
    completed = 0
    severe = 0
    forced_exits = 0
    forced_pending_days = 0
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    exit_rows: list[dict[str, Any]] = []
    start_index = int(family_plans.entry_index.min())
    final_due = int(family_plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)

    for cal_index in range(start_index, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise CorporateActionReplayError(
                    f"pre-effective exit failed:{family}:{lot.symbol}:"
                    f"{lot.forced_event_id}:{lot.forced_effective_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not _holding_row_usable(row):
                raise CorporateActionReplayError(
                    f"invalid holding row:{family}:{lot.symbol}:{current_date}"
                )
            if int(row.corporate_action_count or 0) > 0:
                action = PRIOR.PRIOR._visible_action(row)
                if action is None:
                    raise CorporateActionReplayError(
                        f"unresolved effective action:{family}:{lot.symbol}:{current_date}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise CorporateActionReplayError(
                        "share risk event reached effective date:"
                        f"{family}:{lot.symbol}:{current_date}"
                    )
                lot.action_cash += lot.shares * cash_per_share

        survivors: list[Lot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            forced = lot.forced_effective_date is not None
            due = cal_index >= lot.due_index
            if not forced and not due:
                survivors.append(lot)
                continue
            if not _sellable(row):
                forced_pending_days += int(forced)
                survivors.append(lot)
                continue
            gross = lot.shares * float(row.open)
            proceeds = lot.action_cash + gross * (1.0 - COST)
            cash += proceeds
            turnover += gross
            completed += 1
            severe += int(proceeds / lot.invested_cost - 1.0 <= -0.10)
            forced_exits += int(forced)
            if forced:
                exit_rows.append(
                    {
                        "family": family,
                        "symbol": lot.symbol,
                        "event_id": lot.forced_event_id,
                        "effective_date": lot.forced_effective_date,
                        "fill_date": current_date,
                        "fill_price": float(row.open),
                        "shares": lot.shares,
                    }
                )
        lots = survivors

        pre_entry_nav = cash + sum(
            lot.action_cash + lot.shares * float(row_map[(lot.symbol, current_date)].open)
            for lot in lots
        )
        planned = entry_map.get(cal_index, [])
        planned_entries += len(planned)
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, current_date))
            if _entry_blocked(plan.symbol, plan.signal_date, current_date, symbol_events):
                risk_blocked_entries += 1
                continue
            if (
                row is not None
                and PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        cohort_capital = min(cash, pre_entry_nav / 4)
        if executable:
            allocation = cohort_capital / len(executable)
            for plan, row in executable:
                shares = allocation / (float(row.open) * (1.0 + COST))
                gross = shares * float(row.open)
                invested = gross * (1.0 + COST)
                cash -= invested
                turnover += gross
                lots.append(
                    Lot(plan.symbol, str(plan.industry), int(plan.due_index), shares, invested)
                )
                entries += 1
                capacity.append(float(row.amount) * 0.05 * len(executable) * 4)

        for lot in lots:
            for event in event_decisions.get((lot.symbol, current_date), ()):
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date
                    lot.forced_event_id = event.event_id

        nav = cash
        industry_values: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            industry_values[lot.industry] = industry_values.get(lot.industry, 0.0) + value
        invested_value = sum(industry_values.values())
        hhi = (
            sum((value / invested_value) ** 2 for value in industry_values.values())
            if invested_value > 0
            else 0.0
        )
        nav_rows.append(
            {
                "trade_date": current_date,
                "family": family,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "industry_hhi": hhi,
            }
        )
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break

    equity = pd.DataFrame(nav_rows)
    if lots:
        raise CorporateActionReplayError(f"terminal open lots:{family}:{len(lots)}")
    returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / initial - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252.0
    annualized = (equity.nav.iloc[-1] / initial) ** (1.0 / years) - 1.0
    volatility = returns.std(ddof=1)
    sharpe = math.sqrt(252.0) * returns.mean() / volatility if volatility > 0 else 0.0
    maximum_drawdown = float(drawdown.min())
    result = {
        "family": family,
        "status": "COMPLETE",
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / initial - 1.0),
        "excess_return_vs_cash": float(equity.nav.iloc[-1] / initial - 1.0),
        "annualized_return": float(annualized),
        "maximum_drawdown": maximum_drawdown,
        "daily_sharpe": float(sharpe),
        "calmar": float(annualized / abs(maximum_drawdown)) if maximum_drawdown < 0 else None,
        "turnover_multiple_initial_capital": float(turnover / initial),
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "risk_blocked_entries": risk_blocked_entries,
        "completed_trades": completed,
        "severe_trade_fraction": float(severe / completed),
        "forced_pre_effective_exits": forced_exits,
        "forced_exit_pending_days": forced_pending_days,
        "terminal_open_lots": len(lots),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions > 0, "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacity)),
    }
    return result, equity, pd.DataFrame(exit_rows)


def _classify(spec: dict[str, Any], replay: dict[str, Any]) -> str:
    if replay["status"] != "COMPLETE" or replay["terminal_open_lots"] != 0:
        return "REPLAY_BLOCKED"
    candidate = spec["classification"]["STRATEGY_CANDIDATE_all_required"]
    if (
        replay["entry_execution_fraction"] >= candidate["minimum_entry_execution_fraction"]
        and replay["total_return"] > candidate["minimum_total_return"]
        and replay["daily_sharpe"] >= candidate["minimum_daily_sharpe"]
        and replay["maximum_drawdown"] >= candidate["minimum_maximum_drawdown"]
        and replay["severe_trade_fraction"] <= candidate["maximum_severe_trade_fraction"]
    ):
        return "STRATEGY_CANDIDATE"
    mixed = spec["classification"]["PROMISING_BUT_MIXED_all_required"]
    if (
        replay["total_return"] > mixed["minimum_total_return"]
        and replay["daily_sharpe"] > mixed["minimum_daily_sharpe"]
        and replay["maximum_drawdown"] >= mixed["minimum_maximum_drawdown"]
    ):
        return "PROMISING_BUT_MIXED"
    if (
        replay["total_return"] > 0
        or replay["daily_sharpe"] > 0
        or replay["maximum_drawdown"] >= -0.50
    ):
        return "PARKED"
    return "REJECTED"


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Minimum corporate-action execution repair and frozen replays",
        "",
        "## Execution contract",
        "",
        (
            "QD-010 `known_at` is the conservative next calendar day after announcement. "
            "A known share distribution or rights event blocks new risk and triggers an "
            "existing-position close decision; the first legal later open must occur strictly "
            "before `effective_date`. Cash-only actions retain exact ledger treatment."
        ),
        "",
        (
            f"The bounded input contains {result['action_audit']['risk_events_2018_2023']:,} "
            "risk events; "
            f"{result['action_audit']['events_without_pre_effective_decision_session']} lack "
            "a pre-effective decision session and remain fail-closed."
        ),
        "",
        "## Frozen portfolio results",
        "",
        (
            "| Family | Classification | Total | Annualized | Max DD | Sharpe | Calmar | "
            "Severe | Turnover | Trades | Forced exits | Entry coverage |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for replay in result["replays"]:
        lines.append(
            f"| {replay['family']} | {replay['classification']} | "
            f"{replay['total_return']:.2%} | {replay['annualized_return']:.2%} | "
            f"{replay['maximum_drawdown']:.2%} | {replay['daily_sharpe']:.3f} | "
            f"{replay['calmar']:.3f} | {replay['severe_trade_fraction']:.2%} | "
            f"{replay['turnover_multiple_initial_capital']:.2f}x | "
            f"{replay['completed_trades']} | {replay['forced_pre_effective_exits']} | "
            f"{replay['entry_execution_fraction']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Comparison",
            "",
            f"Daily return correlation is {result['comparison']['daily_return_correlation']:.3f}. "
            f"Industry diffusion mean breadth is "
            f"{result['replays'][0]['mean_positions']:.1f} positions / "
            f"{result['replays'][0]['mean_industries']:.1f} industries; low idiosyncratic "
            f"volatility is {result['replays'][1]['mean_positions']:.1f} / "
            f"{result['replays'][1]['mean_industries']:.1f}.",
            "",
            "## Research portfolio",
            "",
            "1. Open independent stock-level intraday mechanisms for the highest new "
            "information gain per unit cost.",
            "2. Preserve Industry Diffusion as mixed return/left-tail evidence requiring "
            "genuinely independent confirmation, not a risk-threshold rescue.",
            "3. Preserve Low Idiosyncratic Volatility as a mixed defensive lead requiring "
            "independent confirmation.",
            "4. Preserve the existing CHINEXT RS veto; keep dispersion resource-parked and "
            "Industry Rotation closed.",
            "5. Close this execution repair: it is sufficient for these replays and should "
            "not expand into a general corporate-action platform.",
            "",
            "All 2018--2023 data are consumed development history. Post-2023 and CY-011 "
            "remain unread; no OOS, validation, live, or strict PIT-A claim is made.",
            "",
            f"- Spec: `{result['hashes']['spec_sha256']}`",
            f"- Equity: `{result['hashes']['equity_sha256']}`",
            f"- Risk exits: `{result['hashes']['risk_exits_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    paths, calendar, input_identity = _load_market_inputs(spec)
    events, action_audit = _load_risk_events(spec, calendar)
    plans = _plans(calendar)
    market_rows = PRIOR._query_execution_rows(paths, plans, calendar)
    replays: list[dict[str, Any]] = []
    equity_frames: list[pd.DataFrame] = []
    exit_frames: list[pd.DataFrame] = []
    for family in FAMILIES:
        replay, equity, exits = _replay(family, plans, market_rows, calendar, events)
        replay["classification"] = _classify(spec, replay)
        replays.append(replay)
        equity_frames.append(equity)
        exit_frames.append(exits)
    equity_output = pd.concat(equity_frames, ignore_index=True).sort_values(
        ["family", "trade_date"]
    )
    exit_output = pd.concat(exit_frames, ignore_index=True).sort_values(
        ["family", "fill_date", "symbol"]
    )
    _atomic_write(
        EQUITY_PATH,
        equity_output.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        EXIT_PATH,
        exit_output.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    returns = [
        frame.set_index("trade_date").nav.pct_change().rename(family)
        for frame, family in zip(equity_frames, FAMILIES, strict=True)
    ]
    correlation = float(pd.concat(returns, axis=1).dropna().corr().iloc[0, 1])
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_EXPLORE_ONLY",
        "claim_boundary": spec["claim_boundary"],
        "execution_contract": spec["execution_contract"],
        "input_identity": input_identity,
        "action_audit": action_audit,
        "domain": {
            "families": list(FAMILIES),
            "plans": len(plans),
            "market_rows": len(market_rows),
        },
        "replays": replays,
        "comparison": {"daily_return_correlation": correlation},
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "alpha_changed": False,
            "combined_portfolio": False,
            "oos_claim": False,
            "validation_claim": False,
            "live_claim": False,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
            "risk_exits_sha256": sha256_file(EXIT_PATH),
        },
    }
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
