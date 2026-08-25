#!/usr/bin/env python3
"""Build the full per-trade chartbook for the observed-return leader.

The 2020-2022 parameter ranking was frozen before this report.  One chart's
post-exit window reaches into 2023; that read is user-authorized, separately
audited, and is display-only.  No 2023 value may feed parameter selection.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import build_e3cf_trade_chartbook_pdf as base

PARAMETER_ID = "9baed76ec299161c"
CONFIG_SHA256 = "e8b4e5e6938f159a328cf456c20ecb03f4b12aed73d10704fd812fcac6504bda"
PANEL_SNAPSHOT_ID = (
    "panel-b27b6247ec34f674c697259d2e5e07e9615b1733743cc13845dce8f52ce54e00"
)
SELECTION_END = date(2022, 12, 30)
DISPLAY_END = date(2023, 6, 16)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "render"), required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--prepared",
        type=Path,
        default=Path("tmp/pdfs/9baed_trade_chartbook_full.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/pdf/9baed_trade_chartbook_full.pdf"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.resolve()
    prepared = base._absolute(repo, args.prepared)
    output = base._absolute(repo, args.output)
    base._entry_plain = _entry_plain
    if args.mode == "prepare":
        _prepare(repo, prepared)
    else:
        base._cover = _cover
        base._summary_page = _summary_page
        base._method_page = _method_page
        base._provenance_page = _provenance_page
        base._trade_page = _trade_page
        base._render(prepared, output)
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
        for bucket in range(32)
    )
    signal_files = tuple(path.with_name("signals.parquet") for path in trade_files)
    for path in (*trade_files, *signal_files):
        if not path.is_file():
            raise FileNotFoundError(path)

    con = duckdb.connect()
    con.execute("PRAGMA threads=1")
    con.execute("PRAGMA memory_limit='1GB'")
    trade_expr = base._duckdb_file_list(trade_files)
    signal_expr = base._duckdb_file_list(signal_files)
    trades = con.execute(
        f"""
        SELECT * EXCLUDE (bucket)
        FROM read_parquet({trade_expr}, hive_partitioning=true)
        WHERE parameter_id = ? AND is_evaluation_row
        ORDER BY CAST(substr(entry_at, 1, 10) AS DATE), symbol, signal_id
        """,
        [PARAMETER_ID],
    ).fetchdf().to_dict("records")
    if len(trades) != 15:
        raise ValueError(f"expected 15 closed trades, found {len(trades)}")
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
    if not {str(row["signal_id"]) for row in trades}.issubset(signals):
        raise ValueError("a closed trade is missing its source signal")

    chart_requests: list[tuple[int, str, date, date]] = []
    for index, trade in enumerate(trades, start=1):
        signal = signals[str(trade["signal_id"])]
        entry_date = base._iso_date(trade["entry_at"])
        exit_date = base._iso_date(trade["exit_at"])
        chart_start = base._shift_months(entry_date, -6)
        chart_end = base._shift_months(exit_date, 6)
        if chart_end > DISPLAY_END:
            raise ValueError(f"chart end exceeds authorized display window: {chart_end}")
        lifecycle_start = min(
            base._iso_date(signal["accumulation_started_at"]),
            base._iso_date(signal["breakout_at"]),
            base._iso_date(signal["retest_confirmed_at"]),
        )
        trade["chart_start"] = chart_start
        trade["chart_end"] = chart_end
        trade["report_index"] = index
        chart_requests.append(
            (index, str(trade["symbol"]), min(chart_start, lifecycle_start), chart_end)
        )

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
    panel_expr = base._duckdb_file_list(panel_files)
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
         AND p.trade_date BETWEEN r.start_date AND least(r.end_date, DATE '2022-12-30')
        ORDER BY r.report_index, p.trade_date
        """
    ).fetchdf().to_dict("records")

    daily_2023 = repo / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=2023/data_0.parquet"
    features_2023 = (
        repo
        / "data/registered_inputs/CY-019-MARKUP-RETEST-MAIN-CHINEXT-2020-2023-V11/features/year=2023/data.parquet"
    )
    for path in (daily_2023, features_2023):
        if not path.is_file():
            raise FileNotFoundError(path)
    cross_holdout = [row for row in chart_requests if row[3] > SELECTION_END]
    if cross_holdout != [(15, "300076.SZ", date(2022, 5, 30), DISPLAY_END)]:
        raise ValueError(f"unexpected 2023 chart request: {cross_holdout}")
    factor_row = con.execute(
        f"""
        SELECT arg_max(price_coordinate_factor, trade_date)
        FROM read_parquet({panel_expr}, hive_partitioning=true)
        WHERE symbol = '300076.SZ' AND trade_date <= DATE '2022-12-30'
        """
    ).fetchone()
    coordinate_factor = float(factor_row[0])
    action_count = con.execute(
        f"""
        SELECT coalesce(sum(corporate_action_count), 0)
        FROM read_parquet('{daily_2023}')
        WHERE symbol = '300076.SZ'
          AND trade_date BETWEEN DATE '2023-01-01' AND DATE '2023-06-16'
        """
    ).fetchone()[0]
    if int(action_count) != 0:
        raise ValueError("2023 display window contains an unhandled corporate action")
    chart_rows.extend(
        con.execute(
            f"""
            SELECT
              15 AS report_index,
              d.symbol,
              d.trade_date,
              d.open / ? AS chart_open,
              d.high / ? AS chart_high,
              d.low / ? AS chart_low,
              d.close / ? AS chart_close,
              d.volume,
              ? AS price_coordinate_factor,
              f.average_cost,
              f.p10 AS cost_p10,
              f.p50 AS cost_p50,
              f.p90 AS cost_p90,
              coalesce(
                try_cast(json_extract_string(f.peaks_json, '$[0].center_price') AS DOUBLE),
                f.p50
              ) AS main_peak,
              f.dominant_band_lower,
              f.dominant_band_upper,
              d.corporate_action_count,
              d.corporate_action_ids,
              NULL::VARCHAR AS market_state,
              NULL::VARCHAR AS sector_state,
              d.industry,
              d.pit_grade AS industry_pit_grade,
              d.hard_valid AS research_hard_valid,
              false AS strategy_eligible,
              NULL::VARCHAR AS tradable_state,
              NULL::DOUBLE AS atr,
              NULL::DOUBLE AS structure_support,
              NULL::DOUBLE AS breakout_excess_atr,
              NULL::DOUBLE AS setup_score,
              NULL::DOUBLE AS distribution_score,
              f.close_vs_vwap,
              d.turnover_fraction,
              NULL::BOOLEAN AS ev_turnover_absorption,
              NULL::BOOLEAN AS ev_near_price_chip_growth,
              NULL::BOOLEAN AS ev_concentration_improves,
              NULL::BOOLEAN AS ev_sticky_base,
              NULL::BOOLEAN AS ev_downside_absorption,
              NULL::BOOLEAN AS dist_base_loss,
              NULL::BOOLEAN AS dist_cost_band_expands,
              NULL::BOOLEAN AS dist_peak_splits,
              NULL::BOOLEAN AS dist_high_turnover_weak_impact,
              NULL::BOOLEAN AS dist_relative_reversal,
              NULL::DOUBLE AS prior_average_cost,
              NULL::DOUBLE AS prior_cost_p50,
              NULL::DOUBLE AS prior_main_peak,
              f.model_spread_cost_p50,
              f.model_spread_cost_p90,
              f.model_spread_main_peak,
              'DISPLAY_ONLY_AFTER_FROZEN_NO_TRADE' AS reason_codes,
              d.daily_snapshot_id,
              f.daily_snapshot_id AS feature_daily_snapshot_id,
              f.minute_snapshot_id AS feature_minute_snapshot_id,
              d.corporate_action_snapshot_id
            FROM read_parquet('{daily_2023}') d
            LEFT JOIN read_parquet('{features_2023}') f
              ON d.symbol = f.symbol AND d.trade_date = f.trade_date
            WHERE d.symbol = '300076.SZ'
              AND d.trade_date BETWEEN DATE '2023-01-01' AND DATE '2023-06-16'
            ORDER BY d.trade_date
            """,
            [coordinate_factor] * 5,
        ).fetchdf().to_dict("records")
    )

    grouped_rows: dict[int, list[dict[str, Any]]] = {}
    for row in chart_rows:
        grouped_rows.setdefault(int(row.pop("report_index")), []).append(row)
    prepared_trades = []
    for trade in trades:
        index = int(trade["report_index"])
        rows = sorted(grouped_rows.get(index, []), key=lambda row: row["trade_date"])
        record = base._make_trade_record(
            trade, signals[str(trade["signal_id"])], rows
        )
        if not record["chart_rows"]:
            raise ValueError(f"empty chart window for trade {index}")
        if index == 15:
            record["coverage_note"] = (
                "2023-01-01 至 2023-06-16 为用户授权的卖后展示区间；"
                "参数排名和收益统计已在读取前冻结为 NO_TRADE，未使用该区间调参。"
            )
        prepared_trades.append(record)

    metrics_path = validation / "entry_economic_evaluation_v2-f678a3e4e893/parameter_metrics.json"
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    metric = next(
        row for row in metrics_payload["parameters"] if row["parameter_id"] == PARAMETER_ID
    )
    ranking = sorted(
        metrics_payload["parameters"],
        key=lambda row: row["trimmed_5pct_mean_net_return_fraction"],
        reverse=True,
    )
    if ranking[0]["parameter_id"] != PARAMETER_ID:
        raise ValueError("parameter is no longer the observed-return leader")
    p0_path = validation / "pit_b_true_oos_calibration_v3.json"
    p0 = json.loads(p0_path.read_text(encoding="utf-8"))
    access_path = validation / "holdout_chartbook_access_20260825.json"
    access = json.loads(access_path.read_text(encoding="utf-8"))
    freeze_path = repo / "output/markup_retest_main_chinext_2020_2023_v1/freeze_manifest.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    if freeze["freeze_decision"] != "NO_TRADE":
        raise ValueError("expected frozen NO_TRADE before 2023 display access")

    economic_root = validation / "entry_economic_evaluation_v2-f678a3e4e893"
    panel_manifest = panel_root.parent / "manifest.json"
    payload = {
        "schema_version": 1,
        "title": f"{PARAMETER_ID} 全部逐笔买卖蜡烛图与决策说明",
        "generated_at": datetime.now().astimezone().isoformat(),
        "parameter_id": PARAMETER_ID,
        "parameters": metric["parameters"],
        "scope": {
            "classification": "WALK_FORWARD_DEVELOPMENT_EVIDENCE / DIAGNOSTIC_ONLY",
            "evaluation_start": "2020-01-02",
            "evaluation_end": "2022-12-30",
            "display_end": "2023-06-16",
            "annotated_bucket_range": [0, 31],
            "annotated_trade_count": len(prepared_trades),
            "complete_chart_count": len(prepared_trades),
            "holdout_blocked_chart_count": 0,
            "research_as_of": "2022-12-30",
            "display_as_of": "2023-06-16",
        },
        "data_basis": {
            "calculation_price_basis": (
                "策略期使用因果公司行动重基后的分析价格坐标；OHLC 为原始未复权事实除以当日可见 price_coordinate_factor。"
            ),
            "display_price_basis": (
                "2020-2022 与精确成交使用同一因果坐标；300076.SZ 的2023展示窗无公司行动，沿用2022-12-30已知坐标因子。"
            ),
            "causal_corporate_action_rebasing": True,
            "post_exit_2023_action_count": int(action_count),
            "post_exit_coordinate_factor": coordinate_factor,
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
        "selection": {
            "ranking_definition": "81组参数中按5%截尾平均净收益降序",
            "observed_rank": 1,
            "formal_selected_parameter_id": None,
            "formal_decision": freeze["freeze_decision"],
            "economic_gate_status": metric["economic_gate_status"],
            "economic_gate_reason_codes": metric["economic_gate_reason_codes"],
            "distinct_signal_weeks": metric["distinct_signal_weeks"],
            "effective_sample": metric["effective_sample"],
            "bootstrap_lower_95": metric["bootstrap_lower_95"],
            "bootstrap_upper_95": metric["bootstrap_upper_95"],
            "baseline_pair_count": metric["baseline_pair_count"],
            "baseline_difference_trimmed_mean": metric[
                "baseline_difference_trimmed_mean"
            ],
            "baseline_difference_lower_95": metric[
                "baseline_difference_lower_95"
            ],
            "baseline_difference_upper_95": metric[
                "baseline_difference_upper_95"
            ],
        },
        "p0_calibration": {
            "status": p0["status"],
            "protocol_version": p0["protocol_version"],
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
                for fold in p0["folds"]
            ],
        },
        "holdout_audit": {
            "access_status": access["payload"]["status"],
            "ledger_sequence": access["ledger_sequence"],
            "authorization_text": access["payload"]["authorization_text"],
            "holdout_outcomes_observed": True,
            "used_for_parameter_selection_or_thresholds": False,
            "selection_was_frozen_before_access": True,
            "freeze_decision_before_access": "NO_TRADE",
            "formal_2023_untouched_claim_allowed": False,
        },
        "parameter_plain_language": [
            "起始吸筹评分必须达到1.00，即五类吸收/稳定证据全部成立。",
            "突破必须高出成本上沿至少0.25 ATR，不能只算勉强越线。",
            "回踩深度最多0.50 ATR，要求突破后的回落较浅。",
            "平均成本与中位成本向上迁移至少0.50 ATR，要求筹码成本明显抬升。",
            "回踩日成交量和换手均不得超过突破日的80%，避免放量砸回。",
            "派发评分连续两天达到0.80时退出；保护线为冻结支撑下方1.50 ATR；最长持有20个交易日。",
        ],
        "summary": {
            "trade_count": metric["closed_trade_count"],
            "mean_return_fraction": metric["mean_net_return_fraction"],
            "trimmed_5pct_mean_return_fraction": metric[
                "trimmed_5pct_mean_net_return_fraction"
            ],
            "median_return_fraction": metric["median_net_return_fraction"],
            "win_rate": metric["win_rate"],
            "profit_factor": metric["profit_factor"],
            "total_net_pnl": sum(float(row["net_pnl"]) for row in trades),
            "best_trade_return_fraction": max(
                float(row["return_fraction"]) for row in trades
            ),
            "worst_trade_return_fraction": min(
                float(row["return_fraction"]) for row in trades
            ),
            "annual_trade_counts": metric["annual_trade_counts"],
            "exit_reason_counts": _counts(trades, "exit_reason"),
            "portfolio_max_drawdown_fraction": metric[
                "portfolio_max_drawdown_fraction"
            ],
            "trade_cvar_1pct": metric["trade_cvar_1pct"],
            "formal_selection_status": "FROZEN_NO_TRADE",
            "formal_gate_note": (
                "它只是完整开发期里观察收益最高的单点，不是正式获胜参数。15笔、12个信号周、有效样本13.77且置信区间跨零；相邻区域和预注册稳健门槛均未通过。"
            ),
        },
        "source_inventory": [
            base._inventory(economic_root / "manifest.json", repo),
            base._inventory(metrics_path, repo),
            base._inventory(economic_root / "robust_region_decision.json", repo),
            base._inventory(freeze_path, repo),
            base._inventory(p0_path, repo),
            base._inventory(access_path, repo),
            base._inventory(panel_manifest, repo),
            base._inventory(daily_2023, repo),
            base._inventory(features_2023, repo),
            {
                "path": "scripts/build_current_best_trade_chartbook_pdf.py",
                "bytes": Path(__file__).stat().st_size,
                "sha256": base._sha256(Path(__file__)),
            },
        ],
        "trades": prepared_trades,
        "holdout_blocked_trades": [],
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
                "parameter_id": PARAMETER_ID,
                "complete_charts": len(prepared_trades),
                "display_end": str(DISPLAY_END),
                "path": str(target),
            },
            ensure_ascii=False,
        )
    )


