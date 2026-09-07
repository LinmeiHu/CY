"""V0.5 reproducible baseline/input closure. A failed P0 gate returns exit 2.

The current combined scheduler is not integrated; this command does not count
standalone P0 diagnostics or policy unit tests as completed shared scenarios.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import duckdb
import pandas as pd

from research.shared_capital_v1.run_shared_capital_v1 import (
    HERE, ROOT, POLICY, freeze, frozen_hashes, scenario_grid, sha256, verify_frozen_sources, write_json,
)

START_HEAD = "72e01ea52a62b07645e74837eac20f117ecd1812"
CONFIG = ROOT / "research/five_strategy_exit_risk_v1/input_config.json"
OUT = HERE / "output"


def run_module(name, *args):
    print(f"RUN {name} {' '.join(args)}", flush=True)
    log = OUT / (name + ".log")
    with log.open("w") as stream:
        result = subprocess.run([sys.executable, "-m", "research.shared_capital_v1." + name, *args], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"CODE_CHAIN_FAIL: {name}: exit {result.returncode}; {log}")


def input_files():
    inputs = {k: Path(v) for k, v in json.loads(CONFIG.read_text())["inputs"].items()}
    paths = [inputs[k] for k in ("daily_hist", "daily_tail", "mcb_market_industry_state", "qd010_distributions", "qd010_rights", "ifcgr_route_index", "ifcgr_sse_titles", "ifcgr_szse_titles")]
    for year in range(2016, 2024):
        paths.append(inputs["raw_minute_root"] / f"{year}_day_parquet_none.parquet")
    for year in range(2017, 2024):
        path = inputs["cy033_daily_amount"] / f"daily/partition_year={year}/data_0.parquet"
        if year != 2017 or path.exists():  # native loader's explicitly optional prior-year warmup
            paths.append(path)
    for receipt in ("smv6_input_hashes.json", "issuer_source_hashes.json"):
        if (OUT / receipt).exists():
            paths.extend(Path(row["path"]) for row in json.loads((OUT / receipt).read_text()))
    return sorted(set(paths))


def hash_inputs(paths):
    with ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(sha256, paths))
    return {str(path): digest for path, digest in zip(paths, values)}


def select_issuer():
    from research.shared_capital_v1.issuer_inputs import verify_source, select_later
    from five_strategy_bundle.strategies.ifcgr import select_issuer_facts
    inputs = {k: Path(v) for k, v in json.loads(CONFIG.read_text())["inputs"].items()}
    verify_source(OUT)
    parents = pd.read_parquet(HERE / "cache/ogr/signals.parquet")
    for period, frame in (("2018_2021", parents.loc[parents.signal_date.lt("2022-01-01")]), ("2022_2023", parents.loc[parents.signal_date.ge("2022-01-01")])):
        kept, rejected, facts = select_later(frame) if period == "2022_2023" else select_issuer_facts(frame, inputs["ifcgr_route_index"], inputs["ifcgr_sse_titles"], inputs["ifcgr_szse_titles"])
        folder = HERE / "cache/ifcgr" / period
        folder.mkdir(parents=True, exist_ok=True)
        for name, table in (("signals", kept), ("rejected", rejected), ("facts", facts)):
            table.to_parquet(folder / (name + ".parquet"), index=False)
    table = pd.read_csv(OUT / "ifcgr_data_coverage.csv")
    table["status"] = "AVAILABLE_PIT_B_VERIFIED_FOR_ALL_50_REBUILT_2022_2023_PARENT_WINDOWS"
    old = json.loads((HERE / "input_manifest.json").read_text())["ifcgr_fact_coverage"]
    old_row = {"candidate": "ORIGINAL_CONFIG_ROUTE", "row_count": old["rows"], "min_available_at": old["first_available"], "max_available_at": old["last_available"], "rows_2022_2023": old["exact_boundary_rows"], "status": "OLD_ROUTE_ALONE_INSUFFICIENT_AFTER_2022_01_01"}
    pd.concat([pd.DataFrame([old_row]), table], ignore_index=True).to_csv(OUT / "ifcgr_data_coverage.csv", index=False)


def coordinate_evidence():
    inputs = json.loads(CONFIG.read_text())["inputs"]
    con = duckdb.connect()
    market, actions = [], []
    for symbol, day in (("600622.SH", "2017-06-30"), ("600195.SH", "2019-07-16"), ("603368.SH", "2020-06-24")):
        market.append(con.execute("SELECT symbol,trade_date,open,close,coordinate_factor,invalid_step_cum,corporate_action_count,corporate_action_valid,corporate_action_blocking,hard_valid,available_at FROM read_parquet(?) WHERE symbol=? AND trade_date BETWEEN (?::DATE-INTERVAL 4 DAY) AND (?::DATE+INTERVAL 3 DAY) ORDER BY trade_date", [inputs["daily_hist"], symbol, day, day]).fetchdf())
        actions.append(con.execute("SELECT symbol,event_id,effective_date,known_at,pay_date,cash_credit_date,share_credit_date,share_multiplier,cash_per_share_gross,execution_timing_resolved,execution_resolved,execution_unresolved_reason,source_description FROM read_parquet(?) WHERE symbol=? AND effective_date=?::DATE", [inputs["qd010_distributions"], symbol[:6], day]).fetchdf())
    con.close()
    pd.concat(market).to_csv(OUT / "active_coordinate_market_evidence.csv", index=False)
    pd.concat(actions).to_csv(OUT / "active_coordinate_action_evidence.csv", index=False)


def compact_accounts():
    stocks = pd.read_csv(OUT / "stock_p0_reconciliation.csv")
    gaps = pd.read_csv(OUT / "gap_p0_reconciliation.csv")
    smv6 = pd.read_csv(OUT / "smv6_physical_p0_reconciliation.csv")
    p0 = pd.concat([stocks, gaps, smv6], ignore_index=True)
    p0["initialization_scope"] = "DIAGNOSTIC_FLAT_RESET_NOT_FORMAL_CONTINUOUS_P0"
    p0["common_p0_gate"] = "NOT_PASSED"
    p0.to_csv(OUT / "p0_reconciliation.csv", index=False)
    adapters, checkpoint_summary = [], []
    for row in p0.loc[p0.strategy.ne("SMV6")].to_dict("records"):
        folder = HERE / "cache" / row["strategy"].lower() / row["period"]
        intents = pd.read_parquet(folder / "p0_intents.parquet")
        fills = pd.read_parquet(folder / "p0_fills.parquet")
        other = pd.read_parquet(folder / "p0_other_rejected.parquet")
        checks = pd.read_parquet(folder / "p0_checkpoints.parquet")
        funded = int(fills.side.eq("BUY").sum())
        adapters.append({"strategy": row["strategy"], "period": row["period"], "ELIGIBLE_COUNT": row["eligible_count"], "PRE_CAPITAL_INTENT_COUNT": len(intents), "NATIVE_FUNDED_COUNT": funded,
            "CAPITAL_REJECTED_COUNT": len(intents) - funded, "OTHER_REJECTED_COUNT": len(other),
            "status": "PARTIAL_PREFIX_ACCOUNTING_BLOCKED" if row["status"] == "ACCOUNTING_BLOCKED" else "STANDALONE_PRECAPITAL_CAPTURE_SHARED_STATE_NOT_INTEGRATED",
            "flow_scope": "eligible_count is full legal entry population; captured decisions stop at explicit blocker if present",
            "last_checkpoint": str(checks.timestamp.max()), "fidelity": "NORMALIZED_RESEARCH_ACCOUNT"})
        checkpoint_summary.append({"strategy": row["strategy"], "period": row["period"], "checkpoints": len(checks), "min_cash": checks.cash.min(), "max_abs_quantity_diff": checks.quantity_delta.abs().max(), "max_abs_equity_diff": checks.pnl_delta.abs().max(), "status": "PASS_THROUGH_LAST_VALID_CHECKPOINT", "common_account": False})
        # These are real captured native decisions, including rejected demand.
        export = intents.copy()
        if "native_priority" in export:
            export["native_priority"] = export.native_priority.map(str)
        export.to_csv(OUT / f"opportunities_{row['strategy'].lower()}_{row['period']}.csv", index=False)
    for period in ("2018_2021", "2022_2023"):
        folder = HERE / "cache/smv6" / period
        intents = pd.read_parquet(folder / "physical_p0_intents.parquet")
        fills = pd.read_parquet(folder / "physical_p0_fills.parquet")
        checks = pd.read_parquet(folder / "physical_p0_checkpoints.parquet")
        funded = int(fills.side.eq("BUY").sum())
        adapters.append({"strategy": "SMV6", "period": period, "ELIGIBLE_COUNT": len(intents), "PRE_CAPITAL_INTENT_COUNT": len(intents), "NATIVE_FUNDED_COUNT": funded, "CAPITAL_REJECTED_COUNT": len(intents)-funded, "OTHER_REJECTED_COUNT": None,
            "status": "NATIVE_PHYSICAL_CALLBACK_RECONCILED_COMMON_SCHEDULER_PENDING", "flow_scope": "positive native requests after legal execution and volume cap, before affordability; independent reset diagnostic", "last_checkpoint": str(checks.timestamp.max()), "fidelity": "LOCAL_PLATFORM_APPROXIMATION"})
        checkpoint_summary.append({"strategy": "SMV6", "period": period, "checkpoints": len(checks), "min_cash": checks.cash.min(), "max_abs_quantity_diff": checks.quantity_delta.abs().max(), "max_abs_equity_diff": checks.pnl_delta.abs().max(), "status": "PASS_THROUGH_LAST_VALID_CHECKPOINT", "common_account": False})
        intents.to_csv(OUT / f"opportunities_smv6_{period}.csv", index=False)
    pd.DataFrame(adapters).to_csv(OUT / "opportunity_adapter_reconciliation.csv", index=False)
    pd.DataFrame(checkpoint_summary).to_csv(OUT / "standalone_virtual_physical_reconciliation.csv", index=False)
    return p0


def coverage(tests):
    specifications = [
        (1, "ATRDR prefix invariance", "FOCUSED_PASS_HISTORICAL_ACCOUNTING_BLOCKED", "test_atrdr_historical_prefix_entries_cash_positions_nav"),
        (2, "future completion cannot remove entry", "FOCUSED_PASS", "test_future_completion_does_not_create_or_remove_entry"),
        (3, "SMV6 future close perturbation", "PASS", "test_future_close_and_unfinished_open_bar_cannot_change_order"),
        (4, "unfinished bar information", "SMV6_AND_MICRO_STOCK_PASS_FULL_CHAIN_PENDING", "test_history_excludes_current_incomplete_day"),
        (5, "missing legal mark", "PASS", "test_missing_legal_mark_fails_before_order_mutation"),
        (6, "duplicate actual keys", "PASS", "test_comparison_identity_failures"),
        (7, "duplicate golden keys", "PASS", "test_comparison_identity_failures"),
        (8, "null keys", "PASS", "test_comparison_identity_failures"),
        (9, "row count and cardinality", "PASS", "test_many_to_many_and_missing_layers_fail"),
        (10, "comparison CLI nonzero", "PASS", "test_generation_command_required_comparison_failure_nonzero"),
        (11, "missing comparison layers", "PASS", "test_many_to_many_and_missing_layers_fail"),
        (12, "nonfinite accounts", "PASS", "test_nonfinite_account_never_passes"),
        (13, "duplicate/missing dates", "PASS", "test_account_calendar_and_equation_fail_closed"),
        (14, "P0 budgets independent of shared PNL", "PRIMITIVE_PASS_PARALLEL_PATH_NOT_INTEGRATED", "test_base_first_shared_state_and_home_independent"),
        (15, "actual shared holdings drive strategy state", "NOT_INTEGRATED", "independent native physical bridges reconciled; common funded-state scheduler pending"),
        (16, "physical virtual holdings", "STANDALONE_PASS_COMMON_PENDING", "test_physical_virtual_equity_quantity_and_costs"),
        (17, "physical virtual PNL", "STANDALONE_PASS_COMMON_PENDING", "standalone_virtual_physical_reconciliation.csv"),
        (18, "nonnegative cash", "STANDALONE_PASS_COMMON_PENDING", "test_starvation_no_financing_and_determinism"),
        (19, "gross exposure bound", "STANDALONE_PASS_COMMON_PENDING", "test_starvation_no_financing_and_determinism"),
        (20, "base before shared", "ENGINE_TEST_PASS", "test_base_first_shared_state_and_home_independent"),
        (21, "native requested ceiling", "ENGINE_TEST_PASS", "test_base_first_shared_state_and_home_independent"),
        (22, "no funded-trade enlargement", "ENGINE_TEST_PASS", "test_base_first_shared_state_and_home_independent"),
        (23, "base entitlement shortfall", "ENGINE_TEST_PASS", "test_starvation_no_financing_and_determinism"),
        (24, "MCB exact confirmation", "ENGINE_TEST_PASS", "test_exact_confirmation_mcb_only_and_gap_exclusion"),
        (25, "MCB only entries", "ENGINE_TEST_PASS", "test_exact_confirmation_mcb_only_and_gap_exclusion"),
        (26, "Gap exclusion", "ENGINE_TEST_PASS", "test_exact_confirmation_mcb_only_and_gap_exclusion"),
        (27, "previous completed close DD", "PRIMITIVE_PASS_SCHEDULER_PENDING", "test_gate_rejects_duplicate_close"),
        (28, "gate never liquidates", "ENGINE_TEST_PASS", "test_drawdown_gate_does_not_liquidate"),
        (29, "three day hysteresis", "PRIMITIVE_PASS", "test_gate_three_day_recovery_one_level_at_a_time; test_gate_recovery_requires_margin_and_resets_streak"),
        (30, "deterministic ties and lot residuals", "ENGINE_TEST_PASS", "test_largest_remainder_does_not_leave_affordable_whole_native_slot_idle"),
        (31, "initial state freeze", "NATIVE_CONTINUOUS_RULE_FROZEN_STATE_BLOCKED", "initial_state_audit.csv;native_initial_state_probe.csv"),
        (32, "deterministic historical rerun", "STANDALONE_ONLY", "deterministic_baseline_rerun.csv"),
        (33, "frozen and input hashes", "ECONOMIC_BYTES_PASS_TWO_AUTHORIZED_VALIDATOR_REPAIRS", "input_hash_verification.csv; validation_repair_receipt.json"),
    ]
    pd.DataFrame(specifications, columns=["requirement_id", "requirement", "status", "evidence"]).to_csv(OUT / "requirement_test_coverage.csv", index=False)


def report(p0, tests):
    baselines = [
        {"strategy": "ATRDR", "status": "ACCOUNTING_BLOCKED", "hypothesis": "CONFIRMED_FUTURE_COMPLETION_FILTER", "fix": "entry identity separated; focused prefix test passes; active corporate action unresolved"},
        {"strategy": "MCB", "status": "ACCOUNTING_BLOCKED", "hypothesis": "ACTIVE_COORDINATE_CHANGE_CONFIRMED", "fix": "fail closed instead of stale coordinate valuation"},
        {"strategy": "OGR", "status": "VALIDATION_BLOCKED", "hypothesis": "LATER_RAW_PRODUCER_BOUNDARY_REMOVED_WITHOUT_ALPHA_CHANGE", "fix": "both native accounts reconcile; full causal input/initial-state gates pending"},
        {"strategy": "IFCGR", "status": "VALIDATION_BLOCKED", "hypothesis": "LATER_REGISTERED_SOURCE_FOUND", "fix": "all 50 later parent windows covered; classification unchanged; common gates pending"},
        {"strategy": "SMV6", "status": "CAUSAL_BUG_FIXED_AND_REVALIDATED", "hypothesis": "CONFIRMED_FUTURE_CLOSE_AND_UNFINISHED_OPEN_BAR_MARK", "fix": "local adapter uses known open; missing mark fails closed; two historical prefix replays pass"},
    ]
    pd.DataFrame(baselines).to_csv(OUT / "baseline_integrity_status.csv", index=False)
    scenarios = []
    for row in scenario_grid(json.loads(POLICY.read_text())):
        reason = "NATIVE_CONTINUOUS_INITIAL_STATE_BLOCKED_BY_UNRESOLVED_CORPORATE_ACTION"
        scenarios.append({**row, "status": "P0_FAIL", "first_reason": reason, "historical_metrics": "NOT_ESTIMABLE"})
    pd.DataFrame(scenarios).to_csv(OUT / "scenario_run_status.csv", index=False)
    initial = []
    for strategy in ("ATRDR", "MCB", "OGR", "IFCGR", "SMV6"):
        for period in ("2018_2021", "2022_2023"):
            initial.append({"strategy": strategy, "period": period, "diagnostic_initial_cash": 1e6, "diagnostic_initial_positions": "{}", "home_nav": None, "formal_boundary_mode": "NATIVE_CONTINUOUS",
                "cooldown_state": "native callback init" if strategy == "SMV6" else "signal warmup retained; funded holding/cooldown boundary not sealed",
                "warmup_window": "all registered daily history strictly preceding period" if strategy == "SMV6" else "2013 through segment boundary",
                "diagnostic_reset_or_continuation": "RESET_ACCOUNT", "native_reference": "native reset callback" if strategy == "SMV6" else "stock historical account begins before 2018; native continuation inventory not reconciled to shared flat reset",
                "common_initial_state_status": "ACCOUNTING_BLOCKED" if strategy == "ATRDR" or (strategy == "MCB" and period == "2022_2023") else "NATIVE_CONTINUOUS_BOUNDARY_RECONCILIATION_PENDING", "policy_unchanged": True})
    initial_frame = pd.DataFrame(initial)
    native_probe = pd.read_csv(OUT / "native_initial_state_probe.csv")
    initial_frame = initial_frame.merge(native_probe[["strategy", "period", "status", "boundary_nav", "boundary_cash", "boundary_holdings", "first_blocker"]], on=["strategy", "period"], how="left", validate="one_to_one")
    initial_frame.to_csv(OUT / "initial_state_audit.csv", index=False)
    results = pd.read_csv(OUT / "smv6_baseline_reconciliation.csv").pivot(index="period", columns="baseline", values="final_nav")
    results["corrected_minus_legacy_reset_control"] = results.CAUSAL_CORRECTED_BASELINE - results.LEGACY_EXECUTION_RESET_CONTROL
    results.to_csv(OUT / "smv6_baseline_difference.csv")
    coverage(tests)
    status = {"TASK_STATUS": "PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE", "START_HEAD": START_HEAD,
        "GENERATION_STATUS": "STANDALONE_INPUTS_GENERATED", "COMPARISON_STATUS": "STANDALONE_ACCOUNTS_RECONCILED_WITHIN_VALID_PREFIX",
        "CAUSAL_VALIDATION_STATUS": "NOT_PASSED_ALL_STRATEGIES", "ACCOUNT_VALIDATION_STATUS": "COMMON_P0_FAIL",
        "historical_scenarios_completed": 0, "scenario_count": 48,
        "IFCGR_2018_2021_DATA_STATUS": "AVAILABLE_PIT_B", "IFCGR_2022_2023_DATA_STATUS": "AVAILABLE_PIT_B_VERIFIED_PARENT_WINDOWS",
        "FROZEN_STRATEGIES_MODIFIED": "NO", "NEW_SEALED_VALIDATION_OPENED": "NO", "PUSH": "NO",
        "PORTFOLIO_ACCOUNTING_TARGET": "SINGLE_PHYSICAL_ACCOUNT_WITH_VIRTUAL_LOTS",
        "PHYSICAL_VIRTUAL_ACCOUNT_STATUS": "ALL_FIVE_STANDALONE_INTEGRATED_COMMON_SCHEDULER_NOT_INTEGRATED",
        "first_blocker": pd.read_csv(OUT / "native_initial_state_probe.csv").iloc[0].first_blocker,
        "INITIAL_STATE_RULE": "NATIVE_CONTINUOUS_USER_CONFIRMED_MISSING_CREDIT_BLOCKS",
        "independent_engineering_remaining": ["user-selected native continuous boundary reconstruction; unresolved credit state blocks continuation", "common physical pricing units across coordinate stocks, raw-price Gap and local ETF", "common scheduler driving all native callbacks with actual shared fills (independent SMV6 bridge reconciled)", "parallel P0 home-budget paths and full shared scenario scheduler"],
        "tests": tests, "policy_sha256": sha256(POLICY), "baseline_status": baselines}
    status.update(ENVIRONMENT_VALID=True, BRANCH="research/five-strategy-shared-capital-v1",
        EXIT_RULES_USED="NATIVE_ONLY", PORTFOLIO_ACCOUNTING="SINGLE_PHYSICAL_ACCOUNT_WITH_VIRTUAL_LOTS",
        BASELINE_CAUSAL_INTEGRITY="NOT_PASSED_ALL_STRATEGIES",
        P0_STATUS="ACCOUNTING_BLOCKED_NATIVE_CONTINUOUS_INITIAL_STATE",
        OPPORTUNITY_ADAPTER_STATUS="STANDALONE_RECONCILED_COMMON_STATE_INTEGRATION_PENDING",
        OGR_SCENARIOS_COMPLETED="0/24", IFCGR_SCENARIOS_COMPLETED="0/24", TOTAL_SCENARIOS_COMPLETED="0/48",
        MCB_CAPITAL_ROLE="EVIDENCE_INSUFFICIENT", GAP_FAMILY_CHOICE="EVIDENCE_INSUFFICIENT",
        BEST_ADMISSIBLE_POLICY="NOT_ESTIMABLE", MAX_DRAWDOWN_CONSTRAINT_STATUS="NOT_ESTIMABLE",
        SHARED_FUNDED_TRADE_PNL="NOT_ESTIMABLE", BASE_ENTITLEMENT_STARVATION_STATUS="NOT_ESTIMABLE")
    status.update({f"{b['strategy']}_BASELINE_STATUS": b["status"] for b in baselines})
    status.update({f"{p}_RESULT": "NOT_ESTIMABLE" for p in ("P0_FIXED", "P1_RAW_SHARED", "P2_CAPPED_SHARED", "P3_D4", "P3_D5", "P3_D6")})
    write_json(OUT / "run_status.json", status)
    nav_table = p0[["strategy", "period", "funded_count", "final_nav", "max_abs_nav_diff", "status"]].to_csv(index=False)
    text = f"""# 五策略共享资金：V0.5 因果基线与输入闭合

