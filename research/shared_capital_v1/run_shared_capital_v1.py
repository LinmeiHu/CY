"""Fail-closed V1 inventory runner. Historical execution is not yet implemented.

The inventory proves the supplied IFCGR raw-fact coverage blocker, rather than
treating an empty post-2021 fact population as an issuer-filter pass. Exit 2
means PARTIAL_COMPLETE, never a successful historical scenario replay.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
POLICY = HERE / "contracts/shared_capital_policy_v1.json"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def write_csv(path, rows):
    if not rows:
        raise ValueError("Empty placeholder tables are not research deliverables")
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def frozen_hashes():
    return {
        str(p.relative_to(ROOT)): sha256(p)
        for directory in ("src", "configs/frozen", "manifests", "original_sources")
        for p in sorted((ROOT / directory).rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


def verify_frozen_sources(expected):
    current = frozen_hashes()
    repairs_path = HERE / "contracts/validation_repair_receipt.json"
    repairs = json.loads(repairs_path.read_text()) if repairs_path.exists() else {}
    allowed = {"src/five_strategy_bundle/compare.py", "src/five_strategy_bundle/reproduce.py"}
    if set(current) != set(expected):
        return False
    for path, digest in current.items():
        if digest == expected[path]:
            continue
        repair = repairs.get(path, {})
        if path not in allowed or repair.get("before_sha256") != expected[path] or repair.get("after_sha256") != digest:
            return False
    return True


def freeze():
    digest = sha256(POLICY)
    receipt = HERE / "contracts/freeze_receipt.json"
    if receipt.exists():
        expected = json.loads(receipt.read_text())
        if expected["policy_sha256"] != digest:
            raise RuntimeError("Frozen economic policy changed")
        if not verify_frozen_sources(expected["frozen_implementation_hashes"]):
            raise RuntimeError("Frozen implementation/input-contract drift")
    else:
        write_json(receipt, {
            "policy_sha256": digest,
            "start_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "outcome_bearing_scenarios_before_freeze": 0,
            "frozen_implementation_hashes": frozen_hashes(),
        })
    return json.loads(receipt.read_text())


def scenario_grid(policy):
    return [
        {"period": period, "gap": gap, "mcb_mode": mode, "policy": name}
        for period, gap, mode, name in itertools.product(
            policy["periods"], ("OGR", "IFCGR"), policy["mcb_modes"], policy["policies"]
        )
    ]


def source_evidence():
    markers = {
        "src/five_strategy_bundle/strategies/ogr.py": (
            'end: str = "2021-12-31"',
            "dt.year.isin((2017, 2018, 2019, 2020, 2021))",
            "_load_cy033(cy033_root, (2018, 2019, 2020, 2021)",
        ),
        "src/five_strategy_bundle/strategies/ifcgr.py": (
            "WHERE r.causal_available_at<TIMESTAMP '2022-01-01'",
        ),
        "research/five_strategy_exit_risk_v1/state_v2.py": (
            "('IFCGR', 'ifcgr_cy065_trades')", "read_bound(p[key]",
        ),
    }
    return [
        {"source": source, "line": i, "evidence": line.strip()}
        for source, tokens in markers.items()
        for i, line in enumerate((ROOT / source).read_text().splitlines(), 1)
        if any(token in line for token in tokens)
    ]


def inventory(config, out, receipt):
    import duckdb

    raw = json.loads(config.read_text())
    assets = raw.get("inputs", {})
    contract_assets = json.loads((ROOT / "manifests/raw_input_contract.json").read_text())["assets"]
    rows = []
    for name, value in sorted(assets.items()):
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (config.parent / path).resolve()
        registered = name in contract_assets
        # Do not open old outcome/selected-trade payloads, including their tails.
        role = "REGISTERED_RAW_INPUT" if registered else "NOT_ADMITTED_AS_PRODUCTION_INPUT"
        row = {"asset": name, "path": str(path), "exists": path.exists(), "role": role,
               "sha256": None, "hash_scope": "NOT_READ", "bytes": None}
        if path.is_file() and registered and name not in ("daily_tail", "atrdr_daily_2024_2025", "atrdr_daily_2026"):
            row.update(sha256=sha256(path), hash_scope="FULL_FILE", bytes=path.stat().st_size)
        elif path.is_dir():
            row["hash_scope"] = "DIRECTORY_CONTENT_NOT_HASHED_OR_CONSUMED"
        rows.append(row)
    lookup = {r["asset"]: r for r in rows}
    required = lookup.get("ifcgr_route_index")
    if required is None or not required["exists"]:
        coverage = {"status": "MISSING_IFCGR_ROUTE_INDEX", "rows": None}
    else:
        con = duckdb.connect(config={"threads": 2, "memory_limit": "1GB"})
        try:
            # Metadata/availability only; no investment outcomes are selected.
            result = con.execute("""
                SELECT count(*), min(causal_available_at), max(causal_available_at),
                  count(*) FILTER (WHERE causal_available_at = TIMESTAMP '2022-01-01'),
                  count(*) FILTER (WHERE causal_available_at > TIMESTAMP '2022-01-01'
                    AND causal_available_at < TIMESTAMP '2024-01-01')
                FROM read_parquet(?)
            """, [required["path"]]).fetchone()
        finally:
            con.close()
        coverage = dict(zip(("rows", "first_available", "last_available", "exact_boundary_rows", "after_boundary_through_2023_rows"), result))
        coverage["status"] = "RAW_FACT_COVERAGE_NOT_ESTABLISHED_2022_2023" if result[4] == 0 else "REQUIRES_COVERAGE_MANIFEST_VALIDATION"
    evidence = source_evidence()
    write_csv(out / "source_boundary_evidence.csv", evidence)
    write_json(out / "ifcgr_fact_coverage.json", coverage)
    manifest = {
        "evidence_stage": "SOURCE_AND_RAW_INPUT_INVENTORY_ONLY",
        "config_path": str(config.resolve()), "config_sha256": sha256(config),
        "start_head": receipt["start_head"], "policy_sha256": receipt["policy_sha256"],
        "implementation_hashes": receipt["frozen_implementation_hashes"],
        "five_strategy_entrypoint_hashes": {s: sha256(ROOT / "src/five_strategy_bundle/strategies" / (s.lower() + ".py")) for s in ("ATRDR", "MCB", "OGR", "IFCGR", "SMV6")},
        "inputs": rows, "ifcgr_fact_coverage": coverage,
        "periods": json.loads(POLICY.read_text())["periods"],
        "initial_capital": {"total": 4000000, "per_sleeve": 1000000, "p0_reconciled": False},
        "execution_contract": "contracts/shared_capital_policy_v1.json",
        "PIT_grades": {"IFCGR": "PIT-B", "SMV6": "LOCAL_PLATFORM_EQUIVALENCE_UNVERIFIED"},
        "all_raw_inputs_hash_verified": False,
        "raw_hash_limitation": "Only inventoried raw files were hashed. Large unconsumed input directories were not recursively hashed; post-2023 execution inputs were not read.",
    }
    write_json(HERE / "input_manifest.json", manifest)
    return manifest


def verify_inputs(manifest):
    checked = []
    for row in manifest["inputs"]:
        if row["sha256"] is not None:
            actual = sha256(row["path"])
            checked.append({"asset": row["asset"], "sha256": actual, "unchanged": actual == row["sha256"]})
    if not all(x["unchanged"] for x in checked):
        raise RuntimeError("Raw input changed during inventory")
    return checked


def report(out, status):
    coverage = json.loads((out / "ifcgr_fact_coverage.json").read_text())
    text = f"""# 五策略共享资金 V1：执行前阻塞证据

