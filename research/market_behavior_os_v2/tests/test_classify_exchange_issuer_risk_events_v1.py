from __future__ import annotations

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v1 as subject,
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
    ("title", "expected_action", "expected_family"),
    [
        (
            "关于公司股票可能被实施其他风险警示的提示性公告",
            subject.ACTION_OPEN,
            subject.FAMILY_RISK_WARNING,
        ),
        (
            "关于申请撤销其他风险警示的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_RISK_WARNING,
        ),
        (
            "关于公司股票撤销其他风险警示暨停牌的公告",
            subject.ACTION_CLOSE,
            subject.FAMILY_RISK_WARNING,
        ),
        (
            "关于撤销退市风险警示并继续实施其他风险警示的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_RISK_WARNING,
        ),
        (
            "关于收到中国证券监督管理委员会立案告知书的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_INVESTIGATION,
        ),
        (
            "关于收到终止调查决定书的公告",
            subject.ACTION_CLOSE,
            subject.FAMILY_INVESTIGATION,
        ),
        (
            "关于控股股东违规担保事项的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_ILLEGAL_GUARANTEE,
        ),
        (
            "关于控股股东违规担保解决方案的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_ILLEGAL_GUARANTEE,
        ),
        (
            "关于违规担保已解除暨相关风险已消除的公告",
            subject.ACTION_CLOSE,
            subject.FAMILY_ILLEGAL_GUARANTEE,
        ),
        (
            "关于实际控制人非经营性资金占用及整改进展的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_FUND_MISAPPROPRIATION,
        ),
        (
            "关于关联方占用资金已全部归还的公告",
            subject.ACTION_CLOSE,
            subject.FAMILY_FUND_MISAPPROPRIATION,
        ),
        (
            "关于公司部分银行账户被司法冻结的公告",
            subject.ACTION_OPEN,
            subject.FAMILY_BANK_FREEZE,
        ),
        (
            "关于公司银行账户已全部解冻的公告",
            subject.ACTION_CLOSE,
            subject.FAMILY_BANK_FREEZE,
        ),
    ],
)
def test_high_precision_positive_rules(
    title: str, expected_action: str, expected_family: str
) -> None:
    result = subject.classify_exchange_announcements(_metadata([title]))

    assert result.loc[0, "action"] == expected_action
    assert result.loc[0, "risk_family"] == expected_family
    assert result.loc[0, "matched_rule"] != "NO_HIGH_PRECISION_RISK_RULE"


@pytest.mark.parametrize(
    "title",
    [
        "关于为全资子公司提供担保的公告",
        "关于控股股东股份质押及冻结的公告",
        "控股股东及其他关联方占用资金情况专项审计报告",
        "非经营性资金占用及其他关联资金往来情况汇总表",
        "关于公司部分银行账户解冻的进展公告",
        "关于不存在控股股东资金占用情形的自查公告",
        "关于收到行政处罚决定书的公告",
    ],
)
def test_low_information_or_routine_titles_are_ignored(title: str) -> None:
    result = subject.classify_exchange_announcements(_metadata([title]))

    assert result.loc[0, "action"] == subject.ACTION_IGNORE
    assert pd.isna(result.loc[0, "risk_family"])


def test_one_announcement_can_open_two_independent_risk_families() -> None:
    result = subject.classify_exchange_announcements(
        _metadata(["关于公司资金被非法划转及银行账户资金被司法冻结的公告"])
    )

    assert set(result["action"]) == {subject.ACTION_OPEN}
    assert set(result["risk_family"]) == {
        subject.FAMILY_FUND_MISAPPROPRIATION,
        subject.FAMILY_BANK_FREEZE,
    }