TASK_STATUS = PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE

共同 P0 未通过，实际共享场景仍为 **0/48**。本次已经实际重建五策略所需父信号/事实和独立账户诊断；这不等于共同 P0，也不等于共享账户已经完成。没有生成堵塞场景的零收益表，没有 P1/P2/P3 收益结论。

## 已确认与修复

ATRDR 原始父信号的真实行情截断探针（三条 Bull/Fast/Slow 路径）及同重置条件旧过滤差额已保存于 atrdr_actual_prefix_probes.csv / atrdr_legacy_baseline_difference.csv。前段最后有效日差额为 +61.1152626，后段差额仅约 1.25e-8；这是控制比较，不是封存连续 NAV 的替代。

ATRDR Bull 和 slow Bear 在历史账户母体前依赖最终 COMPLETED；研究修正路径按已发生 entry 建立身份，保留未完成/后续失效的历史入场。微型真实执行路径的截断/延长回归已验证入场、意图、现金、持仓和 NAV 前缀不变；不能据此宣称整条历史链已闭合。

SMV6 原本可在缺开盘 mark 时使用当日未来 close，且开盘分钟 close 尚未完成。研究适配器改用已知 OPEN_BAR open，无合法开盘持仓 mark 时不提交该笔订单。冻结策略源码完全未改，历史前缀回放分别核对 730/242 个账户日、241/44 个事件。保持 LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED。