TASK_STATUS = PARTIAL_COMPLETE

当前交付是冻结合同、可执行原始输入审计和经过测试的政策算术；历史共享账户尚未实现。历史回放完成数为 **0/48**（每段 24 个）。没有 P0 对账通过记录，不能解释共享资金收益。

## 已证实的首个外部数据阻塞

配置中的 IFCGR 原始公告路由表共 {coverage.get('rows')} 行；可用时间从 {coverage.get('first_available')} 到 {coverage.get('last_available')}。
恰好处于 2022-01-01 边界的记录为 {coverage.get('exact_boundary_rows')} 行；此后至 2023 年末记录为 {coverage.get('after_boundary_through_2023_rows')} 行。
这不证明 2022–2023 没有风险公告，而是所给原始事实覆盖不足。不能将空事实匹配默认为发行人过滤通过。

源码也存在对应限制：OGR 信号母体与 V27 限定 2017–2021，V28/V28R1/V28R2 读取 2018–2021 分区；IFCGR 查询明确要求 causal_available_at < 2022-01-01。精确源码行见 output/source_boundary_evidence.csv。
现有 exit-risk 的 2022–2023 IFCGR 分支读取配置项 ifcgr_cy065_trades（fixed_trades.parquet）；该表没有在本任务中用作机会源。其是否完整覆盖未获资机会未被证明。
OGR 的 replay_portfolio 虽支持后续 account_start/account_end，但这只扩展账户窗口，不能扩展上游信号与事实覆盖。

