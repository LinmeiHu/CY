#!/usr/bin/env python3
"""Deterministic, point-in-time issuer-risk classification for exchange notices.

The module deliberately uses only the announcement title and its causal
``available_at`` timestamp.  The source's displayed ``published_at`` may be
date-only and is never used as a knowledge time.  It does not infer a resolution
from silence, an application to remove a warning, a remediation plan, or a
partial resolution.

``classify_exchange_announcements`` returns one row per announcement/family
match (and one ``IGNORE`` row when nothing matches).  A single announcement may
therefore open more than one family, for example illegal fund transfers and a
frozen bank account.

``build_active_risk_state`` replays those transitions at each decision time.
An absent event history is not evidence of a clear issuer: a ``CLEAR`` result
requires explicit, complete coverage with a clear baseline.  Otherwise the
result is ``ACTIVE`` when a known open event exists and ``UNKNOWN`` when it does
not; both states block a trading signal.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd

CLASSIFICATION_VERSION: Final = "EXCHANGE_ISSUER_RISK_TITLE_RULES_V1"
SHANGHAI: Final = ZoneInfo("Asia/Shanghai")

ACTION_OPEN: Final = "OPEN"
ACTION_CLOSE: Final = "CLOSE"
ACTION_IGNORE: Final = "IGNORE"

FAMILY_RISK_WARNING: Final = "RISK_WARNING_OR_DELISTING"
FAMILY_INVESTIGATION: Final = "REGULATORY_INVESTIGATION"
FAMILY_ILLEGAL_GUARANTEE: Final = "ILLEGAL_GUARANTEE"
FAMILY_FUND_MISAPPROPRIATION: Final = "CONTROLLER_FUND_MISAPPROPRIATION"
FAMILY_BANK_FREEZE: Final = "ISSUER_BANK_ACCOUNT_FREEZE"

RISK_FAMILIES: Final = (
    FAMILY_RISK_WARNING,
    FAMILY_INVESTIGATION,
    FAMILY_ILLEGAL_GUARANTEE,
    FAMILY_FUND_MISAPPROPRIATION,
    FAMILY_BANK_FREEZE,
)

REQUIRED_METADATA_COLUMNS: Final = (
    "symbol",
    "exchange",
    "announcement_id",
    "title",
    "available_at",
)
REQUIRED_CLASSIFICATION_COLUMNS: Final = (
    "symbol",
    "exchange",
    "announcement_id",
    "available_at",
    "action",
    "risk_family",
    "matched_rule",
)
REQUIRED_DECISION_COLUMNS: Final = ("symbol", "decision_at")
REQUIRED_COVERAGE_COLUMNS: Final = (
    "symbol",
    "coverage_start_at",
    "coverage_end_at",
    "baseline_clear",
)

_TAG_RE = re.compile(r"<[^>]+>")
_DATE_ONLY_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$")
_HAS_CLOCK_RE = re.compile(r"(?:T|\s)\d{1,2}:\d{2}")
_SYMBOL_RE = re.compile(r"^(\d{6})(?:\.(SH|SZ))?$")
_SUPPORTED_PRECISIONS = {
    "SOURCE_SECOND",
    "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY",
}


class RiskEventInputError(ValueError):
    """Raised when an input cannot support a deterministic PIT result."""


@dataclass(frozen=True)
class RuleMatch:
    action: str
    risk_family: str
    matched_rule: str


def normalize_title(value: object) -> str:
    """Return a stable compact title used by the high-precision rules."""

    decoded = html.unescape(_TAG_RE.sub("", str(value)))
    normalized = unicodedata.normalize("NFKC", decoded)
    return re.sub(r"\s+", "", normalized).strip()


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise RiskEventInputError(f"{label} missing required columns: {missing}")


def _exact_local_timestamp(value: object, label: str) -> pd.Timestamp:
    """Parse a timestamp and reject inputs whose intraday time is unknown."""

    if value is None or value is pd.NaT or (
        not isinstance(value, (str, datetime, pd.Timestamp)) and pd.isna(value)
    ):
        raise RiskEventInputError(f"{label} is missing")
    if isinstance(value, date) and not isinstance(value, datetime):
        raise RiskEventInputError(f"{label} is date-only; publication time is unknown")
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or _DATE_ONLY_RE.fullmatch(stripped) or not _HAS_CLOCK_RE.search(stripped):
            raise RiskEventInputError(f"{label} lacks an exact intraday time: {value!r}")
        value = stripped
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RiskEventInputError(f"{label} is not a valid timestamp: {value!r}") from exc
    if pd.isna(timestamp):
        raise RiskEventInputError(f"{label} is missing")
    try:
        if timestamp.tzinfo is None:
            return timestamp.tz_localize(SHANGHAI)
        return timestamp.tz_convert(SHANGHAI)
    except (TypeError, ValueError) as exc:
        raise RiskEventInputError(f"{label} cannot be normalized to Asia/Shanghai") from exc


def _normalize_temporal_columns(work: pd.DataFrame, label: str) -> pd.DataFrame:
    """Normalize causal timestamps and validate optional source-time lineage."""

    result = work.copy()
    result["available_at"] = [
        _exact_local_timestamp(value, f"{label} available_at at row {index!r}")
        for index, value in result["available_at"].items()
    ]
    has_published = "published_at" in result.columns
    has_precision = "precision" in result.columns
    if has_precision and not has_published:
        raise RiskEventInputError(f"{label} has precision without published_at")
    if not has_published:
        return result

    result["published_at"] = [
        _exact_local_timestamp(value, f"{label} published_at at row {index!r}")
        for index, value in result["published_at"].items()
    ]
    if (result["available_at"] < result["published_at"]).any():
        raise RiskEventInputError(f"{label} has available_at earlier than published_at")
    if not has_precision:
        return result

    precisions = result["precision"].map(lambda value: str(value).strip())
    if not precisions.isin(_SUPPORTED_PRECISIONS).all():
        bad = sorted(set(precisions).difference(_SUPPORTED_PRECISIONS))
        raise RiskEventInputError(f"{label} has missing or unsupported precision: {bad}")
    result["precision"] = precisions

    second = result["precision"].eq("SOURCE_SECOND")
    if not result.loc[second, "available_at"].equals(result.loc[second, "published_at"]):
        raise RiskEventInputError(
            f"{label} SOURCE_SECOND rows require available_at == published_at"
        )

    date_only = result["precision"].eq("SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY")
    date_only_published = result.loc[date_only, "published_at"]
    if not date_only_published.equals(date_only_published.dt.normalize()):
        raise RiskEventInputError(
            f"{label} date-only rows require published_at at source-date midnight"
        )
    minimum_available = date_only_published + pd.Timedelta(days=1)
    if (result.loc[date_only, "available_at"] < minimum_available).any():
        raise RiskEventInputError(
            f"{label} date-only rows require available_at >= published_at + 1 day"
        )
    return result


def _normalize_exchange(value: object) -> str:
    exchange = str(value).strip().upper()
    if exchange not in {"SSE", "SZSE"}:
        raise RiskEventInputError(f"unsupported or missing exchange: {value!r}")
    return exchange


def _normalize_symbol(value: object, exchange: str | None = None) -> str:
    raw = str(value).strip().upper()
    match = _SYMBOL_RE.fullmatch(raw)
    if match is None:
        raise RiskEventInputError(f"invalid A-share symbol: {value!r}")
    code, suffix = match.groups()
    inferred = "SH" if code.startswith("6") else "SZ" if code.startswith(("0", "3")) else None
    if inferred is None:
        raise RiskEventInputError(f"unsupported exchange prefix for symbol: {value!r}")
    expected = "SH" if exchange == "SSE" else "SZ" if exchange == "SZSE" else inferred
    if suffix is not None and suffix != expected:
        raise RiskEventInputError(f"symbol/exchange mismatch: {value!r} vs {exchange!r}")
    if inferred != expected:
        raise RiskEventInputError(f"symbol prefix/exchange mismatch: {value!r} vs {exchange!r}")
    return f"{code}.{expected}"


def _contains(pattern: str, title: str) -> bool:
    return re.search(pattern, title) is not None


def _risk_warning_match(title: str) -> RuleMatch | None:
    family = FAMILY_RISK_WARNING
    warning = _contains(r"风险警示|终止上市风险", title)
    if not warning:
        return None

    # Removing one warning while retaining/adding another leaves the issuer risky.
    if _contains(r"继续实施(?:退市|其他)?风险警示|撤销.*风险警示.*实施.*风险警示", title):
        return RuleMatch(ACTION_OPEN, family, "RISK_WARNING_REMAINS_AFTER_PARTIAL_CHANGE")

    close_candidate = _contains(
        r"撤销(?:股票交易)?(?:退市|其他)?风险警示|(?:退市|其他)?风险警示(?:被|予以)?撤销",
        title,
    )
    not_an_effective_close = _contains(
        r"申请撤销|撤销申请|拟(?:申请)?撤销|能否撤销|尚未撤销|未获.*撤销|不予撤销",
        title,
    )
    if close_candidate and not not_an_effective_close:
        return RuleMatch(ACTION_CLOSE, family, "RISK_WARNING_EXPLICITLY_REMOVED")

    if _contains(r"不触及.*风险警示|不存在.*风险警示|无需.*风险警示|不会被实施.*风险警示", title):
        return None
    return RuleMatch(ACTION_OPEN, family, "RISK_WARNING_OR_DELISTING_RISK_DISCLOSED")


def _investigation_match(title: str) -> RuleMatch | None:
    family = FAMILY_INVESTIGATION
    if _contains(r"撤销立案|终止调查|调查终止|立案调查.*结案|结案.*立案调查", title):
        return RuleMatch(ACTION_CLOSE, family, "INVESTIGATION_EXPLICITLY_CLOSED")
    if _contains(r"立案调查|立案告知书|证监会.*立案|收到.*立案", title):
        if _contains(r"不予立案|未被立案", title):
            return None
        return RuleMatch(ACTION_OPEN, family, "REGULATORY_INVESTIGATION_OPENED_OR_ONGOING")
    return None


def _illegal_guarantee_match(title: str) -> RuleMatch | None:
    family = FAMILY_ILLEGAL_GUARANTEE
    has_family = _contains(r"违规担保|担保事项未履行.*审议程序|未履行.*审议程序.*担保", title)
    if not has_family:
        return None
    if _contains(r"不存在.*违规担保|未发生.*违规担保|不涉及.*违规担保", title):
        return None

    partial_or_unresolved = _contains(r"部分.*(?:解除|清偿)|尚未|未全部|解决方案|整改方案", title)
    explicit_close = _contains(r"已(?:经)?解除|全部解除|清偿完毕|风险已(?:经)?消除", title)
    if explicit_close and not partial_or_unresolved:
        return RuleMatch(ACTION_CLOSE, family, "ILLEGAL_GUARANTEE_EXPLICITLY_RESOLVED")
    return RuleMatch(ACTION_OPEN, family, "ILLEGAL_GUARANTEE_DISCLOSED_OR_ONGOING")


def _routine_fund_report(title: str) -> bool:
    return _contains(
        r"(?:资金占用|占用资金).*(?:专项审计报告|专项审核报告|汇总表)"
        r"|(?:专项审计报告|专项审核报告).*(?:资金占用|占用资金)"
        r"|非经营性资金占用及其他关联资金往来.*(?:专项说明|汇总表)",
        title,
    )


def _fund_misappropriation_match(title: str) -> RuleMatch | None:
    family = FAMILY_FUND_MISAPPROPRIATION
    if _routine_fund_report(title):
        return None

    actor = _contains(r"控股股东|实际控制人|实控人|关联方", title)
    occupation = _contains(
        r"非经营性资金占用|资金占用|占用资金|占用公司资金|占用上市公司资金",
        title,
    )
    illegal_transfer = _contains(
        r"(?:公司|上市公司)?资金被?非法划转|非法划转(?:公司|上市公司)?资金",
        title,
    )
    if not ((actor and occupation) or illegal_transfer):
        return None
    negative_occupation = _contains(
        r"不存在.*资金占用|未发生.*资金占用|不涉及.*资金占用", title
    )
    if negative_occupation and not illegal_transfer:
        return None

    partial_or_unresolved = _contains(r"部分归还|部分清偿|尚未|未全部|解决方案|整改方案", title)
    explicit_close = _contains(
        r"占用款?(?:项|资金)?已?(?:全部|全额)归还|"
        r"(?:全部|全额)归还(?:占用款|占用资金)|"
        r"已全部清偿|清偿完毕|相关风险已(?:经)?消除",
        title,
    )
    if explicit_close and not partial_or_unresolved:
        return RuleMatch(ACTION_CLOSE, family, "MISAPPROPRIATED_FUNDS_EXPLICITLY_FULLY_RETURNED")
    return RuleMatch(ACTION_OPEN, family, "CONTROLLER_FUNDS_OCCUPIED_OR_ILLEGALLY_TRANSFERRED")


def _bank_freeze_match(title: str) -> RuleMatch | None:
    family = FAMILY_BANK_FREEZE
    bank_account = _contains(r"银行(?:账户|账号)|募集资金(?:专户|账户)", title)
    if not bank_account:
        return None

    complete_unfreeze = _contains(r"已?(?:全部|全数)解冻|已?全部解除冻结", title)
    partial_or_unresolved = _contains(r"部分解冻|部分解除冻结|尚未|未全部", title)
    if complete_unfreeze and not partial_or_unresolved:
        return RuleMatch(ACTION_CLOSE, family, "BANK_ACCOUNTS_EXPLICITLY_ALL_UNFROZEN")
    if _contains(r"被冻结|司法冻结|冻结事项|冻结情况|账户冻结", title):
        return RuleMatch(ACTION_OPEN, family, "ISSUER_BANK_ACCOUNT_FROZEN_OR_ONGOING")
    return None


def classify_title(title: object) -> tuple[RuleMatch, ...]:
    """Classify one title; multiple independent family matches are retained."""

    compact = normalize_title(title)
    if not compact:
        raise RiskEventInputError("announcement title is empty")
    matches = tuple(
        match
        for matcher in (
            _risk_warning_match,
            _investigation_match,
            _illegal_guarantee_match,
            _fund_misappropriation_match,
            _bank_freeze_match,
        )
        if (match := matcher(compact)) is not None
    )
    return matches


def classify_exchange_announcements(metadata: pd.DataFrame) -> pd.DataFrame:
    """Validate and classify official exchange announcement metadata.

    Announcement identity is ``(symbol, exchange, announcement_id)``.  Any
    duplicate input identity is rejected, including byte-for-byte duplicates,
    because silently choosing a copy could conceal a revised capture.
    """

    _require_columns(metadata, REQUIRED_METADATA_COLUMNS, "metadata")
    work = metadata.copy()
    if work.empty:
        raise RiskEventInputError("metadata is empty; announcement coverage is unknown")

    normalized_exchanges: list[str] = []
    normalized_symbols: list[str] = []
    normalized_ids: list[str] = []
    normalized_titles: list[str] = []
    for row_index, row in work.iterrows():
        exchange = _normalize_exchange(row["exchange"])
        symbol = _normalize_symbol(row["symbol"], exchange)
        announcement_id = str(row["announcement_id"]).strip()
        if not announcement_id or announcement_id.lower() in {"nan", "none", "<na>"}:
            raise RiskEventInputError(f"announcement_id is missing at row {row_index!r}")
        title = normalize_title(row["title"])
        if not title or title.lower() in {"nan", "none", "<na>"}:
            raise RiskEventInputError(f"title is missing at row {row_index!r}")
        normalized_exchanges.append(exchange)
        normalized_symbols.append(symbol)
        normalized_ids.append(announcement_id)
        normalized_titles.append(title)

    work["exchange"] = normalized_exchanges
    work["symbol"] = normalized_symbols
    work["announcement_id"] = normalized_ids
    work["title"] = normalized_titles
    work = _normalize_temporal_columns(work, "metadata")

    identity_columns = ["symbol", "exchange", "announcement_id"]
    duplicate_mask = work.duplicated(identity_columns, keep=False)
    if duplicate_mask.any():
        identities = work.loc[duplicate_mask, identity_columns].drop_duplicates().to_dict("records")
        raise RiskEventInputError(f"duplicate announcement identities: {identities[:5]}")

    output_rows: list[dict[str, object]] = []
    for _, row in work.iterrows():
        base = row.to_dict()
        matches = classify_title(row["title"])
        if not matches:
            output_rows.append(
                {
                    **base,
                    "action": ACTION_IGNORE,
                    "risk_family": pd.NA,
                    "matched_rule": "NO_HIGH_PRECISION_RISK_RULE",
                    "classification_version": CLASSIFICATION_VERSION,
                }
            )
            continue
        for match in matches:
            output_rows.append(
                {
                    **base,
                    "action": match.action,
                    "risk_family": match.risk_family,
                    "matched_rule": match.matched_rule,
                    "classification_version": CLASSIFICATION_VERSION,
                }
            )
    result = pd.DataFrame(output_rows)
    return result.sort_values(
        ["available_at", "symbol", "exchange", "announcement_id", "risk_family"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def _validate_classifications(classifications: pd.DataFrame) -> pd.DataFrame:
    _require_columns(classifications, REQUIRED_CLASSIFICATION_COLUMNS, "classifications")
    work = classifications.copy()
    if work.empty:
        raise RiskEventInputError("classifications are empty; risk state is unknown")
    work["exchange"] = work["exchange"].map(_normalize_exchange)
    work["symbol"] = [
        _normalize_symbol(symbol, exchange)
        for symbol, exchange in zip(work["symbol"], work["exchange"], strict=True)
    ]
    work["announcement_id"] = work["announcement_id"].map(lambda value: str(value).strip())
    if work["announcement_id"].str.lower().isin({"", "nan", "none", "<na>"}).any():
        raise RiskEventInputError("classifications contain a missing announcement_id")
    work = _normalize_temporal_columns(work, "classifications")

    valid_actions = {ACTION_OPEN, ACTION_CLOSE, ACTION_IGNORE}
    if not work["action"].isin(valid_actions).all():
        raise RiskEventInputError("classifications contain an unsupported action")
    recognized = work["action"].isin({ACTION_OPEN, ACTION_CLOSE})
    if work.loc[recognized, "risk_family"].isna().any() or not work.loc[
        recognized, "risk_family"
    ].isin(RISK_FAMILIES).all():
        raise RiskEventInputError("recognized events contain a missing or unsupported risk_family")
    if work.loc[~recognized, "risk_family"].notna().any():
        raise RiskEventInputError("IGNORE rows must not carry a risk_family")
    missing_rule = work["matched_rule"].isna() | work["matched_rule"].astype(str).str.strip().eq("")
    if missing_rule.any():
        raise RiskEventInputError("classifications contain a missing matched_rule")

    recognized_work = work.loc[recognized].copy()
    duplicate_key = ["symbol", "exchange", "announcement_id", "risk_family"]
    if recognized_work.duplicated(duplicate_key, keep=False).any():
        raise RiskEventInputError("duplicate classified announcement/family identity")
    conflict_key = ["symbol", "risk_family", "available_at"]
    conflicts = recognized_work.groupby(conflict_key, dropna=False)["action"].nunique()
    if (conflicts > 1).any():
        raise RiskEventInputError(
            "conflicting OPEN/CLOSE transitions share the same symbol, family, and timestamp"
        )
    return work


def _validate_decisions(decisions: pd.DataFrame) -> pd.DataFrame:
    _require_columns(decisions, REQUIRED_DECISION_COLUMNS, "decisions")
    work = decisions.copy()
    if work.empty:
        raise RiskEventInputError("decisions are empty")
    work["symbol"] = work["symbol"].map(lambda value: _normalize_symbol(value))
    work["decision_at"] = [
        _exact_local_timestamp(value, f"decision_at at row {index!r}")
        for index, value in work["decision_at"].items()
    ]
    if work.duplicated(["symbol", "decision_at"], keep=False).any():
        raise RiskEventInputError("duplicate (symbol, decision_at) identities")
    return work


def _validate_coverage(coverage: pd.DataFrame | None) -> pd.DataFrame | None:
    if coverage is None:
        return None
    _require_columns(coverage, REQUIRED_COVERAGE_COLUMNS, "coverage")
    work = coverage.copy()
    if work.empty:
        raise RiskEventInputError("coverage is empty")
    work["symbol"] = work["symbol"].map(lambda value: _normalize_symbol(value))
    work["coverage_start_at"] = [
        _exact_local_timestamp(value, f"coverage_start_at at row {index!r}")
        for index, value in work["coverage_start_at"].items()
    ]
    work["coverage_end_at"] = [
        _exact_local_timestamp(value, f"coverage_end_at at row {index!r}")
        for index, value in work["coverage_end_at"].items()
    ]
    if work.duplicated(["symbol"], keep=False).any():
        raise RiskEventInputError("coverage contains duplicate symbols")
    if (work["coverage_start_at"] > work["coverage_end_at"]).any():
        raise RiskEventInputError("coverage_start_at is after coverage_end_at")
    if not work["baseline_clear"].map(lambda value: isinstance(value, bool)).all():
        raise RiskEventInputError("coverage baseline_clear must contain literal booleans")
    return work


def build_active_risk_state(
    classifications: pd.DataFrame,
    decisions: pd.DataFrame,
    *,
    coverage: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Replay announcement transitions without consuming post-decision data.

    ``coverage`` is deliberately explicit.  Its ``baseline_clear`` assertion
    means all five families were known clear at ``coverage_start_at`` and the
    complete announcement stream is available through ``coverage_end_at``.
    Without that assertion, silence produces ``UNKNOWN``, never ``CLEAR``.

    The one-row-per-decision output contains ``risk_state`` (``ACTIVE``,
    ``CLEAR``, or ``UNKNOWN``) and ``blocks_signal``.  A known active family
    blocks even when coverage is otherwise incomplete; unknown also blocks.
    """

    events = _validate_classifications(classifications)
    decision_frame = _validate_decisions(decisions)
    coverage_frame = _validate_coverage(coverage)
    coverage_by_symbol = (
        {} if coverage_frame is None else coverage_frame.set_index("symbol").to_dict("index")
    )
    recognized = events.loc[events["action"].isin({ACTION_OPEN, ACTION_CLOSE})].copy()
    recognized = recognized.sort_values(
        ["symbol", "available_at", "exchange", "announcement_id", "risk_family"],
        kind="mergesort",
    )

    rows: list[dict[str, object]] = []
    for _, decision in decision_frame.iterrows():
        symbol = decision["symbol"]
        decision_at = decision["decision_at"]
        coverage_row = coverage_by_symbol.get(symbol)
        coverage_complete = bool(
            coverage_row is not None
            and coverage_row["baseline_clear"]
            and coverage_row["coverage_start_at"] <= decision_at <= coverage_row["coverage_end_at"]
        )
        family_states = {
            family: ("CLEAR" if coverage_complete else "UNKNOWN") for family in RISK_FAMILIES
        }

        eligible_events = recognized.loc[
            (recognized["symbol"] == symbol) & (recognized["available_at"] <= decision_at)
        ]
        if coverage_complete:
            eligible_events = eligible_events.loc[
                eligible_events["available_at"] >= coverage_row["coverage_start_at"]
            ]

        last_event_at: pd.Timestamp | pd.NaT = pd.NaT
        last_event_ids: list[str] = []
        for _, event in eligible_events.iterrows():
            family_states[event["risk_family"]] = (
                "ACTIVE" if event["action"] == ACTION_OPEN else "CLEAR"
            )
            event_time = event["available_at"]
            if pd.isna(last_event_at) or event_time > last_event_at:
                last_event_at = event_time
                last_event_ids = [str(event["announcement_id"])]
            elif event_time == last_event_at:
                last_event_ids.append(str(event["announcement_id"]))

        active_families = sorted(
            family for family, state in family_states.items() if state == "ACTIVE"
        )
        unknown_families = sorted(
            family for family, state in family_states.items() if state == "UNKNOWN"
        )
        if active_families:
            risk_state = "ACTIVE"
        elif unknown_families:
            risk_state = "UNKNOWN"
        else:
            risk_state = "CLEAR"

        base = decision.to_dict()
        active_risk = (
            True if risk_state == "ACTIVE" else False if risk_state == "CLEAR" else pd.NA
        )
        rows.append(
            {
                **base,
                "risk_state": risk_state,
                "active_risk": active_risk,
                "blocks_signal": risk_state != "CLEAR",
                "active_families": "|".join(active_families),
                "unknown_families": "|".join(unknown_families),
                "coverage_complete": coverage_complete,
                "last_consumed_available_at": last_event_at,
                "last_consumed_announcement_ids": "|".join(sorted(set(last_event_ids))),
                "classification_version": CLASSIFICATION_VERSION,
            }
        )

    result = pd.DataFrame(rows)
    result["active_risk"] = result["active_risk"].astype("boolean")
    if result["last_consumed_available_at"].notna().any():
        consumed = result.loc[
            result["last_consumed_available_at"].notna(),
            ["last_consumed_available_at", "decision_at"],
        ]
        if (consumed["last_consumed_available_at"] > consumed["decision_at"]).any():
            raise AssertionError("PIT invariant violated: consumed a post-decision announcement")
    return result.reset_index(drop=True)


__all__ = [
    "ACTION_CLOSE",
    "ACTION_IGNORE",
    "ACTION_OPEN",
    "CLASSIFICATION_VERSION",
    "FAMILY_BANK_FREEZE",
    "FAMILY_FUND_MISAPPROPRIATION",
    "FAMILY_ILLEGAL_GUARANTEE",
    "FAMILY_INVESTIGATION",
    "FAMILY_RISK_WARNING",
    "RISK_FAMILIES",
    "RiskEventInputError",
    "RuleMatch",
    "build_active_risk_state",
    "classify_exchange_announcements",
    "classify_title",
    "normalize_title",
]