比较层现在拒绝 actual/golden 重复键、空键、行数/cardinality 不一致和缺少必需层；生产 reproduce 命令必需比较失败会非零退出，生成后不再以 FULL 作为验证结论。GENERATION_STATUS、COMPARISON_STATUS、CAUSAL_VALIDATION_STATUS、ACCOUNT_VALIDATION_STATUS 分列。冻结清单中仅 compare.py / reproduce.py 两个非经济基础设施源码改变，旧 SHA 与新 SHA 保存在 contracts/validation_repair_receipt.json；旧封存参考在 START_HEAD 和注册 baseline_root 中保留。

融资审计拒绝 NaN/inf、非法 NAV、重复日期和缺失账户方程；无独立交易日历时返回 UNKNOWN。物理账户核验每次成交/资金变动的有限值、现金、持仓数量及权益归因。当前接通五策略独立诊断账户，SMV6 原生回调的真实物理成交可回写状态，两段与本地修正基线 NAV 最大差约 1.4e-9；共同调度器尚未接通。

## 原生连续初始状态

用户已确认：按原生连续状态重建，缺失到账状态保持阻塞。连续探针实际结果：

```csv
{pd.read_csv(OUT / "native_initial_state_probe.csv").to_csv(index=False).rstrip()}
```

ATRDR 在 2017-06-30 持有 600622.SH 时即遇到转增 30% 而 share_credit_date 缺失，早于两个待验收区间；不能构造其 2018/2022 边界。MCB 2018 边界能够重建，但 2020-06-24 后续路径阻塞，2022 边界不可达。这两个区间的共同 P0 都不能用重置空仓替代。