def test_state_machine_replays_same_family_and_never_reads_future_notice() -> None:
    metadata = _metadata(
        [
            "关于公司股票被实施其他风险警示的公告",
            "关于申请撤销其他风险警示的公告",
            "关于公司股票撤销其他风险警示的公告",
            "关于公司股票再次被实施其他风险警示的公告",
        ]
    )
    classified = subject.classify_exchange_announcements(metadata)
    decisions = pd.DataFrame(
        {
            "symbol": ["300290.SZ"] * 5,
            "decision_at": [
                "2021-01-01 18:29:59",
                "2021-01-01 18:30:00",
                "2021-01-02 19:00:00",
                "2021-01-03 18:30:00",
                "2021-01-03 23:59:59",
            ],
        }
    )
    coverage = pd.DataFrame(
        {
            "symbol": ["300290.SZ"],
            "coverage_start_at": ["2021-01-01 00:00:00"],
            "coverage_end_at": ["2021-01-31 23:59:59"],
            "baseline_clear": [True],
        }
    )

    states = subject.build_active_risk_state(classified, decisions, coverage=coverage)

    assert states["risk_state"].tolist() == ["CLEAR", "ACTIVE", "ACTIVE", "CLEAR", "CLEAR"]
    assert states["blocks_signal"].tolist() == [False, True, True, False, False]
    assert states.loc[1, "last_consumed_available_at"] == pd.Timestamp(
        "2021-01-01 18:30:00", tz="Asia/Shanghai"
    )
    assert (
        states.loc[states["last_consumed_available_at"].notna(), "last_consumed_available_at"]
        <= states.loc[states["last_consumed_available_at"].notna(), "decision_at"]
    ).all()
    # The fourth, future OPEN is present in the input but unavailable to every decision above.
    assert "ann-3" not in set(states["last_consumed_announcement_ids"])


def test_silence_without_explicit_complete_coverage_is_unknown_and_blocks() -> None:
    classified = subject.classify_exchange_announcements(
        _metadata(
            [
                "关于召开年度股东大会的公告",
                "关于公司银行账户被冻结的公告",
            ]
        )
    )
    decisions = pd.DataFrame(
        {
            "symbol": ["300290.SZ", "300290.SZ"],
            "decision_at": ["2021-01-01 20:00:00", "2021-01-02 20:00:00"],
        }
    )

    states = subject.build_active_risk_state(classified, decisions)

    assert states["risk_state"].tolist() == ["UNKNOWN", "ACTIVE"]
    assert states["blocks_signal"].tolist() == [True, True]
    assert states["active_risk"].isna().tolist() == [True, False]


def test_date_only_collector_notice_is_consumed_only_at_conservative_available_at() -> None:
    metadata = pd.DataFrame(
        {
            "symbol": ["300290.SZ"],
            "exchange": ["SZSE"],
            "announcement_id": ["SZSE-real-shape-1"],
            "title": ["关于公司股票可能被实施其他风险警示的提示性公告"],
            # This mirrors the collector: source publishTime carried only a date.
            "published_at": [pd.Timestamp("2021-06-01 00:00:00")],
            "available_at": [pd.Timestamp("2021-06-02 00:00:00")],
            "precision": ["SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"],
            "source_publication_value": ["2021-06-01"],
        }
    )
    classified = subject.classify_exchange_announcements(metadata)
    decisions = pd.DataFrame(
        {
            "symbol": ["300290.SZ", "300290.SZ"],
            "decision_at": ["2021-06-01 15:00:00", "2021-06-02 00:00:00"],
        }
    )
    coverage = pd.DataFrame(
        {
            "symbol": ["300290.SZ"],
            "coverage_start_at": ["2021-01-01 00:00:00"],
            "coverage_end_at": ["2021-12-31 23:59:59"],
            "baseline_clear": [True],
        }
    )

    states = subject.build_active_risk_state(classified, decisions, coverage=coverage)

    assert classified.loc[0, "precision"] == "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
    assert states["risk_state"].tolist() == ["CLEAR", "ACTIVE"]
    assert pd.isna(states.loc[0, "last_consumed_available_at"])
    assert states.loc[1, "last_consumed_available_at"] == pd.Timestamp(
        "2021-06-02 00:00:00", tz="Asia/Shanghai"
    )


