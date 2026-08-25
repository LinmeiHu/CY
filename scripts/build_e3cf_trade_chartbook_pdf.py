#!/usr/bin/env python3
"""Build a holdout-safe per-trade candlestick PDF for one entry parameter.

The script intentionally has two modes because the project environment owns
DuckDB/PyArrow while the bundled document runtime owns ReportLab/PyPDF.

Prepare with the project Python, then render with the bundled document Python.
Only development panel years through 2022 are read by ``prepare``.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

PARAMETER_ID = "e3cf6dbc57eeb26f"
BUCKET_LAST = 18
DEVELOPMENT_CUTOFF = date(2022, 12, 30)
CONFIG_SHA256 = "e8b4e5e6938f159a328cf456c20ecb03f4b12aed73d10704fd812fcac6504bda"
PANEL_SNAPSHOT_ID = (
    "panel-b27b6247ec34f674c697259d2e5e07e9615b1733743cc13845dce8f52ce54e00"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "render"), required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--prepared",
        type=Path,
        default=Path("tmp/pdfs/e3cf_trade_chartbook_holdout_safe.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/e3cf_trade_chartbook_holdout_safe.pdf"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    prepared = _absolute(repo, args.prepared)
    output = _absolute(repo, args.output)
    if args.mode == "prepare":
        _prepare(repo, prepared)
    else:
        _render(prepared, output)
    return 0


def _prepare(repo: Path, target: Path) -> None:
    import duckdb  # type: ignore[import-untyped]

    validation = (
        repo
        / "output/markup_retest_main_chinext_2020_2023_v1/validation/development"
        / CONFIG_SHA256[:12]
    )
    replay_root = validation / "entry_economic_exact_replay_v2-e0d4211e0ab8"
    trade_files = tuple(
        replay_root / "parts" / f"bucket={bucket:02d}" / "trades.parquet"
        for bucket in range(BUCKET_LAST + 1)
    )
    signal_files = tuple(path.with_name("signals.parquet") for path in trade_files)
    for path in (*trade_files, *signal_files):
        if not path.is_file():
            raise FileNotFoundError(path)

    con = duckdb.connect()
    # The main research replay may still be using the four performance cores.
    # Keep this reporting query bounded so chart preparation does not contend
    # with or destabilize that run.
    con.execute("PRAGMA threads=2")
    con.execute("PRAGMA memory_limit='2GB'")
    trade_expr = _duckdb_file_list(trade_files)
    signal_expr = _duckdb_file_list(signal_files)
    trades = con.execute(
        f"""
        SELECT * EXCLUDE (bucket)
        FROM read_parquet({trade_expr}, hive_partitioning=true)
        WHERE parameter_id = ? AND is_evaluation_row
        ORDER BY CAST(substr(entry_at, 1, 10) AS DATE), symbol, signal_id
        """,
        [PARAMETER_ID],
    ).fetchdf().to_dict("records")
    if len(trades) != 255:
        raise ValueError(f"expected the annotated 255 trades, found {len(trades)}")
    signals = {
        str(row["signal_id"]): row
        for row in con.execute(
            f"""
            SELECT * EXCLUDE (bucket)
            FROM read_parquet({signal_expr}, hive_partitioning=true)
            WHERE parameter_id = ? AND is_evaluation_row
            """,
            [PARAMETER_ID],
        ).fetchdf().to_dict("records")
    }
    trade_signal_ids = {str(row["signal_id"]) for row in trades}
    if not trade_signal_ids.issubset(signals):
        raise ValueError("a closed trade is missing its source signal")

    chart_requests: list[tuple[int, str, date, date]] = []
    eligible_indices: list[int] = []
    blocked_indices: list[int] = []
    for index, trade in enumerate(trades, start=1):
        entry_date = _iso_date(trade["entry_at"])
        exit_date = _iso_date(trade["exit_at"])
        start = _shift_months(entry_date, -6)
        end = _shift_months(exit_date, 6)
        trade["chart_start"] = start
        trade["chart_end"] = end
        trade["report_index"] = index
        if end <= DEVELOPMENT_CUTOFF:
            eligible_indices.append(index)
            source_signal = signals[str(trade["signal_id"])]
            lifecycle_start = min(
                _iso_date(source_signal["accumulation_started_at"]),
                _iso_date(source_signal["breakout_at"]),
                _iso_date(source_signal["retest_confirmed_at"]),
            )
            chart_requests.append(
                (index, str(trade["symbol"]), min(start, lifecycle_start), end)
            )
        else:
            blocked_indices.append(index)

    panel_root = (
        repo
        / "output/markup_retest_main_chinext_2020_2023_v1/panel/development"
        / CONFIG_SHA256[:12]
        / "data"
    )
    panel_files = tuple(
        sorted(
            path
            for year in range(2018, 2023)
            for path in (panel_root / f"partition_year={year}").rglob("*.parquet")
        )
    )
    if not panel_files:
        raise FileNotFoundError(f"no development panel files under {panel_root}")
    con.execute(
        "CREATE TEMP TABLE chart_requests(report_index INTEGER, symbol VARCHAR, start_date DATE, end_date DATE)"
    )
    con.executemany("INSERT INTO chart_requests VALUES (?, ?, ?, ?)", chart_requests)
    panel_expr = _duckdb_file_list(panel_files)
    chart_rows = con.execute(
        f"""
        SELECT
          r.report_index,
          p.symbol,
          p.trade_date,
          p.open / nullif(p.price_coordinate_factor, 0) AS chart_open,
          p.high / nullif(p.price_coordinate_factor, 0) AS chart_high,
          p.low / nullif(p.price_coordinate_factor, 0) AS chart_low,
          p.close / nullif(p.price_coordinate_factor, 0) AS chart_close,
          p.volume,
          p.price_coordinate_factor,
          p.average_cost,
          p.cost_p10,
          p.cost_p50,
          p.cost_p90,
          p.main_peak,
          p.dominant_band_lower,
          p.dominant_band_upper,
          p.corporate_action_count,
          p.corporate_action_ids,
          p.market_state,
          p.sector_state,
          p.industry,
          p.industry_pit_grade,
          p.research_hard_valid,
          p.strategy_eligible,
          p.tradable_state,
          p.atr,
          p.structure_support,
          p.breakout_excess_atr,
          p.setup_score,
          p.distribution_score,
          p.close_vs_vwap,
          p.turnover_fraction,
          p.ev_turnover_absorption,
          p.ev_near_price_chip_growth,
          p.ev_concentration_improves,
          p.ev_sticky_base,
          p.ev_downside_absorption,
          p.dist_base_loss,
          p.dist_cost_band_expands,
          p.dist_peak_splits,
          p.dist_high_turnover_weak_impact,
          p.dist_relative_reversal,
          p.prior_average_cost,
          p.prior_cost_p50,
          p.prior_main_peak,
          p.model_spread_cost_p50,
          p.model_spread_cost_p90,
          p.model_spread_main_peak,
          p.reason_codes,
          p.daily_snapshot_id,
          p.feature_daily_snapshot_id,
          p.feature_minute_snapshot_id,
          p.corporate_action_snapshot_id
        FROM read_parquet({panel_expr}, hive_partitioning=true) p
        JOIN chart_requests r
          ON p.symbol = r.symbol
         AND p.trade_date BETWEEN r.start_date AND r.end_date
        ORDER BY r.report_index, p.trade_date
        """
    ).fetchdf().to_dict("records")
    grouped_rows: dict[int, list[dict[str, Any]]] = {}
    for row in chart_rows:
        grouped_rows.setdefault(int(row.pop("report_index")), []).append(row)

    prepared_trades: list[dict[str, Any]] = []
    blocked_trades: list[dict[str, Any]] = []
    for trade in trades:
        index = int(trade["report_index"])
        signal = signals[str(trade["signal_id"])]
        base = _make_trade_record(trade, signal, grouped_rows.get(index, []))
        if index in blocked_indices:
            base["holdout_block_reason"] = (
                "卖出后六个月跨入 2023 留出期；为避免观察留出期结果，本报告未读取 2023 行情。"
            )
            blocked_trades.append(base)
        else:
            if not base["chart_rows"]:
                raise ValueError(f"empty chart window for trade {index}")
            prepared_trades.append(base)

    exact_manifest = replay_root / "progress.json"
    p0_manifest = validation / "pit_b_true_oos_calibration_v3.json"
    review_manifest = validation / "entry_selection_protocol_review_v2.json"
    incident_manifest = validation / "holdout_access_incident_20260824.json"
    p0_payload = json.loads(p0_manifest.read_text(encoding="utf-8"))
    incident_payload = json.loads(incident_manifest.read_text(encoding="utf-8"))
    incident_event = incident_payload["payload"]
    payload = {
        "schema_version": 1,
        "title": "e3cf6dbc57eeb26f 逐笔买卖蜡烛图与决策说明",
        "generated_at": datetime.now().astimezone().isoformat(),
        "parameter_id": PARAMETER_ID,
        "parameters": _jsonable(trades[0]["parameters"]),
        "scope": {
            "classification": "WALK_FORWARD_DEVELOPMENT_EVIDENCE / DIAGNOSTIC_ONLY",
            "evaluation_start": "2020-01-02",
            "evaluation_end": "2022-12-30",
            "annotated_bucket_range": [0, BUCKET_LAST],
            "annotated_trade_count": len(trades),
            "complete_chart_count": len(prepared_trades),
            "holdout_blocked_chart_count": len(blocked_trades),
            "research_as_of": "2022-12-30",
        },
        "data_basis": {
            "calculation_price_basis": (
                "因果公司行动重基后的分析价格坐标；OHLC 使用原始未复权事实除以当日可见 price_coordinate_factor。"
            ),
            "display_price_basis": "与策略计算和精确 5 分钟成交价相同的因果分析价格坐标。",
            "causal_corporate_action_rebasing": True,
            "corporate_action_asset": "QD-010",
            "daily_asset": "CY-006",
            "minute_asset": "CY-008",
            "chip_feature_asset": "CY-019",
            "chip_lineage_asset": "CY-020",
            "pit_grade": "B_RESEARCH_ONLY",
            "panel_snapshot_id": PANEL_SNAPSHOT_ID,
            "strategy_config_sha256": CONFIG_SHA256,
        },
        "execution_basis": {
            "signal_time": "收盘后 15:30 形成信号",
            "fill_time": "下一合法交易日 09:35 前的精确 5 分钟窗口",
            "same_bar_fill": False,
            "nominal_capital_per_signal": 500000.0,
            "fee_bps": 5.0,
            "slippage_bps": 10.0,
            "impact_bps": 5.0,
            "t_plus_one": True,
            "blocked_exit_persists": True,
        },
        "p0_calibration": {
            "status": p0_payload["status"],
            "protocol_version": p0_payload["protocol_version"],
            "folds": [
                {
                    "name": fold["name"],
                    "training_end": fold["calibration_training_end"],
                    "evaluation_start": fold["evaluation_start"],
                    "evaluation_end": fold["evaluation_end"],
                    "oos_valid_symbol_count": fold["oos_valid_symbol_count"],
                    "weighted_actual_ece": fold["weighted_actual_ece"],
                    "weighted_model_brier": fold["weighted_model_brier"],
                    "weighted_baseline_brier": fold["weighted_baseline_brier"],
                }
                for fold in p0_payload["folds"]
            ],
            "interpretation": p0_payload["interpretation"],
        },
        "holdout_audit": {
            "physical_2023_access_incident_preexisted": True,
            "incident_status": incident_event["status"],
            "holdout_outcomes_observed": incident_event[
                "holdout_outcomes_observed"
            ],
            "used_for_parameter_selection_or_thresholds": incident_event[
                "used_for_parameter_selection_or_thresholds"
            ],
            "this_report_added_2023_access": False,
        },
        "parameter_plain_language": [
            "起始吸筹评分必须达到 1.0，即五项吸收/稳定证据全部成立。",
            "突破幅度门槛为 0 ATR：只要确认突破成本上沿即可，不额外追求更大幅度。",
            "回踩深度最多 0.5 ATR，要求回踩较浅。",
            "平均成本与中位成本迁移至少 0 ATR，即不能比突破前向下移动。",
            "筹码派发评分达到 0.8 且连续两个交易日确认才触发派发退出。",
            "保护止损线为冻结突破支撑下方 1.5 ATR；最长持有 20 个可交易日。",
        ],
        "summary": _summary(trades),
        "source_inventory": [
            _inventory(review_manifest, repo),
            _inventory(p0_manifest, repo),
            _inventory(exact_manifest, repo),
            _inventory(incident_manifest, repo),
            {
                "path": str(Path("scripts/build_e3cf_trade_chartbook_pdf.py")),
                "sha256": _sha256(Path(__file__)),
            },
        ],
        "trades": prepared_trades,
        "holdout_blocked_trades": blocked_trades,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "PREPARED",
                "annotated_trades": len(trades),
                "complete_charts": len(prepared_trades),
                "holdout_blocked": len(blocked_trades),
                "path": str(target),
            },
            ensure_ascii=False,
        )
    )


def _make_trade_record(
    trade: Mapping[str, Any],
    signal: Mapping[str, Any],
    chart_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for raw in chart_rows:
        row = _jsonable(dict(raw))
        row["trade_date"] = str(row["trade_date"])[:10]
        rows.append(row)
    by_date = {str(row["trade_date"]): row for row in rows}
    accumulation_date = str(signal["accumulation_started_at"])[:10]
    breakout_date = str(signal["breakout_at"])[:10]
    decision_date = str(signal["retest_confirmed_at"])[:10]
    exit_intent_date = str(trade["exit_intent_at"])[:10]
    lifecycle = {
        "accumulation": by_date.get(accumulation_date),
        "breakout": by_date.get(breakout_date),
        "retest": by_date.get(decision_date),
        "exit_intent": by_date.get(exit_intent_date),
    }
    display_rows = [
        row
        for row in rows
        if str(trade["chart_start"])
        <= str(row["trade_date"])
        <= str(trade["chart_end"])
    ]
    coverage_note = ""
    if display_rows:
        requested_start = date.fromisoformat(str(trade["chart_start"]))
        requested_end = date.fromisoformat(str(trade["chart_end"]))
        first_bar = date.fromisoformat(str(display_rows[0]["trade_date"]))
        last_bar = date.fromisoformat(str(display_rows[-1]["trade_date"]))
        gaps: list[str] = []
        if (first_bar - requested_start).days > 10:
            gaps.append(f"图窗开始后至 {first_bar} 没有可见交易 K 线")
        if (requested_end - last_bar).days > 10:
            gaps.append(f"{last_bar} 后至图窗结束没有可见交易 K 线")
        if gaps:
            coverage_note = "；".join(gaps) + "；空白区保留，不伪造价格。"
    entry_reasons = _entry_plain(signal, lifecycle)
    exit_reasons = _exit_plain(trade, lifecycle)
    return {
        "report_index": int(trade["report_index"]),
        "signal_id": str(trade["signal_id"]),
        "symbol": str(trade["symbol"]),
        "signal_at": str(trade["signal_at"]),
        "entry_at": str(trade["entry_at"]),
        "entry_price": _number(trade["entry_price"]),
        "entry_cash": _number(trade["entry_cash"]),
        "entry_quantity": int(trade["entry_quantity"]),
        "exit_intent_at": str(trade["exit_intent_at"]),
        "exit_at": str(trade["exit_at"]),
        "exit_price": _number(trade["exit_price"]),
        "exit_reason": str(trade["exit_reason"]),
        "net_pnl": _number(trade["net_pnl"]),
        "return_fraction": _number(trade["return_fraction"]),
        "blocked_tail_loss": _number(trade["blocked_tail_loss"]),
        "chart_start": str(trade["chart_start"]),
        "chart_end": str(trade["chart_end"]),
        "chart_rows": display_rows,
        "coverage_note": coverage_note,
        "lifecycle": lifecycle,
        "decision_evidence": {
            "market_state": str(signal["market_state"]),
            "sector_state": str(signal["sector_state"]),
            "industry_pit_grade": str(signal["industry_pit_grade"]),
            "pit_grade": str(signal["pit_grade"]),
            "anchor_retention": _number(signal["anchor_retention"]),
            "anchor_retention_lower": _number(signal["anchor_retention_lower"]),
            "anchor_retention_upper": _number(signal["anchor_retention_upper"]),
            "evidence_for": _string_list(signal["evidence_for"]),
            "evidence_against": _string_list(signal["evidence_against"]),
            "alternative_explanations": [
                _plain_alternative(item)
                for item in _string_list(signal["alternative_explanations"])
            ],
            "available_at": str(signal["available_at"]),
            "snapshot_ids": _string_list(signal["snapshot_ids"]),
        },
        "entry_plain": entry_reasons,
        "exit_plain": exit_reasons,
    }


def _entry_plain(
    signal: Mapping[str, Any], lifecycle: Mapping[str, Mapping[str, Any] | None]
) -> list[str]:
    accumulation = lifecycle.get("accumulation") or {}
    breakout = lifecycle.get("breakout") or {}
    retest = lifecycle.get("retest") or {}
    setup = _number(accumulation.get("setup_score"))
    breakout_atr = _number(breakout.get("breakout_excess_atr"))
    retest_depth = _safe_ratio(
        abs(_number(breakout.get("structure_support")) - _number(retest.get("chart_low"))),
        _number(retest.get("atr")),
    )
    migration = _safe_ratio(
        min(
            _number(retest.get("average_cost"))
            - _number(breakout.get("prior_average_cost")),
            _number(retest.get("cost_p50")) - _number(breakout.get("prior_cost_p50")),
        ),
        _number(retest.get("atr")),
    )
    volume_ratio = _safe_ratio(
        _number(retest.get("volume")), _number(breakout.get("volume"))
    )
    turnover_ratio = _safe_ratio(
        _number(retest.get("turnover_fraction")),
        _number(breakout.get("turnover_fraction")),
    )
    evidence = "、".join(
        _plain_evidence(item) for item in _string_list(signal.get("evidence_for"))
    )
    return [
        f"先出现完整吸筹组合：起始评分 {setup:.2f}，门槛 1.00。{evidence}。",
        f"随后确认突破：突破成本上沿 {breakout_atr:.2f} ATR，门槛是不低于 0 ATR。",
        (
            f"回踩仍守住结构：回踩深度 {retest_depth:.2f} ATR（上限 0.50）；"
            f"成本迁移 {migration:.2f} ATR（不得向下）；成交量/突破日 {volume_ratio:.2f}，"
            f"换手/突破日 {turnover_ratio:.2f}（两者上限均 0.80）。"
        ),
        (
            f"冻结底仓保留率下界 {_number(signal.get('anchor_retention_lower')):.1%}（门槛 70%）；"
            f"大盘 {signal.get('market_state')}，板块 {signal.get('sector_state')}。"
        ),
        (
            f"信号在 {str(signal.get('decision_at'))[:16]} 收盘后形成，"
            f"只在下一合法 5 分钟窗口成交，没有使用同一根 K 线内成交。"
        ),
    ]


def _exit_plain(
    trade: Mapping[str, Any], lifecycle: Mapping[str, Mapping[str, Any] | None]
) -> list[str]:
    exit_row = lifecycle.get("exit_intent") or {}
    breakout = lifecycle.get("breakout") or {}
    reason = str(trade["exit_reason"])
    reason_text = {
        "MAX_HOLDING_PERIOD": "持有达到 20 个可交易日，仍未出现更早的止损或派发退出，按时间上限离场。",
        "STRUCTURE_BROKEN": "原来冻结的筹码底座或价格结构已经破坏，入场假设失效，不能继续硬扛。",
        "PROTECTIVE_STOP": (
            "收盘跌破冻结突破支撑下方 1.5 ATR 的保护线，触发保护止损。"
        ),
        "DISTRIBUTION_CONFIRMED": "筹码派发评分连续两个交易日达到 0.80，确认筹码结构转弱。",
        "CORPORATE_ACTION": "公司行动使原价格/筹码坐标需要重基，先退出并停止增加风险。",
        "DATA_INVALID": "关键数据或点时质量门禁失效，系统按 fail-closed 原则退出。",
    }.get(reason, f"系统退出原因码为 {reason}。")
    support = _number(breakout.get("structure_support"))
    close = _number(exit_row.get("chart_close"))
    atr = _number(exit_row.get("atr"))
    stop = support - 1.5 * atr if math.isfinite(support + atr) else math.nan
    distribution_score = _number(exit_row.get("distribution_score"))
    distribution_text = (
        f"{distribution_score:.2f}"
        if math.isfinite(distribution_score)
        else "缺失（数据门禁已 fail-closed）"
    )
    details = (
        f"退出意图日收盘 {close:.3f}，冻结支撑 {support:.3f}，"
        f"当日 ATR {atr:.3f}，保护线约 {stop:.3f}，派发评分 "
        f"{distribution_text}。"
    )
    fill = (
        f"退出意图在 {str(trade['exit_intent_at'])[:16]} 形成，"
        f"实际于下一合法窗口 {str(trade['exit_at'])[:16]} 成交；"
        f"成交后净收益 {_number(trade['return_fraction']):+.2%}，"
        f"净盈亏 {_number(trade['net_pnl']):+,.0f} 元。"
    )
    blocked = _number(trade.get("blocked_tail_loss"))
    blocked_text = (
        f"退出受阻尾部损失记录为 {blocked:,.0f} 元。"
        if blocked > 0
        else "本笔没有记录到退出受阻尾部损失。"
    )
    return [reason_text, details, fill, blocked_text]


def _summary(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    returns = [_number(row["return_fraction"]) for row in trades]
    pnls = [_number(row["net_pnl"]) for row in trades]
    ordered = sorted(returns)
    trim = int(len(ordered) * 0.05)
    trimmed = ordered[trim : len(ordered) - trim]
    positive = sum(value for value in returns if value > 0)
    negative = -sum(value for value in returns if value < 0)
    annual = Counter(str(row["entry_at"])[:4] for row in trades)
    exits = Counter(str(row["exit_reason"]) for row in trades)
    return {
        "trade_count": len(trades),
        "mean_return_fraction": statistics.fmean(returns),
        "trimmed_5pct_mean_return_fraction": statistics.fmean(trimmed),
        "median_return_fraction": statistics.median(returns),
        "win_rate": sum(value > 0 for value in returns) / len(returns),
        "profit_factor": positive / negative if negative else None,
        "total_net_pnl": sum(pnls),
        "best_trade_return_fraction": max(returns),
        "worst_trade_return_fraction": min(returns),
        "annual_trade_counts": dict(sorted(annual.items())),
        "exit_reason_counts": dict(sorted(exits.items())),
        "formal_selection_status": "NOT_EVALUATED / NOT_FROZEN",
        "formal_gate_note": (
            "这些 255 笔只是当时 19/32 分桶的中途观察；必须等 32/32、匹配基线、"
            "周级 bootstrap、回撤/容量和经济连通区全部完成后才能判断 PASS 或 NO_TRADE。"
        ),
    }


def _render(prepared: Path, output: Path) -> None:
    from pypdf import PdfReader
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    del colors  # Colors are imported lazily in drawing helpers.
    payload = json.loads(prepared.read_text(encoding="utf-8"))
    pdfmetrics.registerFont(
        TTFont(
            "STSong-Light",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    page_size = landscape(A4)
    c = canvas.Canvas(str(output), pagesize=page_size, pageCompression=1)
    c.setTitle(payload["title"])
    c.setAuthor("CYQ-GAME research audit")
    c.setSubject("Per-trade causal candlestick charts and plain-language rationale")

    page = 0

    def finish_page() -> None:
        nonlocal page
        page += 1
        _footer(c, page_size, page)
        c.showPage()

    _cover(c, page_size, payload)
    finish_page()
    _summary_page(c, page_size, payload)
    finish_page()
    _method_page(c, page_size, payload)
    finish_page()
    _provenance_page(c, page_size, payload)
    finish_page()
    _index_pages(c, page_size, payload["trades"], finish_page)

    for trade in payload["trades"]:
        _trade_page(c, page_size, trade, payload)
        finish_page()

    _blocked_pages(c, page_size, payload["holdout_blocked_trades"], finish_page)
    c.save()

    reader = PdfReader(str(output))
    expected_pages = page
    if len(reader.pages) != expected_pages:
        raise ValueError(
            f"PDF page count mismatch: expected {expected_pages}, got {len(reader.pages)}"
        )
    if output.stat().st_size < 100_000:
        raise ValueError("PDF is unexpectedly small")
    print(
        json.dumps(
            {
                "status": "RENDERED",
                "pages": len(reader.pages),
                "complete_trade_charts": len(payload["trades"]),
                "holdout_blocked": len(payload["holdout_blocked_trades"]),
                "bytes": output.stat().st_size,
                "path": str(output),
            },
            ensure_ascii=False,
        )
    )


def _cover(c: Any, size: tuple[float, float], payload: Mapping[str, Any]) -> None:
    width, height = size
    c.setFillColorRGB(0.05, 0.10, 0.18)
    c.rect(0, 0, width, height, stroke=0, fill=1)
    c.setFillColorRGB(0.18, 0.72, 0.78)
    c.rect(42, height - 120, 9, 66, stroke=0, fill=1)
    c.setFont("STSong-Light", 25)
    c.setFillColorRGB(0.96, 0.98, 1.0)
    c.drawString(68, height - 78, "逐笔买卖蜡烛图与决策说明")
    c.setFont("Helvetica-Bold", 15)
    c.drawString(68, height - 108, payload["parameter_id"])
    c.setFont("STSong-Light", 12)
    scope = payload["scope"]
    c.drawString(
        68,
        height - 163,
        f"锁定样本：{scope['annotated_trade_count']} 笔（当时完成 bucket 00-18）",
    )
    c.drawString(
        68,
        height - 188,
        f"完整 12 个月图窗：{scope['complete_chart_count']} 笔；2023 留出期锁定：{scope['holdout_blocked_chart_count']} 笔",
    )
    c.drawString(68, height - 213, "研究区间：2020-01-02 至 2022-12-30")
    c.drawString(68, height - 238, "证据等级：B_RESEARCH_ONLY / DIAGNOSTIC_ONLY")
    c.setFillColorRGB(0.75, 0.80, 0.87)
    c.setFont("STSong-Light", 10)
    _draw_wrapped(
        c,
        "本图册把每次买入和卖出放回完整的前后行情中，解释当时为什么允许买、为什么退出，以及哪些替代解释和数据限制仍然存在。它不是交易指令，也不是最终参数冻结证据。",
        68,
        height - 300,
        width - 136,
        15,
        max_lines=5,
    )
    c.setFont("Helvetica", 8)
    c.drawString(68, 52, f"Panel snapshot: {payload['data_basis']['panel_snapshot_id']}")


def _summary_page(c: Any, size: tuple[float, float], payload: Mapping[str, Any]) -> None:
    width, height = size
    _page_title(c, height, "一页看懂：收益、样本与当前结论")
    summary = payload["summary"]
    metrics = [
        ("样本", f"{summary['trade_count']} 笔"),
        ("普通均值", f"{summary['mean_return_fraction']:+.3%}"),
        ("5% 截尾均值", f"{summary['trimmed_5pct_mean_return_fraction']:+.3%}"),
        ("中位数", f"{summary['median_return_fraction']:+.3%}"),
        ("胜率", f"{summary['win_rate']:.1%}"),
        ("Profit Factor", f"{summary['profit_factor']:.3f}"),
        ("累计单笔名义净盈亏", f"{summary['total_net_pnl']:+,.0f} 元"),
        ("最好 / 最差", f"{summary['best_trade_return_fraction']:+.2%} / {summary['worst_trade_return_fraction']:+.2%}"),
    ]
    x0, y0 = 42, height - 100
    cell_w, cell_h = (width - 84) / 4, 58
    for index, (label, value) in enumerate(metrics):
        row, col = divmod(index, 4)
        x, y = x0 + col * cell_w, y0 - row * (cell_h + 12)
        c.setFillColorRGB(0.94, 0.96, 0.98)
        c.roundRect(x, y - cell_h, cell_w - 10, cell_h, 5, stroke=0, fill=1)
        c.setFillColorRGB(0.30, 0.37, 0.45)
        c.setFont("STSong-Light", 9)
        c.drawString(x + 10, y - 18, label)
        c.setFillColorRGB(0.05, 0.12, 0.20)
        c.setFont("STSong-Light", 13)
        c.drawString(x + 10, y - 42, value)
    c.setFont("STSong-Light", 11)
    c.setFillColorRGB(0.05, 0.12, 0.20)
    c.drawString(42, height - 276, "当前可以说什么")
    _draw_wrapped(
        c,
        "这组参数在已完成的 19/32 分桶里呈正收益苗头，且附近多个参数点也为正；但它仍未完成全量经济门禁，不能称为正式好参数。",
        42,
        height - 299,
        width * 0.46,
        15,
        max_lines=5,
    )
    c.drawString(width * 0.53, height - 276, "还缺什么")
    _draw_wrapped(
        c,
        "必须补齐 32/32 分桶、周级 bootstrap 置信下界、匹配 eligible 基线、回撤/尾损/容量，并确认至少三个相邻点共同通过；合法终点也可能是 NO_TRADE。",
        width * 0.53,
        height - 299,
        width * 0.41,
        15,
        max_lines=6,
    )
    c.setFont("STSong-Light", 10)
    c.drawString(42, 142, "按入场年份的交易数")
    c.drawString(260, 142, "退出原因")
    c.setFont("Helvetica", 9)
    c.drawString(42, 121, _pairs(summary["annual_trade_counts"]))
    c.setFont("STSong-Light", 9)
    _draw_wrapped(
        c,
        _exit_pairs(summary["exit_reason_counts"]),
        260,
        121,
        width - 302,
        13,
        max_lines=3,
    )
    c.setFillColorRGB(0.86, 0.24, 0.23)
    c.setFont("STSong-Light", 10)
    _draw_wrapped(c, summary["formal_gate_note"], 42, 77, width - 84, 14, max_lines=3)


def _method_page(c: Any, size: tuple[float, float], payload: Mapping[str, Any]) -> None:
    width, height = size
    _page_title(c, height, "读图方法、成交口径与必要限制")
    sections = [
        (
            "参数大白话",
            payload["parameter_plain_language"],
        ),
        (
            "价格与成交",
            [
                payload["data_basis"]["calculation_price_basis"],
                "红色 K 线表示上涨，绿色表示下跌；蓝色竖线/三角形为买入，橙色为卖出。蓝线为筹码中位成本，紫色虚线为主峰。",
                "信号在收盘后形成，只能在下一合法 5 分钟窗口成交；费用 5 bps、滑点 10 bps、冲击 5 bps。",
                "退出意图和实际卖出是两件事；停牌或跌停无法成交时，风险继续留在账上。",
            ],
        ),
        (
            "研究限制",
            [
                "筹码分布是持仓成本状态估计，不是庄家账户透视；三个卖方模型是替代假说。",
                "当前资产等级为 B_RESEARCH_ONLY，不能冒充严格 PIT-A，也不能直接授权 EdgeCard、Kelly 或实盘。",
                "该参数来自已经反复查看的 2020-2022 开发期；不是未触碰 OOS。",
                "45 笔交易的卖后六个月跨入 2023，本安全版本不读取 2023 行情，以免污染一次性留出期。",
            ],
        ),
    ]
    columns = (42, width / 3 + 14, 2 * width / 3 + 2)
    col_w = width / 3 - 52
    for x, (heading, bullets) in zip(columns, sections, strict=True):
        c.setFillColorRGB(0.10, 0.24, 0.37)
        c.setFont("STSong-Light", 12)
        c.drawString(x, height - 92, heading)
        y = height - 118
        for bullet in bullets:
            c.setFillColorRGB(0.18, 0.23, 0.30)
            c.setFont("STSong-Light", 8.5)
            used = _draw_wrapped(c, "• " + bullet, x, y, col_w, 12, max_lines=6)
            y -= used + 11


def _provenance_page(
    c: Any, size: tuple[float, float], payload: Mapping[str, Any]
) -> None:
    width, height = size
    _page_title(c, height, "数据血缘、真实后续校准与留出期审计")
    basis = payload["data_basis"]
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 11)
    c.drawString(42, height - 91, "点时数据与价格坐标")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("STSong-Light", 8)
    y = height - 113
    items = [
        f"研究 as_of={payload['scope']['research_as_of']}；等级={basis['pit_grade']}。",
        (
            f"日线={basis['daily_asset']}，分钟成交={basis['minute_asset']}，"
            f"筹码特征/血缘={basis['chip_feature_asset']}/{basis['chip_lineage_asset']}，"
            f"公司行动={basis['corporate_action_asset']}。"
        ),
        basis["calculation_price_basis"],
        f"panel_snapshot_id={basis['panel_snapshot_id']}",
        f"strategy_config_sha256={basis['strategy_config_sha256']}",
    ]
    for item in items:
        used = _draw_wrapped(c, "• " + item, 42, y, width * 0.46, 11, max_lines=4)
        y -= used + 7

    p0 = payload["p0_calibration"]
    x2 = width * 0.53
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 11)
    c.drawString(x2, height - 91, "P0 真正后续评价折（按股票 fail-closed）")
    c.setFont("STSong-Light", 8)
    c.setFillColorRGB(0.16, 0.20, 0.26)
    y2 = height - 113
    for fold in p0["folds"]:
        text = (
            f"{fold['name']}：训练至 {fold['training_end']}，评价 {fold['evaluation_start']} 至 "
            f"{fold['evaluation_end']}；OOS 合格股票 {fold['oos_valid_symbol_count']}；"
            f"加权 ECE={fold['weighted_actual_ece']:.4f}，模型/基线 Brier="
            f"{fold['weighted_model_brier']:.4f}/{fold['weighted_baseline_brier']:.4f}。"
        )
        used = _draw_wrapped(c, "• " + text, x2, y2, width * 0.41, 11, max_lines=5)
        y2 -= used + 8
    used = _draw_wrapped(
        c,
        "• PASS 的含义是校准流程有真实后续评分且不合格股票被挡住；它不表示所有股票或整体模型都优于基线，也不授权下单。",
        x2,
        y2,
        width * 0.41,
        11,
        max_lines=5,
    )
    y2 -= used + 8
    audit = payload["holdout_audit"]
    c.setFillColorRGB(0.72, 0.14, 0.12)
    _draw_wrapped(
        c,
        (
            "• 仓库此前已有一次 2023 文件架构/行数物理访问事故，已追加审计；没有看到收益、标签或策略指标，也未用于阈值/选参。"
            f"本图册新增 2023 访问={audit['this_report_added_2023_access']}。"
        ),
        x2,
        y2,
        width * 0.41,
        11,
        max_lines=5,
    )

    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 10.5)
    c.drawString(42, 164, "关键源文件哈希（用于复核本图册引用的版本）")
    c.setFillColorRGB(0.22, 0.27, 0.33)
    c.setFont("Helvetica", 6.5)
    y3 = 145
    for item in payload["source_inventory"]:
        c.drawString(42, y3, f"{item['path']}  sha256={item['sha256']}")
        y3 -= 14


def _index_pages(
    c: Any,
    size: tuple[float, float],
    trades: Sequence[Mapping[str, Any]],
    finish_page: Any,
) -> None:
    _, height = size
    per_page = 34
    for start in range(0, len(trades), per_page):
        _page_title(c, height, f"逐笔索引（完整图窗） {start + 1}-{min(start + per_page, len(trades))}")
        c.setFont("STSong-Light", 8)
        c.setFillColorRGB(0.30, 0.36, 0.43)
        c.drawString(42, height - 78, "序号   股票        买入日期      卖出日期      净收益       退出原因")
        y = height - 96
        for trade in trades[start : start + per_page]:
            text = (
                f"{trade['report_index']:03d}    {trade['symbol']:<11}  "
                f"{trade['entry_at'][:10]}   {trade['exit_at'][:10]}   "
                f"{trade['return_fraction']:+7.2%}    {_plain_exit(trade['exit_reason'])}"
            )
            c.setFillColorRGB(0.05, 0.11, 0.18)
            c.drawString(42, y, text)
            y -= 13
        finish_page()


def _trade_page(
    c: Any,
    size: tuple[float, float],
    trade: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    width, height = size
    outcome_color = (0.78, 0.10, 0.12) if trade["return_fraction"] >= 0 else (0.05, 0.48, 0.30)
    c.setFillColorRGB(0.05, 0.11, 0.18)
    c.setFont("STSong-Light", 14)
    c.drawString(
        35,
        height - 31,
        f"{trade['report_index']:03d}/255  {trade['symbol']}  买 {trade['entry_at'][:10]} → 卖 {trade['exit_at'][:10]}",
    )
    c.setFillColorRGB(*outcome_color)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(width - 35, height - 31, f"NET {trade['return_fraction']:+.2%}")
    _draw_candles(c, (35, 266, width - 70, 270), trade)

    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 10.5)
    c.drawString(35, 239, "买入为什么")
    c.drawString(width / 2 + 8, 239, "卖出为什么")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("STSong-Light", 7.6)
    y_left = 224
    for line in trade["entry_plain"]:
        used = _draw_wrapped(c, "• " + line, 35, y_left, width / 2 - 55, 10.3, max_lines=3)
        y_left -= used + 2
    y_right = 224
    for line in trade["exit_plain"]:
        used = _draw_wrapped(
            c,
            "• " + line,
            width / 2 + 8,
            y_right,
            width / 2 - 43,
            10.3,
            max_lines=3,
        )
        y_right -= used + 2

    alt = "；".join(trade["decision_evidence"]["alternative_explanations"])
    c.setFillColorRGB(0.38, 0.42, 0.47)
    c.setFont("STSong-Light", 6.8)
    _draw_wrapped(
        c,
        f"必要限制/替代解释：{alt or '无额外记录'}。{trade.get('coverage_note') or ''}"
        f"数据等级 {trade['decision_evidence']['pit_grade']}；"
        f"available_at={trade['decision_evidence']['available_at']}；signal_id={trade['signal_id'][:16]}…",
        35,
        53,
        width - 70,
        9,
        max_lines=2,
    )
    c.setFont("Helvetica", 5.8)
    c.drawString(35, 34, f"parameter={payload['parameter_id']} | panel={payload['data_basis']['panel_snapshot_id'][:28]}…")


def _draw_candles(
    c: Any, rect: tuple[float, float, float, float], trade: Mapping[str, Any]
) -> None:
    from reportlab.lib import colors

    x0, y0, width, height = rect
    rows = trade["chart_rows"]
    prices = [
        float(value)
        for row in rows
        for value in (
            row.get("chart_low"),
            row.get("chart_high"),
            row.get("cost_p50"),
            row.get("main_peak"),
        )
        if _is_finite(value)
    ]
    low, high = min(prices), max(prices)
    pad = max((high - low) * 0.07, max(abs(high), 1.0) * 0.005)
    low -= pad
    high += pad
    volume_height = 38
    chart_y0 = y0 + volume_height + 15
    chart_h = height - volume_height - 15
    c.setStrokeColor(colors.HexColor("#D7DEE7"))
    c.setLineWidth(0.35)
    for step in range(5):
        y = chart_y0 + chart_h * step / 4
        c.line(x0, y, x0 + width, y)
        value = low + (high - low) * step / 4
        c.setFillColor(colors.HexColor("#66717F"))
        c.setFont("Helvetica", 6)
        c.drawRightString(x0 + width - 2, y + 2, f"{value:.2f}")
    n = len(rows)
    body_w = max(0.7, min(2.4, width / max(n, 1) * 0.68))
    window_start = date.fromisoformat(str(trade["chart_start"]))
    window_end = date.fromisoformat(str(trade["chart_end"]))
    calendar_span = max((window_end - window_start).days, 1)

    def x_date(raw: Any) -> float:
        value = date.fromisoformat(str(raw)[:10])
        return x0 + (value - window_start).days / calendar_span * width

    def y_price(value: float) -> float:
        return chart_y0 + (value - low) / max(high - low, 1e-12) * chart_h

    finite_volumes = [
        _number(row.get("volume"))
        for row in rows
        if _is_finite(row.get("volume"))
    ]
    max_volume = max(finite_volumes, default=1.0)
    entry_date = trade["entry_at"][:10]
    exit_date = trade["exit_at"][:10]
    signal_date = trade["signal_at"][:10]
    tick = window_start.replace(day=1)
    tick_index = 0
    while tick <= window_end:
        if tick_index % 2 == 0:
            c.setFillColor(colors.HexColor("#647180"))
            c.setFont("Helvetica", 5.7)
            c.drawString(x_date(tick), y0 + 1, tick.strftime("%Y-%m"))
        tick = _shift_months(tick, 1)
        tick_index += 1
    for row in rows:
        x = x_date(row["trade_date"])
        day = str(row["trade_date"])
        open_ = _number(row.get("chart_open"))
        high_ = _number(row.get("chart_high"))
        low_ = _number(row.get("chart_low"))
        close = _number(row.get("chart_close"))
        up = close >= open_
        candle = colors.HexColor("#D54C4C" if up else "#2E9B68")
        c.setStrokeColor(candle)
        c.setFillColor(candle)
        c.setLineWidth(0.45)
        c.line(x, y_price(low_), x, y_price(high_))
        bottom = min(y_price(open_), y_price(close))
        body_h = max(abs(y_price(close) - y_price(open_)), 0.75)
        c.rect(x - body_w / 2, bottom, body_w, body_h, stroke=0, fill=1)
        volume = _number(row.get("volume"))
        if not math.isfinite(volume):
            volume = 0.0
        vh = volume / max(max_volume, 1e-12) * (volume_height - 7)
        c.setFillColor(colors.Color(candle.red, candle.green, candle.blue, alpha=0.35))
        c.rect(x - body_w / 2, y0 + 12, body_w, vh, stroke=0, fill=1)
        if day == signal_date:
            c.setStrokeColor(colors.HexColor("#7754B3"))
            c.setDash(1.5, 1.5)
            c.line(x, chart_y0, x, chart_y0 + chart_h)
            c.setDash()
            c.setFillColor(colors.HexColor("#7754B3"))
            c.setFont("STSong-Light", 6)
            c.drawString(x + 2, chart_y0 + chart_h - 8, "信号")
        if day == entry_date:
            _marker(c, x, y_price(float(trade["entry_price"])), "买", "#1769AA", True)
        if day == exit_date:
            _marker(c, x, y_price(float(trade["exit_price"])), "卖", "#E07A22", False)

    _line_series(c, rows, x_date, y_price, "cost_p50", "#1769AA", dashed=False)
    _line_series(c, rows, x_date, y_price, "main_peak", "#7754B3", dashed=True)
    c.setStrokeColor(colors.HexColor("#9FA9B5"))
    c.rect(x0, y0, width, height, stroke=1, fill=0)
    c.setFont("STSong-Light", 6.5)
    c.setFillColor(colors.HexColor("#4B5866"))
    c.drawString(
        x0 + 4,
        y0 + height - 10,
        f"图窗 {trade['chart_start']} 至 {trade['chart_end']} | 因果分析价格 | 蓝=筹码中位成本 | 紫虚线=主峰 | 下方=成交量",
    )


def _marker(c: Any, x: float, y: float, label: str, color: str, upward: bool) -> None:
    from reportlab.lib import colors

    c.setStrokeColor(colors.HexColor(color))
    c.setFillColor(colors.HexColor(color))
    c.setLineWidth(1.0)
    c.line(x, y - 15, x, y + 15)
    if upward:
        path = c.beginPath()
        path.moveTo(x, y)
        path.lineTo(x - 4, y - 7)
        path.lineTo(x + 4, y - 7)
    else:
        path = c.beginPath()
        path.moveTo(x, y)
        path.lineTo(x - 4, y + 7)
        path.lineTo(x + 4, y + 7)
    path.close()
    c.drawPath(path, stroke=0, fill=1)
    c.setFont("STSong-Light", 6.5)
    c.drawString(x + 3, y + (6 if upward else -10), label)


def _line_series(
    c: Any,
    rows: Sequence[Mapping[str, Any]],
    x_date: Any,
    y_price: Any,
    field: str,
    color: str,
    *,
    dashed: bool,
) -> None:
    from reportlab.lib import colors

    c.setStrokeColor(colors.HexColor(color))
    c.setLineWidth(0.55)
    if dashed:
        c.setDash(2, 1.5)
    path = c.beginPath()
    started = False
    for row in rows:
        value = row.get(field)
        if not _is_finite(value):
            started = False
            continue
        x = x_date(row["trade_date"])
        y = y_price(float(value))
        if started:
            path.lineTo(x, y)
        else:
            path.moveTo(x, y)
            started = True
    c.drawPath(path, stroke=1, fill=0)
    c.setDash()


def _blocked_pages(
    c: Any,
    size: tuple[float, float],
    trades: Sequence[Mapping[str, Any]],
    finish_page: Any,
) -> None:
    width, height = size
    per_page = 25
    for start in range(0, len(trades), per_page):
        _page_title(c, height, "2023 留出期锁定清单（未读取后续行情）")
        c.setFont("STSong-Light", 9)
        c.setFillColorRGB(0.70, 0.13, 0.12)
        _draw_wrapped(
            c,
            "以下交易本身属于 2020-2022 开发期，但卖出后六个月会跨入 2023。为了不提前观察最终留出期价格，本安全版本只列交易事实，不画不完整或偷看后的蜡烛图。",
            42,
            height - 78,
            width - 84,
            13,
            max_lines=4,
        )
        y = height - 127
        c.setFillColorRGB(0.30, 0.36, 0.43)
        c.drawString(42, y, "序号   股票        买入日期      卖出日期      净收益       所需图窗结束")
        y -= 18
        for trade in trades[start : start + per_page]:
            c.setFillColorRGB(0.05, 0.11, 0.18)
            c.setFont("Helvetica", 8)
            c.drawString(
                42,
                y,
                f"{trade['report_index']:03d}    {trade['symbol']:<11}  {trade['entry_at'][:10]}   "
                f"{trade['exit_at'][:10]}   {trade['return_fraction']:+7.2%}    {trade['chart_end']}",
            )
            y -= 15
        c.setFont("STSong-Light", 8.5)
        c.setFillColorRGB(0.35, 0.39, 0.44)
        c.drawString(42, 55, "解锁条件：先完成开发期经济选择并冻结 PASS/NO_TRADE，再按一次性留出协议决定是否允许读取 2023。")
        finish_page()


def _page_title(c: Any, height: float, title: str) -> None:
    c.setFillColorRGB(0.05, 0.11, 0.18)
    c.setFont("STSong-Light", 17)
    c.drawString(42, height - 47, title)
    c.setStrokeColorRGB(0.18, 0.67, 0.72)
    c.setLineWidth(2)
    c.line(42, height - 58, 166, height - 58)


def _footer(c: Any, size: tuple[float, float], page: int) -> None:
    width, _ = size
    c.setFillColorRGB(0.45, 0.50, 0.56)
    c.setFont("Helvetica", 6.5)
    c.drawRightString(width - 35, 18, f"CYQ-GAME research chartbook | page {page}")


def _draw_wrapped(
    c: Any,
    text: str,
    x: float,
    y: float,
    width: float,
    leading: float,
    *,
    max_lines: int,
) -> float:
    from reportlab.pdfbase import pdfmetrics

    font_name = c._fontname
    font_size = c._fontsize
    lines: list[str] = []
    current = ""
    for char in str(text):
        candidate = current + char
        if current and pdfmetrics.stringWidth(candidate, font_name, font_size) > width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    lines = lines[:max_lines]
    for index, line in enumerate(lines):
        c.drawString(x, y - index * leading, line)
    return max(len(lines), 1) * leading


def _plain_evidence(value: str) -> str:
    return {
        "high_turnover_low_price_impact": "高换手但价格不容易被砸下去",
        "sticky_base_and_stable_main_peak": "底部筹码仍黏住且主峰稳定",
        "downside_absorption_and_intraday_support": "下跌有承接且日内重新站回支撑",
        "near_price_chip_growth": "现价附近筹码增加",
        "concentration_improves": "筹码集中度改善",
        "cost_band_narrows_and_concentration_improves": "成本带收窄且筹码集中度改善",
        "asr_and_near_price_chip_growth": "获利筹码比例改善且现价附近筹码增加",
    }.get(value, value)


def _plain_alternative(value: str) -> str:
    key, separator, raw = value.partition("=")
    if not separator:
        return value
    labels = {
        "industry_pit_grade": "行业归属点时等级",
        "data_reason": "数据限制",
        "known_cost_fraction": "已知成本筹码占比",
        "chip_model_disagreement_atr": "三卖方模型分歧",
        "chip_observability_score": "筹码可观测度",
        "global_p90_overhang_atr": "全局九成筹码上方压力",
    }
    label = labels.get(key, key)
    try:
        number = float(raw)
    except ValueError:
        return f"{label}={raw}"
    if key == "known_cost_fraction":
        return f"{label}={number:.1%}"
    if key in {"chip_model_disagreement_atr", "global_p90_overhang_atr"}:
        return f"{label}={number:.2f} ATR"
    return f"{label}={number:.3f}"


def _plain_exit(value: str) -> str:
    return {
        "MAX_HOLDING_PERIOD": "持有期到期",
        "STRUCTURE_BROKEN": "结构破坏",
        "PROTECTIVE_STOP": "保护止损",
        "DISTRIBUTION_CONFIRMED": "派发确认",
        "CORPORATE_ACTION": "公司行动",
        "DATA_INVALID": "数据失效",
    }.get(value, value)


def _exit_pairs(values: Mapping[str, int]) -> str:
    return "；".join(f"{_plain_exit(key)} {value}" for key, value in values.items())


def _pairs(values: Mapping[str, Any]) -> str:
    return " | ".join(f"{key}: {value}" for key, value in values.items())


def _inventory(path: Path, repo: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve().relative_to(repo.resolve())),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duckdb_file_list(paths: Sequence[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def _absolute(repo: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo / path


def _iso_date(value: Any) -> date:
    return date.fromisoformat(str(value)[:10])


def _shift_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _safe_ratio(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
        return math.nan
    return numerator / denominator


def _is_finite(value: Any) -> bool:
    return math.isfinite(_number(value))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value]
    return [str(value)]


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if isinstance(value, Iterable):
        return [_jsonable(item) for item in value]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return number if math.isfinite(number) else None


if __name__ == "__main__":
    raise SystemExit(main())