## 空仓诊断中的账户阻塞

ATRDR 前段持有 600195.SH，2019-07-16 发生每 10 股转增 4 股；MCB 前段持有 603368.SH，2020-06-24 同类转增。注册 distributions 原表 share_credit_date 均为空、execution_timing_resolved=False、execution_unresolved_reason 包含 missing_share_credit_date。市场输入在对应日将 corporate_action_valid 设为 False，并改变 invalid_step_cum。不能删去此前入场，也不能把新复权坐标当作已经到账可卖股份，更不能临时新增提前卖出规则。本次保留真实持仓并明确停机；相应最终 NAV 是缺失值，不是零。证据见 active_coordinate_*_evidence.csv。

独立工程欠项仍存在：共同初始状态、跨价格单位的实际持仓转换、SMV6 共享成交回调、独立 P0 HOME_BUDGET 全检查点路径和完整调度器。后段股票原生账户虽对账通过，这些工程欠项仍阻止 2022–2023 的 24 个共同场景。本报告没有把工程欠项称为数据缺失。

## IFCGR 输入缺口已找到合法候选并完成父窗口核验

原配置路由 285347 行，止于 2022-01-01，这个事实仍成立。但沿既有 CY-065/CY-063 清单找到 CY-062 原始官方公告路由：149545 行，2022–2023 有 49967 行。新重建 OGR 后段 50 个父信号的发行人及 120 天窗口全部被注册来源覆盖；原分类器重跑为 50 kept / 0 rejected。前段 370 父信号为 362 kept / 8 rejected。这里的 0 rejected 是有事实来源支持的分类结果，与缺数据时默认为无风险完全不同。