def _entry_plain(
    signal: Mapping[str, Any], lifecycle: Mapping[str, Mapping[str, Any] | None]
) -> list[str]:
    accumulation = lifecycle.get("accumulation") or {}
    breakout = lifecycle.get("breakout") or {}
    retest = lifecycle.get("retest") or {}
    setup = base._number(accumulation.get("setup_score"))
    breakout_atr = base._number(breakout.get("breakout_excess_atr"))
    retest_depth = base._safe_ratio(
        abs(
            base._number(breakout.get("structure_support"))
            - base._number(retest.get("chart_low"))
        ),
        base._number(retest.get("atr")),
    )
    migration = base._safe_ratio(
        min(
            base._number(retest.get("average_cost"))
            - base._number(breakout.get("prior_average_cost")),
            base._number(retest.get("cost_p50"))
            - base._number(breakout.get("prior_cost_p50")),
        ),
        base._number(retest.get("atr")),
    )
    volume_ratio = base._safe_ratio(
        base._number(retest.get("volume")), base._number(breakout.get("volume"))
    )
    turnover_ratio = base._safe_ratio(
        base._number(retest.get("turnover_fraction")),
        base._number(breakout.get("turnover_fraction")),
    )
    evidence = "、".join(
        base._plain_evidence(item) for item in base._string_list(signal.get("evidence_for"))
    )
    return [
        f"先出现满分吸筹组合：起始评分 {setup:.2f}，门槛1.00。{evidence}。",
        f"随后确认有效突破：高出成本上沿 {breakout_atr:.2f} ATR，门槛至少0.25 ATR。",
        (
            f"回踩仍守住结构：深度 {retest_depth:.2f} ATR（上限0.50）；成本向上迁移 "
            f"{migration:.2f} ATR（下限0.50）；成交量/突破日 {volume_ratio:.2f}，"
            f"换手/突破日 {turnover_ratio:.2f}（均不高于0.80）。"
        ),
        (
            f"冻结底仓保留率下界 {base._number(signal.get('anchor_retention_lower')):.1%}（门槛70%）；"
            f"当时大盘 {signal.get('market_state')}，板块 {signal.get('sector_state')}。"
        ),
        (
            f"信号在 {str(signal.get('decision_at'))[:16]} 收盘后形成，只在下一合法5分钟窗口成交，"
            "没有使用同一根K线内成交。"
        ),
    ]