def test_missing_columns_duplicate_identity_and_unknown_time_fail_closed() -> None:
    valid = _metadata(["关于公司股票可能被实施其他风险警示的公告"])

    with pytest.raises(subject.RiskEventInputError, match="missing required columns"):
        subject.classify_exchange_announcements(valid.drop(columns="available_at"))

    with pytest.raises(subject.RiskEventInputError, match="duplicate announcement identities"):
        subject.classify_exchange_announcements(pd.concat([valid, valid], ignore_index=True))

    date_only = valid.copy()
    date_only["available_at"] = "2021-01-01"
    with pytest.raises(subject.RiskEventInputError, match="intraday time"):
        subject.classify_exchange_announcements(date_only)

    bare_published_date = valid.copy()
    bare_published_date["published_at"] = "2021-01-01"
    bare_published_date["available_at"] = "2021-01-02 00:00:00"
    bare_published_date["precision"] = "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
    with pytest.raises(subject.RiskEventInputError, match="intraday time"):
        subject.classify_exchange_announcements(bare_published_date)


def test_publication_lineage_constraints_fail_closed() -> None:
    valid = _metadata(["关于公司银行账户被冻结的公告"])

    earlier = valid.copy()
    earlier["available_at"] = "2021-01-01 18:29:59"
    earlier["precision"] = "SOURCE_SECOND"
    with pytest.raises(subject.RiskEventInputError, match="earlier than published_at"):
        subject.classify_exchange_announcements(earlier)

    delayed_second = valid.copy()
    delayed_second["available_at"] = "2021-01-01 18:30:01"
    with pytest.raises(subject.RiskEventInputError, match="SOURCE_SECOND"):
        subject.classify_exchange_announcements(delayed_second)

    premature_date_only = valid.copy()
    premature_date_only["published_at"] = pd.Timestamp("2021-01-01 00:00:00")
    premature_date_only["available_at"] = pd.Timestamp("2021-01-01 23:59:59")
    premature_date_only["precision"] = "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
    with pytest.raises(subject.RiskEventInputError, match=r"published_at \+ 1 day"):
        subject.classify_exchange_announcements(premature_date_only)

    unknown_precision = valid.copy()
    unknown_precision["precision"] = "UNKNOWN"
    with pytest.raises(subject.RiskEventInputError, match="unsupported precision"):
        subject.classify_exchange_announcements(unknown_precision)


def test_decision_and_coverage_anomalies_fail_closed() -> None:
    classified = subject.classify_exchange_announcements(
        _metadata(["关于公司银行账户被冻结的公告"])
    )

    date_only_decision = pd.DataFrame(
        {"symbol": ["300290.SZ"], "decision_at": ["2021-01-02"]}
    )
    with pytest.raises(subject.RiskEventInputError, match="intraday time"):
        subject.build_active_risk_state(classified, date_only_decision)

    duplicate_decision = pd.DataFrame(
        {
            "symbol": ["300290.SZ", "300290.SZ"],
            "decision_at": ["2021-01-02 15:00:00", "2021-01-02 15:00:00"],
        }
    )
    with pytest.raises(subject.RiskEventInputError, match="duplicate"):
        subject.build_active_risk_state(classified, duplicate_decision)

    decisions = duplicate_decision.iloc[:1].copy()
    bad_coverage = pd.DataFrame(
        {
            "symbol": ["300290.SZ"],
            "coverage_start_at": ["2021-02-01 00:00:00"],
            "coverage_end_at": ["2021-01-01 00:00:00"],
            "baseline_clear": [True],
        }
    )
    with pytest.raises(subject.RiskEventInputError, match="after"):
        subject.build_active_risk_state(classified, decisions, coverage=bad_coverage)


def test_conflicting_same_timestamp_transitions_fail_closed() -> None:
    classified = subject.classify_exchange_announcements(
        _metadata(
            [
                "关于公司银行账户被冻结的公告",
                "关于公司银行账户已全部解冻的公告",
            ]
        )
    )
    classified.loc[:, "available_at"] = pd.Timestamp(
        "2021-01-02 18:30:00", tz="Asia/Shanghai"
    )
    classified.loc[:, "published_at"] = pd.Timestamp(
        "2021-01-02 18:30:00", tz="Asia/Shanghai"
    )
    decisions = pd.DataFrame(
        {"symbol": ["300290.SZ"], "decision_at": ["2021-01-03 15:00:00"]}
    )

    with pytest.raises(subject.RiskEventInputError, match="conflicting"):
        subject.build_active_risk_state(classified, decisions)