## 独立的未完成工程

2018–2021 不受上述后段数据缺口直接阻塞，但尚未完成独立初始化的 P0、五个原生策略机会适配器、实际持仓回调、单一物理账户与虚拟份额核算及历史回放。
这里没有把这些工程欠项称为数据缺失，也没有把政策函数单测称为历史回放成功。恢复后应先完成 P0 对账，再推进该段场景。

## 已冻结的资本语义

四个活跃策略各 100 万，总额 400 万。股票原生账户归一化资金可线性缩放，保留 MAIN/CHINEXT 内部初始 50/50 和分数原生份额；SMV6 原生为 100 万、100 股整手。
这是一套原生执行语义的研究计价，尚未证明分数股票份额对应交易所可执行持仓。股票每侧 0.002 复合费用；SMV6 佣金 0.0002、每侧滑点 0.0008、50% 分钟量限制。所有退出为 NATIVE_ONLY。
HOME_BUDGET 仅取独立 P0；共享盈亏不进入其递归。政策哈希在任何收益回放之前冻结。

## 十二项研究结论的当前证据状态

1. STRUCTURAL_IDLE：NOT_ESTIMABLE，缺少完整原生未获资机会审计。
2. SEGMENTATION_IDLE：NOT_ESTIMABLE，不能由持仓低利用率推断。
3. 新增获资机会数：NOT_ESTIMABLE；未运行，不记为零。
4. 共享交易盈亏：NOT_ESTIMABLE。
5. P1 收益是否仅来自更高暴露：NOT_ESTIMABLE。
6. P2 Demand 拥挤控制：仅政策上限算术已测试，历史效果 NOT_ESTIMABLE。
7. P3 尾部风险/效率：状态机已测试，历史 frontier NOT_ESTIMABLE。
8. MCB 资本角色：EVIDENCE_INSUFFICIENT。
9. Gap 选择：EVIDENCE_INSUFFICIENT。
10. 合格共享政策：EVIDENCE_INSUFFICIENT，不能据此得出共享政策无效。
11. BASE_ENTITLEMENT_SHORTFALL：NOT_ESTIMABLE。
12. 最差回撤归因：NOT_ESTIMABLE。

两段的 CAGR、MaxDD、CVaR、平均暴露、获资率、capital-days、共享交易数/盈亏及相对 P0 变化均未计算；没有伪造零值或空结果表。scenario_run_status.csv 是执行状态清单，**不是 scenario_segment_results.csv 的替代品**。

## 继续执行所需

