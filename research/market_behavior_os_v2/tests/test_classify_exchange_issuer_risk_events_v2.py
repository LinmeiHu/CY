from __future__ import annotations

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v2 as subject,
)


def _metadata(titles: list[str], *, symbol: str = "300290.SZ") -> pd.DataFrame:
    exchange = "SSE" if symbol.endswith(".SH") else "SZSE"
    timestamps = [f"2021-01-{index + 1:02d} 18:30:00" for index in range(len(titles))]
    return pd.DataFrame(
        {
            "symbol": [symbol] * len(titles),
            "exchange": [exchange] * len(titles),
            "announcement_id": [f"ann-{index}" for index in range(len(titles))],
            "title": titles,
            "published_at": timestamps,
            "available_at": timestamps,
            "precision": ["SOURCE_SECOND"] * len(titles),
        }
    )


@pytest.mark.parametrize(
    "title",
    [
        "控股股东及其他关联方占用资金情况专项报告",
        "关于控股股东及其他关联方占用资金情况的专项说明",
        "关于对控股股东及其他关联方占用资金情况的专项审计说明",
        "独立董事关于关联方占用资金情况的专项说明和独立意见",
        "独立董事关于关联方占用资金及对外担保情况的独立意见",
        "关于公司关联方占用上市公司资金情况的专项审核报告",
        "关于控股股东及其他关联方占用资金情况",
        "非经营性资金占用及其他关联资金往来情况汇总表",
    ],
)
def test_ambiguous_governance_review_title_is_not_an_adverse_event(title: str) -> None:
    result = subject.classify_exchange_announcements(_metadata([title]))

    assert result.loc[0, "action"] == subject.ACTION_IGNORE
    assert pd.isna(result.loc[0, "risk_family"])
    assert result.loc[0, "classification_version"] == subject.CLASSIFICATION_VERSION


@pytest.mark.parametrize(
    ("title", "expected_action"),
    [
        ("关于实际控制人非经营性资金占用及整改进展的公告", subject.ACTION_OPEN),
        ("关于控股股东存在占用上市公司资金事项的公告", subject.ACTION_OPEN),
        ("关于公司资金被非法划转的风险提示公告", subject.ACTION_OPEN),
        ("关于关联方占用资金已全部归还的公告", subject.ACTION_CLOSE),
    ],
)
def test_explicit_adverse_or_resolution_predicate_is_retained(
    title: str, expected_action: str
) -> None:
    result = subject.classify_exchange_announcements(_metadata([title]))

    assert result.loc[0, "action"] == expected_action
    assert result.loc[0, "risk_family"] == subject.FAMILY_FUND_MISAPPROPRIATION


def test_strong_adverse_predicate_overrides_attachment_wording() -> None:
    result = subject.classify_exchange_announcements(
        _metadata(["关于控股股东非经营性资金占用整改进展的专项说明"])
    )

    assert result.loc[0, "action"] == subject.ACTION_OPEN
    assert result.loc[0, "risk_family"] == subject.FAMILY_FUND_MISAPPROPRIATION


def test_other_v1_families_and_multi_family_semantics_are_preserved() -> None:
    result = subject.classify_exchange_announcements(
        _metadata(["关于公司资金被非法划转及银行账户资金被司法冻结的公告"])
    )

    assert set(result["action"]) == {subject.ACTION_OPEN}
    assert set(result["risk_family"]) == {
        subject.FAMILY_FUND_MISAPPROPRIATION,
        subject.FAMILY_BANK_FREEZE,
    }


@pytest.mark.parametrize(
    "title",
    [
        "关于控股股东及实际控制人收到中国证券监督管理委员会调查通知书的公告",
        "关于收到公安机关立案告知单的公告",
        "关于董事、总经理立案调查期间不得减持公司股份的公告",
        "关于交易所问询函回复中涉及涉嫌违规担保事项的核查意见",
        "关于大股东占用资金及违规担保事项的独立董事意见",
    ],
)
def test_person_cases_and_repeated_attachment_language_are_ignored(title: str) -> None:
    result = subject.classify_exchange_announcements(_metadata([title]))

    assert result.loc[0, "action"] == subject.ACTION_IGNORE


@pytest.mark.parametrize(
    ("title", "family"),
    [
        (
            "关于收到中国证券监督管理委员会调查通知书的公告",
            subject.FAMILY_INVESTIGATION,
        ),
        ("关于立案调查事项进展暨风险提示的公告", subject.FAMILY_INVESTIGATION),
        (
            "关于收到交易所对涉嫌违规担保事项问询函的公告",
            subject.FAMILY_ILLEGAL_GUARANTEE,
        ),
        ("关于涉嫌违规担保事项暨重大风险提示的公告", subject.FAMILY_ILLEGAL_GUARANTEE),
        ("关于资金占用事项的进展公告", subject.FAMILY_FUND_MISAPPROPRIATION),
    ],
)
def test_issuer_level_fact_titles_are_recognized(title: str, family: str) -> None:
    result = subject.classify_exchange_announcements(_metadata([title]))

    assert result.loc[0, "action"] == subject.ACTION_OPEN
    assert result.loc[0, "risk_family"] == family


def test_v1_point_in_time_rejections_are_not_weakened() -> None:
    metadata = _metadata(["关于控股股东存在占用上市公司资金事项的公告"])
    metadata.loc[0, "available_at"] = "2021-01-01"

    with pytest.raises(subject.RiskEventInputError, match="exact intraday time"):
        subject.classify_exchange_announcements(metadata)
