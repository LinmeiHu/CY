#!/usr/bin/env python3
"""High-precision issuer-risk title taxonomy with fund-review false positives removed.

Version 2 preserves every V1 family except the controller-fund rule.  A title
that merely names the mandatory related-party fund-occupation review is not
evidence that occupation occurred.  The fund family therefore needs an
explicit adverse predicate in the title itself; generic reports, special
explanations, audit attachments and independent-director opinions are ignored.

The module deliberately remains title-only.  It never infers facts from an
announcement body and it retains V1's causal ``available_at`` validation.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v1 as v1,
)

CLASSIFICATION_VERSION = "EXCHANGE_ISSUER_RISK_TITLE_RULES_V2"

ACTION_OPEN = v1.ACTION_OPEN
ACTION_CLOSE = v1.ACTION_CLOSE
ACTION_IGNORE = v1.ACTION_IGNORE

FAMILY_RISK_WARNING = v1.FAMILY_RISK_WARNING
FAMILY_INVESTIGATION = v1.FAMILY_INVESTIGATION
FAMILY_ILLEGAL_GUARANTEE = v1.FAMILY_ILLEGAL_GUARANTEE
FAMILY_FUND_MISAPPROPRIATION = v1.FAMILY_FUND_MISAPPROPRIATION
FAMILY_BANK_FREEZE = v1.FAMILY_BANK_FREEZE
RISK_FAMILIES = v1.RISK_FAMILIES

RiskEventInputError = v1.RiskEventInputError
RuleMatch = v1.RuleMatch
normalize_title = v1.normalize_title
build_active_risk_state = v1.build_active_risk_state
_exact_local_timestamp = v1._exact_local_timestamp


def _contains(pattern: str, title: str) -> bool:
    return v1._contains(pattern, title)


def _ambiguous_fund_review(title: str) -> bool:
    """Return true for governance-review titles that do not assert misconduct."""

    return _contains(
        r"专项(?:审计|审核|核查|检查)?(?:说明|报告|意见)"
        r"|独立董事.*(?:说明|意见)"
        r"|汇总表|关联资金往来"
        r"|(?:年度|半年度).*资金占用"
        r"|资金占用.*对外担保(?:情况|事项)",
        title,
    )


def _investigation_match(title: str) -> RuleMatch | None:
    """Recognize an issuer securities investigation, not a person's criminal case."""

    family = FAMILY_INVESTIGATION
    if _contains(r"撤销立案|终止调查|调查终止|立案调查.*结案|结案.*立案调查", title):
        return RuleMatch(ACTION_CLOSE, family, "ISSUER_INVESTIGATION_EXPLICITLY_CLOSED_V2")
    person_or_nonsecurities_case = _contains(
        r"公安机关|检察院|人民法院|"
        r"(?:控股股东|实际控制人|实控人|董事|总经理|高管|个人)"
        r".*(?:收到.*调查通知书|立案调查|立案告知)",
        title,
    )
    if person_or_nonsecurities_case:
        return None
    ongoing_issuer_case = _contains(
        r"立案调查(?:事项)?(?:进展|暨风险提示)|立案调查.*风险提示",
        title,
    )
    regulator_notice = _contains(
        r"(?:收到|公司被|对公司).*"
        r"(?:中国证监会|中国证券监督管理委员会|证券监督管理局|证监局).*"
        r"(?:立案|调查通知书)|"
        r"(?:中国证监会|中国证券监督管理委员会|证券监督管理局|证监局).*"
        r"(?:对公司)?(?:立案|调查通知书)",
        title,
    )
    if ongoing_issuer_case or regulator_notice:
        return RuleMatch(ACTION_OPEN, family, "ISSUER_SECURITIES_INVESTIGATION_OPEN_OR_ONGOING_V2")
    return None


def _illegal_guarantee_match(title: str) -> RuleMatch | None:
    """Ignore replies and governance attachments that only repeat the allegation."""

    family = FAMILY_ILLEGAL_GUARANTEE
    has_family = _contains(r"违规担保|担保事项未履行.*审议程序|未履行.*审议程序.*担保", title)
    if not has_family:
        return None
    if _contains(r"不存在.*违规担保|未发生.*违规担保|不涉及.*违规担保", title):
        return None
    partial_or_unresolved = _contains(r"部分.*(?:解除|清偿)|尚未|未全部|解决方案|整改方案", title)
    explicit_close = _contains(r"已(?:经)?解除|全部解除|清偿完毕|风险已(?:经)?消除", title)
    if explicit_close and not partial_or_unresolved:
        return RuleMatch(ACTION_CLOSE, family, "ILLEGAL_GUARANTEE_EXPLICITLY_RESOLVED_V2")
    attachment_or_reply = _contains(
        r"(?:问询函|监管函).*(?:回复|答复|核查意见)|"
        r"(?:回复|答复).*(?:问询函|监管函)|"
        r"独立董事.*(?:说明|意见)|专项核查意见|评估机构.*意见",
        title,
    )
    original_notice = _contains(r"收到.*(?:问询函|监管函)|重大风险提示", title)
    if attachment_or_reply and not original_notice:
        return None
    return RuleMatch(ACTION_OPEN, family, "EXPLICIT_ILLEGAL_GUARANTEE_EVENT_V2")