def _counts(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        key = str(row[field])
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


def _cover(c: Any, size: tuple[float, float], payload: Mapping[str, Any]) -> None:
    width, height = size
    c.setFillColorRGB(0.05, 0.10, 0.18)
    c.rect(0, 0, width, height, stroke=0, fill=1)
    c.setFillColorRGB(0.18, 0.72, 0.78)
    c.rect(42, height - 120, 9, 66, stroke=0, fill=1)
    c.setFillColorRGB(0.96, 0.98, 1.0)
    c.setFont("STSong-Light", 25)
    c.drawString(68, height - 78, "当前观察收益第一名：逐笔蜡烛图")
    c.setFont("Helvetica-Bold", 15)
    c.drawString(68, height - 108, payload["parameter_id"])
    c.setFont("STSong-Light", 12)
    c.drawString(68, height - 163, "完整开发期评估：81组参数、32/32分桶、2020-2022")
    c.drawString(68, height - 188, "完整图窗：15/15笔，每笔买前6个月至卖后6个月")
    c.drawString(68, height - 213, "排名口径：5%截尾平均净收益最高")
    c.setFillColorRGB(1.0, 0.71, 0.35)
    c.drawString(68, height - 238, "正式结论：NO_TRADE - 观察第一不等于通过稳健门槛")
    c.setFillColorRGB(0.75, 0.80, 0.87)
    c.setFont("STSong-Light", 10)
    base._draw_wrapped(
        c,
        "本图册逐笔解释为什么买、为什么卖、当时掌握了什么，以及卖后发生了什么。最后一笔的展示窗经用户明确授权读取至2023-06-16；该结果不允许反向用于调参。",
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
    base._page_title(c, height, "一页看懂：它为什么排第一，又为什么仍是 NO_TRADE")
    summary = payload["summary"]
    selection = payload["selection"]
    metrics = [
        ("完整交易", f"{summary['trade_count']} 笔"),
        ("普通均值", f"{summary['mean_return_fraction']:+.3%}"),
        ("5% 截尾均值", f"{summary['trimmed_5pct_mean_return_fraction']:+.3%}"),
        ("中位数", f"{summary['median_return_fraction']:+.3%}"),
        ("胜率", f"{summary['win_rate']:.1%}"),
        ("Profit Factor", f"{summary['profit_factor']:.3f}"),
        ("累计名义净盈亏", f"{summary['total_net_pnl']:+,.0f} 元"),
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
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 11)
    c.drawString(42, height - 276, "为什么它是观察第一")
    c.drawString(width * 0.53, height - 276, "为什么正式结论仍然不交易")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("STSong-Light", 9)
    base._draw_wrapped(
        c,
        "在完整81组开发期评估中，它的5%截尾平均净收益为+5.375%，按该单一观察指标排名第1；平均收益、中位数、胜率和盈亏比也都为正。",
        42,
        height - 299,
        width * 0.43,
        14,
        max_lines=5,
    )
    base._draw_wrapped(
        c,
        (
            f"只有15笔、12个信号周、有效样本{selection['effective_sample']:.2f}；"
            f"bootstrap 95%区间为 {selection['bootstrap_lower_95']:+.3%} 至 "
            f"{selection['bootstrap_upper_95']:+.3%}，跨过零。相邻参数没有形成共同通过的稳健区域。"
        ),
        width * 0.53,
        height - 299,
        width * 0.41,
        14,
        max_lines=6,
    )
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 10)
    c.drawString(42, 148, "按入场年份")
    c.drawString(245, 148, "退出原因")
    c.drawString(535, 148, "尾部与组合")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("Helvetica", 8.5)
    c.drawString(42, 126, base._pairs(summary["annual_trade_counts"]))
    c.setFont("STSong-Light", 8.5)
    base._draw_wrapped(
        c,
        base._exit_pairs(summary["exit_reason_counts"]),
        245,
        126,
        260,
        12,
        max_lines=3,
    )
    base._draw_wrapped(
        c,
        f"组合最大回撤 {summary['portfolio_max_drawdown_fraction']:.2%}；单笔1% CVaR {summary['trade_cvar_1pct']:.2%}。",
        535,
        126,
        width - 577,
        12,
        max_lines=3,
    )
    c.setFillColorRGB(0.82, 0.16, 0.14)
    c.setFont("STSong-Light", 10)
    base._draw_wrapped(c, summary["formal_gate_note"], 42, 75, width - 84, 14, max_lines=3)


def _method_page(c: Any, size: tuple[float, float], payload: Mapping[str, Any]) -> None:
    width, height = size
    base._page_title(c, height, "参数大白话、读图方法与成交口径")
    sections = [
        ("这组参数在等什么", payload["parameter_plain_language"]),
        (
            "图上每条线是什么",
            [
                payload["data_basis"]["calculation_price_basis"],
                "红K线为上涨、绿K线为下跌；蓝色三角和竖线是实际买入，橙色是实际卖出，紫色竖虚线是信号日。",
                "蓝线是筹码中位成本，紫色虚线是筹码主峰；下方柱体是成交量。",
                "横轴严格使用自然日，停牌或无数据区保留为空白，不用复制价格伪造K线。",
            ],
        ),
        (
            "成交、风险和边界",
            [
                "信号收盘后形成，只能在下一合法5分钟窗口成交；费用5 bps、滑点10 bps、冲击5 bps。",
                "执行遵守T+1；退出受停牌或跌停阻挡时继续记尾部风险，不假设能瞬间卖掉。",
                "筹码分布只是成本状态估计，不是庄家账户透视；资产等级为B_RESEARCH_ONLY。",
                "2023卖后行情只用于展示，读取前正式决策已冻结为NO_TRADE；不得看图后再修改这组参数。",
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
            c.setFont("STSong-Light", 8.2)
            used = base._draw_wrapped(c, "• " + bullet, x, y, col_w, 11.5, max_lines=6)
            y -= used + 8


def _provenance_page(
    c: Any, size: tuple[float, float], payload: Mapping[str, Any]
) -> None:
    width, height = size
    base._page_title(c, height, "数据血缘、校准、正式结论与2023访问审计")
    basis = payload["data_basis"]
    selection = payload["selection"]
    audit = payload["holdout_audit"]
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 11)
    c.drawString(42, height - 91, "选择期与价格坐标")
    c.drawString(width * 0.53, height - 91, "正式选择结论与2023访问")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("STSong-Light", 8)
    left = [
        f"选参研究 as_of={payload['scope']['research_as_of']}；卖后展示 as_of={payload['scope']['display_as_of']}。",
        f"日线={basis['daily_asset']}，分钟={basis['minute_asset']}，筹码={basis['chip_feature_asset']}/{basis['chip_lineage_asset']}，公司行动={basis['corporate_action_asset']}。",
        basis["display_price_basis"],
        f"300076.SZ的2023展示窗公司行动数={basis['post_exit_2023_action_count']}，沿用坐标因子={basis['post_exit_coordinate_factor']:.6f}。",
        f"panel_snapshot_id={basis['panel_snapshot_id']}",
    ]
    y = height - 113
    for item in left:
        used = base._draw_wrapped(c, "• " + item, 42, y, width * 0.46, 11, max_lines=4)
        y -= used + 6
    right = [
        f"81组、32/32分桶已完成；观察排名={selection['observed_rank']}，正式冻结决策={selection['formal_decision']}。",
        f"门禁={selection['economic_gate_status']}；原因={','.join(selection['economic_gate_reason_codes'])}。",
        f"匹配基线14笔；相对基线截尾均值 {selection['baseline_difference_trimmed_mean']:+.3%}，95%区间 {selection['baseline_difference_lower_95']:+.3%} 至 {selection['baseline_difference_upper_95']:+.3%}。",
        f"用户授权原话：{audit['authorization_text']}；追加审计序号={audit['ledger_sequence']}。",
        "2023价格结果现已被观察，不能再称为未触碰留出期；本报告没有据此选参、改阈值、授权EdgeCard或Kelly。",
    ]
    y2 = height - 113
    for index, item in enumerate(right):
        c.setFillColorRGB(0.74, 0.14, 0.12) if index >= 3 else c.setFillColorRGB(0.16, 0.20, 0.26)
        used = base._draw_wrapped(c, "• " + item, width * 0.53, y2, width * 0.41, 11, max_lines=5)
        y2 -= used + 6
    p0 = payload["p0_calibration"]
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 10.5)
    c.drawString(42, 175, "P0真正后续校准")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("STSong-Light", 7.5)
    fold_text = "；".join(
        f"{fold['name']} OOS有效{fold['oos_valid_symbol_count']}只，ECE={fold['weighted_actual_ece']:.4f}，模型/基线Brier={fold['weighted_model_brier']:.4f}/{fold['weighted_baseline_brier']:.4f}"
        for fold in p0["folds"]
    )
    base._draw_wrapped(c, fold_text + "。校准PASS只表示流程真实后续且逐股fail-closed，不等于该参数通过经济门槛。", 42, 156, width - 84, 10, max_lines=3)
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 10)
    c.drawString(42, 111, "关键源文件哈希")
    c.setFillColorRGB(0.22, 0.27, 0.33)
    c.setFont("Helvetica", 5.5)
    y3 = 95
    for item in payload["source_inventory"]:
        c.drawString(42, y3, f"{item['path']}  sha256={item['sha256']}")
        y3 -= 8.2


def _trade_page(
    c: Any,
    size: tuple[float, float],
    trade: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    width, height = size
    outcome_color = (
        (0.78, 0.10, 0.12)
        if trade["return_fraction"] >= 0
        else (0.05, 0.48, 0.30)
    )
    c.setFillColorRGB(0.05, 0.11, 0.18)
    c.setFont("STSong-Light", 14)
    c.drawString(
        35,
        height - 31,
        f"{trade['report_index']:02d}/15  {trade['symbol']}  买 {trade['entry_at'][:10]} → 卖 {trade['exit_at'][:10]}",
    )
    c.setFillColorRGB(*outcome_color)
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(width - 35, height - 31, f"NET {trade['return_fraction']:+.2%}")
    base._draw_candles(c, (35, 266, width - 70, 270), trade)
    c.setFillColorRGB(0.08, 0.23, 0.36)
    c.setFont("STSong-Light", 10.5)
    c.drawString(35, 239, "买入为什么（当时能知道的证据）")
    c.drawString(width / 2 + 8, 239, "卖出为什么（先形成意图，再合法成交）")
    c.setFillColorRGB(0.16, 0.20, 0.26)
    c.setFont("STSong-Light", 7.4)
    y_left = 224
    for line in trade["entry_plain"]:
        used = base._draw_wrapped(c, "• " + line, 35, y_left, width / 2 - 55, 10.1, max_lines=3)
        y_left -= used + 2
    y_right = 224
    for line in trade["exit_plain"]:
        used = base._draw_wrapped(c, "• " + line, width / 2 + 8, y_right, width / 2 - 43, 10.1, max_lines=3)
        y_right -= used + 2
    alt = "；".join(trade["decision_evidence"]["alternative_explanations"])
    c.setFillColorRGB(0.38, 0.42, 0.47)
    c.setFont("STSong-Light", 6.7)
    base._draw_wrapped(
        c,
        f"必要限制/替代解释：{alt or '无额外记录'}。{trade.get('coverage_note') or ''}"
        f"数据等级 {trade['decision_evidence']['pit_grade']}；available_at={trade['decision_evidence']['available_at']}；"
        f"signal_id={trade['signal_id'][:16]}…",
        35,
        53,
        width - 70,
        8.8,
        max_lines=2,
    )
    c.setFont("Helvetica", 5.8)
    c.drawString(35, 34, f"parameter={payload['parameter_id']} | panel={payload['data_basis']['panel_snapshot_id'][:28]}…")


if __name__ == "__main__":
    raise SystemExit(main())
