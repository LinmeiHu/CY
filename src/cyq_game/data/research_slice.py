"""One-symbol daily PIT-B research slice and its five necessary audits."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from math import isfinite
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .asof_join import (
    PITDomain,
    PITDomainRecord,
    PITJoinRequest,
    join_strategy_inputs,
)
from .corporate_actions import UNRESOLVED, adapt_cninfo_corporate_actions
from .pit import CorporateActionRecord
from .quant_adapter import (
    NormalizedQuantRecord,
    QuantAssetKind,
    QuantReadScope,
    adapt_historical_trading_rules,
    iter_quant_records,
    select_float_as_of,
)
from .registry import (
    DataActivationError,
    DataAssetRegistry,
    DataOperation,
    InputSnapshotManifest,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
_BLOCKING_ACTIONS = {UNRESOLVED, "RIGHTS_ISSUE"}
_KNOWN_LIMITS = (0.05, 0.10, 0.20, 0.30)


def prepare_daily_research_slice(
    *,
    registry_path: str | Path,
    input_manifest_path: str | Path,
    symbol: str,
    start: date,
    end: date,
) -> dict[str, object]:
    """Build and audit a bounded daily PIT-B slice without running a strategy."""

    scope = QuantReadScope(start=start, end=end, symbols=(symbol,))
    if scope.calendar_days > 31:
        raise DataActivationError("single-symbol validation is limited to 31 calendar days")

    registry = DataAssetRegistry.load(registry_path)
    manifest = InputSnapshotManifest.load(input_manifest_path, registry=registry)
    manifest.require_range(start, end)
    authorization = manifest.authorize(DataOperation.INGEST, registry=registry)
    canonical_symbol = scope.symbols[0]
    code = canonical_symbol[:6]

    daily_binding = manifest.binding("daily_bars")
    state_binding = manifest.binding("trading_state")
    industry_binding = manifest.binding("industry_membership")
    float_binding = manifest.binding("circulating_shares")
    action_binding = manifest.binding("corporate_actions")

    daily = tuple(
        iter_quant_records(
            binding=daily_binding,
            authorization=authorization,
            kind=QuantAssetKind.DAILY_BARS,
            path=daily_binding.path / f"{code}.none.parquet",
            scope=scope,
        )
    )
    states = adapt_historical_trading_rules(
        binding=state_binding,
        authorization=authorization,
        path=state_binding.path / f"{code}.parquet",
        scope=scope,
    )
    industry = tuple(
        iter_quant_records(
            binding=industry_binding,
            authorization=authorization,
            kind=QuantAssetKind.INDUSTRY_DAILY,
            path=industry_binding.path / "industry_daily.parquet",
            scope=scope,
        )
    )
    float_records = tuple(
        iter_quant_records(
            binding=float_binding,
            authorization=authorization,
            kind=QuantAssetKind.SHARE_FLOAT_PIT,
            path=float_binding.path / "qmt_capital.parquet",
            scope=scope,
        )
    )
    action_batch = adapt_cninfo_corporate_actions(
        binding=action_binding,
        authorization=authorization,
        scope=scope,
        distributions_path=action_binding.path / "normalized/distributions.parquet",
        rights_path=action_binding.path / "normalized/rights_issues.parquet",
        run_id=f"pit-b-slice:{canonical_symbol}:{start}:{end}",
    )

    duplicate_issues: list[str] = []
    daily_by_date = _unique_daily(daily, "daily_bars", duplicate_issues)
    state_by_date = _unique_daily(states, "trading_state", duplicate_issues)
    industry_by_date = _unique_daily(industry, "industry_membership", duplicate_issues)
    duplicate_issues.extend(_float_duplicates(float_records))
    duplicate_issues.extend(_action_duplicates(action_batch.records))

    coverage_issues: list[str] = []
    time_issues: list[str] = []
    unit_issues: list[str] = []
    cross_issues: list[str] = []
    joins: list[dict[str, object]] = []
    expected_dates = sorted(daily_by_date)
    if not expected_dates:
        coverage_issues.append("no unadjusted daily bars in requested scope")

    _check_date_keys("trading_state", expected_dates, state_by_date, cross_issues)
    _check_date_keys("industry_membership", expected_dates, industry_by_date, cross_issues)
    _check_units(daily, states, float_records, action_batch.records, unit_issues)

    for trade_date in expected_dates:
        bar = daily_by_date[trade_date]
        decision_at = bar.available_at
        records = _pit_records_for_day(
            symbol=canonical_symbol,
            trade_date=trade_date,
            decision_at=decision_at,
            bar=bar,
            state=state_by_date.get(trade_date),
            industry=industry_by_date.get(trade_date),
            float_record=select_float_as_of(
                float_records,
                symbol=canonical_symbol,
                decision_at=decision_at,
            ),
            actions=action_batch.records,
        )
        for record in records:
            if record.available_at > decision_at:
                time_issues.append(
                    f"{trade_date} {record.domain.value} available_at follows decision_at"
                )
            if not record.is_effective_at(decision_at):
                time_issues.append(
                    f"{trade_date} {record.domain.value} is not effective at decision_at"
                )
        joined = join_strategy_inputs(
            records,
            PITJoinRequest(
                symbol=canonical_symbol,
                decision_at=decision_at,
                strict_archival=False,
            ),
        )
        if not joined.hard_valid:
            coverage_issues.append(
                f"{trade_date} incomplete PIT join: "
                + ",".join(reason.value for reason in joined.validity.reasons)
            )
        joins.append(
            {
                "trade_date": trade_date.isoformat(),
                "decision_at": decision_at.isoformat(),
                "hard_valid": joined.hard_valid,
                "data_quality": joined.data_quality,
                "domain_flags": {
                    domain.value: flag for domain, flag in joined.domain_flags.items()
                },
                "reasons": [reason.value for reason in joined.validity.reasons],
            }
        )

    checks = {
        "coverage": _check(coverage_issues, len(joins)),
        "duplicates": _check(duplicate_issues, len(daily) + len(states) + len(industry)),
        "time_travel": _check(time_issues, len(joins) * len(PITDomain)),
        "consistency": _check(
            unit_issues,
            len(daily) + len(states) + len(float_records) + len(action_batch.records),
        ),
        "cross_table": _check(cross_issues, len(joins)),
    }
    gate_pass = bool(joins) and all(item["status"] == "PASS" for item in checks.values())
    return {
        "gate": "PIT_B_SINGLE_SYMBOL_MONTH",
        "gate_pass": gate_pass,
        "pit_grade": "B_CAUSAL_RESEARCH",
        "strict_pit_archive_ready": False,
        "scope": {
            "symbol": canonical_symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "daily_only": True,
        },
        "authorization": {
            "operation": authorization.operation.value,
            "manifest_id": authorization.input_manifest_id,
            "purpose": authorization.purpose.value,
        },
        "counts": {
            "daily_bars": len(daily),
            "trading_states": len(states),
            "industry_memberships": len(industry),
            "historical_float_facts": len(float_records),
            "corporate_actions": len(action_batch.records),
            "corporate_action_issues": len(action_batch.issues),
            "joined_days": len(joins),
        },
        "checks": checks,
        "joins": joins,
        "sources": {
            role: {
                "asset_id": binding.asset.asset_id,
                "snapshot_id": binding.snapshot_id,
                "source": binding.source,
            }
            for role, binding in (
                ("daily_bars", daily_binding),
                ("trading_state", state_binding),
                ("industry_membership", industry_binding),
                ("circulating_shares", float_binding),
                ("corporate_actions", action_binding),
            )
        },
        "limitations": [
            "CNINFO is a frozen current historical snapshot without revision-vintage lineage.",
            "Industry membership is used only as a mandatory daily label; no sector model runs.",
            "Minute/Tick data and strategy/backtest execution are outside this gate.",
        ],
    }


def _pit_records_for_day(
    *,
    symbol: str,
    trade_date: date,
    decision_at: datetime,
    bar: NormalizedQuantRecord,
    state: NormalizedQuantRecord | None,
    industry: NormalizedQuantRecord | None,
    float_record: NormalizedQuantRecord | None,
    actions: Iterable[CorporateActionRecord],
) -> tuple[PITDomainRecord, ...]:
    valid_from = datetime.combine(trade_date, time.min, tzinfo=SHANGHAI).astimezone(UTC)
    valid_to = valid_from + timedelta(days=1)
    records = [
        _record(
            PITDomain.SECURITY_IDENTITY,
            symbol,
            trade_date,
            decision_at,
            bar,
            {"security_type": "A_SHARE", "listed": True},
            valid_from,
            valid_to,
        )
    ]
    if industry is not None and industry.hard_valid:
        records.append(
            _record(
                PITDomain.SECTOR_MEMBERSHIP,
                symbol,
                trade_date,
                industry.available_at,
                industry,
                {"sector_id": str(industry.values["industry"])},
                valid_from,
                valid_to,
            )
        )
    if float_record is not None and float_record.hard_valid:
        records.append(
            _record(
                PITDomain.FLOAT_SHARES,
                symbol,
                trade_date,
                float_record.available_at,
                float_record,
                {"float_shares": float(float_record.values["circulating_capital"])},
                valid_from,
                valid_to,
            )
        )

    blocking = [
        action
        for action in actions
        if action.symbol == symbol
        and action.ex_date == trade_date
        and action.available_at <= decision_at
        and action.action_type in _BLOCKING_ACTIONS
    ]
    records.append(
        PITDomainRecord(
            domain=PITDomain.CORPORATE_ACTION_STATUS,
            symbol=symbol,
            record_id=f"corporate_action_status:{symbol}:{trade_date}",
            revision_id=f"modeled-current-snapshot:{trade_date}",
            valid_from=valid_from,
            valid_to=valid_to,
            available_at=decision_at,
            source="CNINFO frozen final-action snapshot; absence modeled at decision close",
            snapshot_id="QD-010-cninfo-actions-20260820",
            values={"coverage_complete": not blocking},
            strict_pit_eligible=False,
            available_at_observed=False,
        )
    )
    if state is not None and state.hard_valid:
        records.extend(
            (
                _record(
                    PITDomain.TRADING_STATUS,
                    symbol,
                    trade_date,
                    state.available_at,
                    state,
                    {
                        "trade_status": str(state.values["trade_status"]),
                        "is_st": bool(state.values["is_st"]),
                    },
                    valid_from,
                    valid_to,
                ),
                _record(
                    PITDomain.MARKET_RULE,
                    symbol,
                    trade_date,
                    state.available_at,
                    state,
                    {
                        "board": _board(symbol),
                        "lot_size": 100,
                        "t_plus_one": True,
                        "limit_pct": float(state.values["limit_pct"]),
                    },
                    valid_from,
                    valid_to,
                ),
            )
        )
    return tuple(records)


def _record(
    domain: PITDomain,
    symbol: str,
    trade_date: date,
    available_at: datetime,
    source_record: NormalizedQuantRecord,
    values: Mapping[str, str | int | float | bool | None],
    valid_from: datetime,
    valid_to: datetime,
) -> PITDomainRecord:
    return PITDomainRecord(
        domain=domain,
        symbol=symbol,
        record_id=f"{domain.value}:{symbol}:{trade_date}",
        revision_id=f"{source_record.snapshot_id}:{trade_date}",
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at,
        source=source_record.source,
        snapshot_id=source_record.snapshot_id,
        values=values,
        strict_pit_eligible=False,
        available_at_observed=False,
        price_coordinate=(
            "UNADJUSTED" if domain is PITDomain.SECURITY_IDENTITY else None
        ),
    )


def _unique_daily(
    records: Iterable[NormalizedQuantRecord],
    label: str,
    issues: list[str],
) -> dict[date, NormalizedQuantRecord]:
    grouped: dict[date, list[NormalizedQuantRecord]] = {}
    for record in records:
        trade_date = record.values["trade_date"]
        if not isinstance(trade_date, date):
            issues.append(f"{label} has non-date trade_date")
            continue
        grouped.setdefault(trade_date, []).append(record)
    result: dict[date, NormalizedQuantRecord] = {}
    for trade_date, rows in grouped.items():
        if len(rows) != 1:
            issues.append(f"{label} duplicate key {trade_date}: {len(rows)} rows")
        else:
            result[trade_date] = rows[0]
    return result


def _float_duplicates(records: Iterable[NormalizedQuantRecord]) -> list[str]:
    keys = Counter(
        (
            record.symbol,
            record.values["effective_date"],
            record.values["announced_date"],
        )
        for record in records
    )
    return [f"float duplicate key {key}: {count} rows" for key, count in keys.items() if count > 1]


def _action_duplicates(records: Iterable[CorporateActionRecord]) -> list[str]:
    keys = Counter(record.action_id for record in records)
    return [
        f"corporate action duplicate id {key}: {count} rows"
        for key, count in keys.items()
        if count > 1
    ]


def _check_date_keys(
    label: str,
    expected_dates: list[date],
    actual: Mapping[date, NormalizedQuantRecord],
    issues: list[str],
) -> None:
    expected = set(expected_dates)
    missing = sorted(expected - set(actual))
    extra = sorted(set(actual) - expected)
    if missing:
        issues.append(f"{label} missing dates: {','.join(map(str, missing))}")
    if extra:
        issues.append(f"{label} extra dates: {','.join(map(str, extra))}")


def _check_units(
    daily: Iterable[NormalizedQuantRecord],
    states: Iterable[NormalizedQuantRecord],
    float_records: Iterable[NormalizedQuantRecord],
    actions: Iterable[CorporateActionRecord],
    issues: list[str],
) -> None:
    for record in daily:
        values = record.values
        prices = [float(values[name]) for name in ("open", "high", "low", "close", "preclose")]
        if not all(isfinite(value) and value > 0 for value in prices):
            issues.append(f"{values['trade_date']} daily price unit anomaly")
        if not record.hard_valid:
            issues.append(f"{values['trade_date']} daily row hard_valid=false")
    for record in states:
        limit_pct = float(record.values["limit_pct"])
        if not any(abs(limit_pct - item) <= 1e-9 for item in _KNOWN_LIMITS):
            issues.append(f"{record.values['trade_date']} unknown limit_pct={limit_pct}")
        if not record.hard_valid:
            issues.append(f"{record.values['trade_date']} trading state hard_valid=false")
    for record in float_records:
        value = float(record.values["circulating_capital"])
        if not isfinite(value) or value <= 0 or value > 10_000_000_000_000:
            issues.append(
                f"{record.values['effective_date']} float-share unit anomaly={value}"
            )
    for action in actions:
        if action.ratio is not None and (not isfinite(action.ratio) or action.ratio <= 0):
            issues.append(f"{action.action_id} action ratio unit anomaly")
        if action.cash_per_share is not None and (
            not isfinite(action.cash_per_share) or action.cash_per_share < 0
        ):
            issues.append(f"{action.action_id} cash-per-share unit anomaly")


def _board(symbol: str) -> str:
    code, exchange = symbol.split(".")
    if exchange == "SH" and code.startswith(("688", "689")):
        return "STAR"
    if exchange == "SZ" and code.startswith(("300", "301")):
        return "CHINEXT"
    if exchange in {"SH", "SZ"}:
        return "MAIN"
    return "BSE"


def _check(issues: list[str], records_checked: int) -> dict[str, Any]:
    return {
        "status": "PASS" if not issues else "FAIL",
        "records_checked": records_checked,
        "issue_count": len(issues),
        "issues": issues[:20],
    }