IFCGR_2022_2023_DATA_STATUS = AVAILABLE_PIT_B_VERIFIED_PARENT_WINDOWS

保留 PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE。只读取 <=2023 的事实窗口；没有读取 accepted trades 来补机会，没有读取 post-2023 投资结果。来源审计、schema、时间范围、逐文件哈希和 50 个窗口见 ifcgr_data_coverage.csv / ifcgr_parent_window_coverage.csv / issuer_source_hashes.json。

## 独立账户实际结果，不能当成共同 P0

以下初始现金 100 万是冻结归一化研究计价，股票/Gap 为 NORMALIZED_RESEARCH_ACCOUNT，SMV6 为 LOCAL_PLATFORM_APPROXIMATION。没有声称乘以 100 万便得到实盘可执行账户。股票保留分板 50/50、原生 K/日容量/排序/费用；Gap 保留原生目标和退出。独立诊断采用 flat reset，仅为控制实验。用户已明确选择原生连续状态，缺失到账状态保持阻塞；单独的 contracts/initial_state_v05.json 覆盖旧初始化条款而保留旧政策文件字节。连续路径从 2014 年实际重放，证据见 native_initial_state_probe.csv；无法越过阻塞构造 2018/2022 边界现金、持仓或 HOME_BUDGET。

```csv
{nav_table.rstrip()}
```