def _fund_misappropriation_match(title: str) -> RuleMatch | None:
    """Require the title itself to make an adverse fund-occupation assertion."""

    family = FAMILY_FUND_MISAPPROPRIATION
    actor = _contains(r"控股股东|实际控制人|实控人|关联方|大股东", title)
    occupation = _contains(
        r"非经营性资金占用|资金占用|占用资金|占用公司资金|占用上市公司资金",
        title,
    )
    illegal_transfer = _contains(
        r"(?:公司|上市公司)?资金被?非法划转|非法划转(?:公司|上市公司)?资金",
        title,
    )
    event_noun = _contains(r"资金占用(?:事项|问题)|占用资金(?:事项|问题)", title)
    if not ((actor and occupation) or illegal_transfer or event_noun):
        return None

    negative = _contains(
        r"不存在.*资金占用|未发生.*资金占用|不涉及.*资金占用"
        r"|未占用.*(?:公司|上市公司)?资金",
        title,
    )
    if negative and not illegal_transfer:
        return None

    partial_or_unresolved = _contains(
        r"部分归还|部分清偿|尚未|未全部|解决方案|整改方案", title
    )
    explicit_close = _contains(
        r"占用款?(?:项|资金)?已?(?:全部|全额)归还|"
        r"(?:全部|全额)归还(?:占用款|占用资金)|"
        r"已全部清偿|清偿完毕|相关风险已(?:经)?消除",
        title,
    )
    if explicit_close and not partial_or_unresolved:
        return RuleMatch(
            ACTION_CLOSE,
            family,
            "MISAPPROPRIATED_FUNDS_EXPLICITLY_FULLY_RETURNED_V2",
        )

    fund_wrongdoing = _contains(
        r"(?:违规|非法|涉嫌)(?:资金占用|占用资金|占用公司资金|占用上市公司资金)"
        r"|(?:资金占用|占用资金|占用公司资金|占用上市公司资金)"
        r"(?:系|属于|构成)(?:违规|非法)",
        title,
    )
    strong_adverse = illegal_transfer or fund_wrongdoing or _contains(
        r"整改|归还|清偿|偿还|解决|风险提示|"
        r"被(?:查明|认定)|查实|责令|监管措施|问询|处罚|立案",
        title,
    )
    explicit_event = event_noun or _contains(
        r"(?:资金占用|占用资金|占用公司资金|占用上市公司资金)(?:事项|问题)"
        r"|(?:存在|发生|形成|新增).*(?:资金占用|占用资金|占用公司资金|占用上市公司资金)"
        r"|(?:控股股东|实际控制人|实控人|关联方|大股东)"
        r"(?:存在|发生|形成|新增|涉嫌|被查明|被认定)"
        r".*(?:资金占用|占用资金|占用公司资金|占用上市公司资金)",
        title,
    )
    if _ambiguous_fund_review(title) and not strong_adverse:
        return None
    if not (illegal_transfer or explicit_event or strong_adverse):
        return None
    return RuleMatch(
        ACTION_OPEN,
        family,
        "EXPLICIT_CONTROLLER_FUND_MISAPPROPRIATION_OR_ILLEGAL_TRANSFER_V2",
    )


def classify_title(title: object) -> tuple[RuleMatch, ...]:
    """Classify one normalized title under the V2 high-precision taxonomy."""

    compact = normalize_title(title)
    if not compact:
        raise RiskEventInputError("announcement title is empty")
    matches = tuple(
        match
        for matcher in (
            v1._risk_warning_match,
            _investigation_match,
            _illegal_guarantee_match,
            _fund_misappropriation_match,
            v1._bank_freeze_match,
        )
        if (match := matcher(compact)) is not None
    )
    return matches


def _require_columns(frame: pd.DataFrame, required: Iterable[str], label: str) -> None:
    v1._require_columns(frame, required, label)


def classify_exchange_announcements(metadata: pd.DataFrame) -> pd.DataFrame:
    """Validate metadata and classify it without weakening V1 PIT semantics."""

    _require_columns(metadata, v1.REQUIRED_METADATA_COLUMNS, "metadata")
    work = metadata.copy()
    if work.empty:
        raise RiskEventInputError("metadata is empty; announcement coverage is unknown")

    normalized_exchanges: list[str] = []
    normalized_symbols: list[str] = []
    normalized_ids: list[str] = []
    normalized_titles: list[str] = []
    for row_index, row in work.iterrows():
        exchange = v1._normalize_exchange(row["exchange"])
        symbol = v1._normalize_symbol(row["symbol"], exchange)
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
    work = v1._normalize_temporal_columns(work, "metadata")

    identity_columns = ["symbol", "exchange", "announcement_id"]
    duplicate_mask = work.duplicated(identity_columns, keep=False)
    if duplicate_mask.any():
        identities = (
            work.loc[duplicate_mask, identity_columns]
            .drop_duplicates()
            .to_dict("records")
        )
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
                    "matched_rule": "NO_HIGH_PRECISION_RISK_RULE_V2",
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
