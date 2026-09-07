"""Exact title rules used by the frozen IFCGR V29R2 producer."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd


CLASSIFICATION_VERSION = "EXCHANGE_ISSUER_RISK_TITLE_RULES_V2"
OPEN, CLOSE, IGNORE = "OPEN", "CLOSE", "IGNORE"
RISK_WARNING = "RISK_WARNING_OR_DELISTING"
INVESTIGATION = "REGULATORY_INVESTIGATION"
ILLEGAL_GUARANTEE = "ILLEGAL_GUARANTEE"
FUND_MISAPPROPRIATION = "CONTROLLER_FUND_MISAPPROPRIATION"
BANK_FREEZE = "ISSUER_BANK_ACCOUNT_FREEZE"
RISK_FAMILIES = (RISK_WARNING, INVESTIGATION, ILLEGAL_GUARANTEE, FUND_MISAPPROPRIATION, BANK_FREEZE)


@dataclass(frozen=True)
class Match:
    action: str
    risk_family: str
    matched_rule: str


def normalize_title(value: object) -> str:
    decoded = html.unescape(re.sub(r"<[^>]+>", "", str(value)))
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", decoded)).strip()


def _has(pattern: str, title: str) -> bool:
    return re.search(pattern, title) is not None


def _risk_warning(title: str) -> Match | None:
    if not _has(r"风险警示|终止上市风险", title): return None
    if _has(r"继续实施(?:退市|其他)?风险警示|撤销.*风险警示.*实施.*风险警示", title): return Match(OPEN, RISK_WARNING, "RISK_WARNING_REMAINS_AFTER_PARTIAL_CHANGE")
    close = _has(r"撤销(?:股票交易)?(?:退市|其他)?风险警示|(?:退市|其他)?风险警示(?:被|予以)?撤销", title)
    ineffective = _has(r"申请撤销|撤销申请|拟(?:申请)?撤销|能否撤销|尚未撤销|未获.*撤销|不予撤销", title)
    if close and not ineffective: return Match(CLOSE, RISK_WARNING, "RISK_WARNING_EXPLICITLY_REMOVED")
    if _has(r"不触及.*风险警示|不存在.*风险警示|无需.*风险警示|不会被实施.*风险警示", title): return None
    return Match(OPEN, RISK_WARNING, "RISK_WARNING_OR_DELISTING_RISK_DISCLOSED")


def _investigation(title: str) -> Match | None:
    if _has(r"撤销立案|终止调查|调查终止|立案调查.*结案|结案.*立案调查", title): return Match(CLOSE, INVESTIGATION, "ISSUER_INVESTIGATION_EXPLICITLY_CLOSED_V2")
    if _has(r"公安机关|检察院|人民法院|(?:控股股东|实际控制人|实控人|董事|总经理|高管|个人).*(?:收到.*调查通知书|立案调查|立案告知)", title): return None
    ongoing = _has(r"立案调查(?:事项)?(?:进展|暨风险提示)|立案调查.*风险提示", title)
    notice = _has(r"(?:收到|公司被|对公司).*(?:中国证监会|中国证券监督管理委员会|证券监督管理局|证监局).*(?:立案|调查通知书)|(?:中国证监会|中国证券监督管理委员会|证券监督管理局|证监局).*(?:对公司)?(?:立案|调查通知书)", title)
    return Match(OPEN, INVESTIGATION, "ISSUER_SECURITIES_INVESTIGATION_OPEN_OR_ONGOING_V2") if ongoing or notice else None


def _illegal_guarantee(title: str) -> Match | None:
    if not _has(r"违规担保|担保事项未履行.*审议程序|未履行.*审议程序.*担保", title): return None
    if _has(r"不存在.*违规担保|未发生.*违规担保|不涉及.*违规担保", title): return None
    partial = _has(r"部分.*(?:解除|清偿)|尚未|未全部|解决方案|整改方案", title)
    if _has(r"已(?:经)?解除|全部解除|清偿完毕|风险已(?:经)?消除", title) and not partial: return Match(CLOSE, ILLEGAL_GUARANTEE, "ILLEGAL_GUARANTEE_EXPLICITLY_RESOLVED_V2")
    attachment = _has(r"(?:问询函|监管函).*(?:回复|答复|核查意见)|(?:回复|答复).*(?:问询函|监管函)|独立董事.*(?:说明|意见)|专项核查意见|评估机构.*意见", title)
    if attachment and not _has(r"收到.*(?:问询函|监管函)|重大风险提示", title): return None
    return Match(OPEN, ILLEGAL_GUARANTEE, "EXPLICIT_ILLEGAL_GUARANTEE_EVENT_V2")


def _fund(title: str) -> Match | None:
    actor = _has(r"控股股东|实际控制人|实控人|关联方|大股东", title)
    occupation = _has(r"非经营性资金占用|资金占用|占用资金|占用公司资金|占用上市公司资金", title)
    illegal = _has(r"(?:公司|上市公司)?资金被?非法划转|非法划转(?:公司|上市公司)?资金", title)
    noun = _has(r"资金占用(?:事项|问题)|占用资金(?:事项|问题)", title)
    if not ((actor and occupation) or illegal or noun): return None
    if _has(r"不存在.*资金占用|未发生.*资金占用|不涉及.*资金占用|未占用.*(?:公司|上市公司)?资金", title) and not illegal: return None
    partial = _has(r"部分归还|部分清偿|尚未|未全部|解决方案|整改方案", title)
    if _has(r"占用款?(?:项|资金)?已?(?:全部|全额)归还|(?:全部|全额)归还(?:占用款|占用资金)|已全部清偿|清偿完毕|相关风险已(?:经)?消除", title) and not partial: return Match(CLOSE, FUND_MISAPPROPRIATION, "MISAPPROPRIATED_FUNDS_EXPLICITLY_FULLY_RETURNED_V2")
    wrongdoing = _has(r"(?:违规|非法|涉嫌)(?:资金占用|占用资金|占用公司资金|占用上市公司资金)|(?:资金占用|占用资金|占用公司资金|占用上市公司资金)(?:系|属于|构成)(?:违规|非法)", title)
    strong = illegal or wrongdoing or _has(r"整改|归还|清偿|偿还|解决|风险提示|被(?:查明|认定)|查实|责令|监管措施|问询|处罚|立案", title)
    explicit = noun or _has(r"(?:资金占用|占用资金|占用公司资金|占用上市公司资金)(?:事项|问题)|(?:存在|发生|形成|新增).*(?:资金占用|占用资金|占用公司资金|占用上市公司资金)|(?:控股股东|实际控制人|实控人|关联方|大股东)(?:存在|发生|形成|新增|涉嫌|被查明|被认定).*(?:资金占用|占用资金|占用公司资金|占用上市公司资金)", title)
    ambiguous = _has(r"专项(?:审计|审核|核查|检查)?(?:说明|报告|意见)|独立董事.*(?:说明|意见)|汇总表|关联资金往来|(?:年度|半年度).*资金占用|资金占用.*对外担保(?:情况|事项)", title)
    if (ambiguous and not strong) or not (illegal or explicit or strong): return None
    return Match(OPEN, FUND_MISAPPROPRIATION, "EXPLICIT_CONTROLLER_FUND_MISAPPROPRIATION_OR_ILLEGAL_TRANSFER_V2")


def _bank_freeze(title: str) -> Match | None:
    if not _has(r"银行(?:账户|账号)|募集资金(?:专户|账户)", title): return None
    partial = _has(r"部分解冻|部分解除冻结|尚未|未全部", title)
    if _has(r"已?(?:全部|全数)解冻|已?全部解除冻结", title) and not partial: return Match(CLOSE, BANK_FREEZE, "BANK_ACCOUNTS_EXPLICITLY_ALL_UNFROZEN")
    return Match(OPEN, BANK_FREEZE, "ISSUER_BANK_ACCOUNT_FROZEN_OR_ONGOING") if _has(r"被冻结|司法冻结|冻结事项|冻结情况|账户冻结", title) else None


def classify(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        title = normalize_title(row.title)
        matches = [match for fn in (_risk_warning, _investigation, _illegal_guarantee, _fund, _bank_freeze) if (match := fn(title))]
        if not matches:
            rows.append({**row.to_dict(), "title": title, "action": IGNORE, "risk_family": pd.NA, "matched_rule": "NO_HIGH_PRECISION_RISK_RULE_V2", "classification_version": CLASSIFICATION_VERSION})
        else:
            for match in matches: rows.append({**row.to_dict(), "title": title, "action": match.action, "risk_family": match.risk_family, "matched_rule": match.matched_rule, "classification_version": CLASSIFICATION_VERSION})
    return pd.DataFrame(rows).sort_values(["available_at", "symbol", "exchange", "announcement_id", "risk_family"], kind="mergesort", na_position="last").reset_index(drop=True)