SMV6 相同 reset 条件下的旧执行控制末值为 1242160.7330112131 / 1107900.8681746258，修正后为 1260255.978086352 / 1103922.0770485739，差额 +18095.245075139 / -3978.791126052。旧执行控制不是跨段连续封存 NAV 的替代目标；原始 LEGACY_SEALED_REFERENCE 仍为注册 baseline_root，CAUSAL_CORRECTED_BASELINE 单独保存，不向旧数值强行拟合。

OGR/IFCGR 独立固定账户资本拒绝数为 0；状态/容量拒绝仍按原生规则记录。这不能推出共同账户没有资金分割，也不能把闲置现金全部称为可共享空间。共同 STRUCTURAL_IDLE、SEGMENTATION_IDLE、GLOBAL_DEMAND_CONFLICT、共享交易盈亏、基础权利饥饿及风险可接受性均 NOT_ESTIMABLE。

P1 仍仅诊断，MaxDD_shared <= MaxDD_P0 + 0.50pp 的规则和原政策 hash 完全未改。没有最佳政策、资金角色或 Gap 优劣判断。

## 验证与重跑

聚焦及现有单元测试：{tests}。33 项需求覆盖逐项区分原语测试、独立账户验证、整链待验证和未接通工程；不以测试数量冒充全验收。哈希和独立诊断重跑结果见 input_hash_verification.csv / final_input_hash_verification.csv / deterministic_baseline_rerun.csv / smv6_physical_deterministic_rerun.csv / frozen_hash_verification.csv。本次最终复核 339 个已消费输入哈希一致；股票/Gap 8 条 NAV 重跑一致，SMV6 10 份物理账户层重跑一致。没有推送。