需要覆盖 2022–2023 决策前 120 天窗口的可追溯 IFCGR 原始公告路由、对应 SSE/SZSE 标题与 PIT-B 覆盖清单；并需要能够在本仓库研究目录内调用的完整 Gap 后段机会生成入口。
允许研究目录适配原生函数并不自动解决缺失公告历史；恢复后必须验证机会总体及 P0，再执行原定 48 个段场景。不得使用已接受交易补齐。

冻结源码/config/manifests/original_sources 字节在本次执行前后核对；已实际读取的独立原始文件进行前后 SHA256 核对。未读取的大型目录未声明全量哈希通过。
测试结果与具体覆盖范围见 output/focused_test_results.json（若已生成）。没有生产资金配置更改，没有 push；不把局部实现提交为已完成研究。
"""
    (HERE / "REPORT.md").write_text(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("inventory", "demand", "replay", "report", "all"), default="all")
    parser.add_argument("--period", choices=("2018_2021", "2022_2023", "all"), default="all")
    parser.add_argument("--gap", choices=("OGR", "IFCGR", "all"), default="all")
    parser.add_argument("--mcb-mode", choices=("independent", "confirmation_tag", "all"), default="all")
    parser.add_argument("--policy", choices=("P0", "P1", "P2", "P3_D4", "P3_D5", "P3_D6", "all"), default="all")
    parser.add_argument("--input-config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=HERE / "output")
    args = parser.parse_args(argv)
    out = args.output_root.resolve()
    if not out.is_relative_to(HERE):
        raise ValueError("This partial inventory runner writes only inside this research directory")
    out.mkdir(parents=True, exist_ok=True)
    receipt = freeze()
    policy = json.loads(POLICY.read_text())
    manifest = inventory(args.input_config, out, receipt)
    rows = []
    for scenario in scenario_grid(policy):
        if any(getattr(args, key) != "all" and getattr(args, key) != scenario[key] for key in ("period", "gap", "mcb_mode", "policy")):
            continue
        blocker = "INTEGRATED_NATIVE_P0_AND_SHARED_REPLAY_NOT_IMPLEMENTED"
        state = "NOT_RUN"
        if scenario["period"] == "2022_2023":
            blocker = "GAP_POST2021_PRODUCER_BOUNDARY"
            state = "BLOCKED"
            if scenario["gap"] == "IFCGR":
                blocker = manifest["ifcgr_fact_coverage"]["status"]
        rows.append({**scenario, "status": state, "first_reason": blocker, "historical_metrics": "NOT_ESTIMABLE"})
    write_csv(out / "scenario_run_status.csv", rows)
    status = {
        "TASK_STATUS": "PARTIAL_COMPLETE", "requested_stage": args.stage,
        "implemented_stages": ["inventory", "blocker_report"],
        "historical_scenarios_completed": 0, "preregistered_segment_scenarios": 48,
        "selected_segment_scenarios": len(rows), "P0_reconciled": False,
        "first_data_blocker": manifest["ifcgr_fact_coverage"],
        "separate_engineering_remaining": "Native independent P0 and integrated stateful opportunity/physical-account replay",
        "recommendation": "EVIDENCE_INSUFFICIENT",
        "frozen_sources_unchanged": verify_frozen_sources(receipt["frozen_implementation_hashes"]),
        "authorized_infrastructure_repairs": "contracts/validation_repair_receipt.json",
        "verified_consumed_input_files": verify_inputs(manifest),
        "all_raw_input_directories_verified": False,
        "policy_sha256": receipt["policy_sha256"],
    }
    if not status["frozen_sources_unchanged"]:
        raise RuntimeError("Frozen source drift")
    write_json(out / "run_status.json", status)
    report(out, status)
    print(json.dumps({"TASK_STATUS": status["TASK_STATUS"], "completed": 0, "planned": 48, "first_data_blocker": status["first_data_blocker"], "REPORT": str(HERE / "REPORT.md")}, default=str, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