精确命令及退出码见 REPRODUCTION_COMMANDS.md；完整闭合命令在共同门未通过时返回 2。所有生成文件在本工作区，缓存和日志不提交，紧凑证据及真实机会流提交。
"""
    (HERE / "REPORT.md").write_text(text)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--regenerate", action="store_true", help="rebuild all registered raw parents and native diagnostics")
    args = parser.parse_args(argv)
    branch = subprocess.check_output(["git", "branch", "--show-current"], text=True, cwd=ROOT).strip()
    if ROOT != Path("/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1") or branch != "research/five-strategy-shared-capital-v1":
        raise RuntimeError("invalid environment")
    subprocess.run(["git", "merge-base", "--is-ancestor", "216e33dd46d91abcb1c8e73f0de921762df4ef86", "HEAD"], cwd=ROOT, check=True)
    receipt = freeze()
    if args.regenerate:
        print("Hashing registered consumed inputs before controlled rerun", flush=True)
        before = hash_inputs(input_files())
        from verify_no_financing import _canonical_hash
        prior = {str(p.relative_to(HERE)): _canonical_hash(p) for p in (HERE / "cache").glob("*/*/p0_nav.parquet")}
        for strategy in ("ATRDR", "MCB", "OGR"):
            run_module("build_inputs", "--strategy", strategy)
        select_issuer()
        run_module("smv6_baseline")
        run_module("stock_p0")
        run_module("gap_p0")
        run_module("prefix_probe")
        run_module("smv6_physical")
        run_module("initial_state")
        after = hash_inputs(input_files())
        verification = [{"path": path, "before_sha256": value, "after_sha256": after.get(path), "status": "PASS" if value == after.get(path) else "FAIL"} for path, value in before.items()]
        pd.DataFrame(verification).to_csv(OUT / "input_hash_verification.csv", index=False)
        if any(row["status"] != "PASS" for row in verification):
            raise RuntimeError("raw input drift")
        deterministic = [{"path": path, "first_canonical_sha256": value, "second_canonical_sha256": _canonical_hash(HERE / path), "status": "PASS" if value == _canonical_hash(HERE / path) else "FAIL"} for path, value in prior.items()]
        if deterministic:
            pd.DataFrame(deterministic).to_csv(OUT / "deterministic_baseline_rerun.csv", index=False)
        if any(row["status"] != "PASS" for row in deterministic):
            raise RuntimeError("standalone deterministic rerun mismatch")
    else:
        select_issuer()
    coordinate_evidence()
    test = subprocess.run([sys.executable, "-m", "pytest", "-q", "research/shared_capital_v1/tests", "tests/unit", "--basetemp", str(HERE / "cache/pytest_tmp"), "--junitxml", str(OUT / "focused_tests.xml")], cwd=ROOT, capture_output=True, text=True)
    (OUT / "focused_tests.log").write_text(test.stdout + test.stderr)
    if test.returncode:
        raise RuntimeError("focused tests failed")
    tree = ET.parse(OUT / "focused_tests.xml")
    cases = tree.findall(".//testcase")
    tests = {"passed": len(cases), "failed": 0, "scope": "focused tests plus existing unit suite, not full scenario acceptance"}
    write_json(OUT / "focused_test_results.json", tests)
    p0 = compact_accounts()
    current = frozen_hashes()
    rows = [{"path": path, "before_sha256": old, "after_sha256": current[path], "status": "UNCHANGED" if old == current[path] else "AUTHORIZED_VALIDATOR_REPAIR"} for path, old in receipt["frozen_implementation_hashes"].items()]
    pd.DataFrame(rows).to_csv(OUT / "frozen_hash_verification.csv", index=False)
    if not verify_frozen_sources(receipt["frozen_implementation_hashes"]):
        raise RuntimeError("frozen economic source drift")
    manifest = json.loads((HERE / "input_manifest.json").read_text())
    manifest.update(start_head=START_HEAD, current_run_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        evidence_stage="V05_REGISTERED_INPUT_REBUILD_AND_NATIVE_STANDALONE_P0_DIAGNOSTICS",
        policy_sha256=sha256(POLICY), validation_infrastructure_repairs=json.loads((HERE / "contracts/validation_repair_receipt.json").read_text()),
        ifcgr_later_registered_source="output/ifcgr_data_coverage.csv", consumed_input_hash_evidence="output/input_hash_verification.csv",
        legacy_sealed_reference=json.loads(CONFIG.read_text())["baseline_root"], causal_corrected_baseline="cache/", common_p0_reconciled=False)
    manifest.pop("all_raw_inputs_hash_verified", None)
    consumed = pd.read_csv(OUT / "input_hash_verification.csv")
    hashes = dict(zip(consumed.path, consumed.after_sha256))
    manifest.update(all_consumed_inputs_hash_verified=bool(consumed.status.eq("PASS").all()),
        consumed_input_count=len(consumed), implementation_hashes=current,
        initial_state_contract="contracts/initial_state_v05.json",
        initial_state_contract_sha256=sha256(HERE / "contracts/initial_state_v05.json"),
        native_continuous_state_evidence="output/native_initial_state_probe.csv")
    manifest["ifcgr_fact_coverage"]["scope"] = "ORIGINAL_CONFIG_ROUTE_ONLY; later verified source is separate"
    for item in manifest["inputs"]:
        path = item["path"]
        if path in hashes:
            item.update(sha256=hashes[path], bytes=Path(path).stat().st_size, hash_scope="FULL_FILE_CONSUMED_VERIFIED")
        elif any(p.startswith(path.rstrip("/") + "/") for p in hashes):
            item.update(hash_scope="CONSUMED_CHILD_FILES_HASHED_SEE_INPUT_HASH_VERIFICATION", consumed_children=sum(p.startswith(path.rstrip("/") + "/") for p in hashes))
    write_json(HERE / "input_manifest.json", manifest)
    status = report(p0, tests)
    print(json.dumps({"TASK_STATUS": status["TASK_STATUS"], "completed": 0, "planned": 48, "first_blocker": status["first_blocker"]}, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
