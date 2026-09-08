from pathlib import Path
import hashlib, json
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "research/opportunity_capital_v1"
CACHE = ROOT / "research/scaling_regime_v1/cache"
ACCOUNT = CACHE / "accounts/IFCGR__independent__NATIVE__FULL_BOOK_NORMALIZATION__2026-09-04"
OUT = ROOT / "research/capital_admission_v1/output"
OUT.mkdir(parents=True, exist_ok=True)
YEARS = list(range(2018, 2027))


def year_label(y):
    return "2026 YTD" if y == 2026 else str(y)


def atrdr_label(row):
    e = str(row.get("event_id", ""))
    if str(row.get("route", "")) == "BULL": return "ATRDR Bull"
    return "ATRDR Slow Bear" if "SLOW_SUPPLY_EXHAUSTION" in e else "ATRDR Fast Bear"


def canonical_tables():
    intents = {}
    for name in ["atrdr", "mcb", "ifcgr"]:
        d = pd.read_parquet(ACCOUNT / f"{name}_intents.parquet")
        d["decision_at"] = pd.to_datetime(d["decision_at"])
        if name == "atrdr": d["strategy_label"] = d.apply(atrdr_label, axis=1)
        else: d["strategy_label"] = name.upper()
        intents[name] = d
    fills = pd.read_parquet(ACCOUNT / "fills.parquet")
    fills["entry"] = pd.to_datetime(fills["entry"], errors="coerce")
    fills["exit"] = pd.to_datetime(fills["exit"], errors="coerce")
    fills["strategy_label"] = fills.apply(lambda r: atrdr_label(r) if r.strategy == "ATRDR" else str(r.strategy), axis=1)
    return intents, fills


def prior_opportunities():
    p = PARENT / "output/opportunity_master.csv.gz"
    d = pd.read_csv(p)
    d["decision_at"] = pd.to_datetime(d["decision_at"], errors="coerce")
    return d


def build_coverage():
    intents, fills = canonical_tables()
    old = prior_opportunities()
    labels = ["ATRDR Bull", "ATRDR Fast Bear", "ATRDR Slow Bear", "MCB", "OGR", "IFCGR", "SMV6"]
    rows = []
    for label in labels:
        for y in YEARS:
            lo, hi = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y+1}-01-01") if y < 2026 else pd.Timestamp("2026-09-05")
            if label.startswith("ATRDR"):
                ii = intents["atrdr"].loc[(intents["atrdr"].strategy_label == label) & intents["atrdr"].decision_at.ge(lo) & intents["atrdr"].decision_at.lt(hi)]
            elif label.lower() in intents:
                ii = intents[label.lower()].loc[intents[label.lower()].decision_at.ge(lo) & intents[label.lower()].decision_at.lt(hi)]
            else:
                ii = pd.DataFrame()
            ff = fills.loc[(fills.strategy_label == label) & fills.entry.ge(lo) & fills.entry.lt(hi)]
            oo = old.loc[(old.strategy == label) & old.decision_at.ge(lo) & old.decision_at.lt(hi)]
            # Exact post-2023 IFCGR pre-capital population is the Native producer's intent stream.
            if label == "IFCGR" and y >= 2024:
                pre = ii
                source = "canonical Native ifcgr_intents.parquet"
            elif label == "SMV6" and y >= 2024:
                pre = pd.DataFrame()
                source = "MISSING: registered SMV6 callback producer ends 2023"
            else:
                pre = oo
                source = "opportunity_capital_v1/opportunity_master.csv.gz"
            status = "PASS"
            if len(ii) or len(ff):
                status = "FAIL_MISSING_PRECAPITAL" if len(pre) == 0 else "PASS"
            rows.append({"strategy": label, "year": year_label(y), "pre_capital_opportunity_count": len(pre),
                         "native_entry_intent_count": len(ii), "native_fill_count": int((ff.side == "BUY").sum()),
                         "native_exit_count": int((ff.side == "SELL").sum()), "opportunity_source": source,
                         "native_source": str(ACCOUNT), "opportunity_first_date": pre.decision_at.min() if len(pre) else pd.NaT,
                         "opportunity_last_date": pre.decision_at.max() if len(pre) else pd.NaT, "coverage_status": status})
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "strategy_year_coverage_reconciliation.csv", index=False, date_format="%Y-%m-%d %H:%M:%S")
    return out


def source_trace():
    rows = [
        {"strategy": "SMV6", "producer": "research/shared_capital_v1/smv6_baseline.py load_bounded", "registered_input": "research/shared_capital_v1/cache/smv6/2018_2021 and 2022_2023", "coverage_end": "2023-12-31", "status": "SOURCE_COVERAGE_ENDS_2023", "evidence": "load_bounded hard-filters daily/minute/availability with trade_date < DATE 2024-01-01; precapital_intents exists only for 2018_2021 and 2022_2023"},
        {"strategy": "SMV6", "producer": "continuous Native account fills", "registered_input": str(ACCOUNT / "fills.parquet"), "coverage_end": "2026-09-04", "status": "NATIVE_ACTIVITY_PRESENT", "evidence": "SMV6 BUY/SELL rows exist after 2023, but fills are post-capital and cannot substitute for pre-capital callback intents"},
        {"strategy": "IFCGR", "producer": "continuous Native IFCGR adapter", "registered_input": str(ACCOUNT / "ifcgr_intents.parquet"), "coverage_end": "2026-08-03", "status": "PRECAPITAL_AVAILABLE", "evidence": "397 frozen Native intents; PIT-B qualification retained by upstream adapter"},
        {"strategy": "IFCGR", "producer": "continuous Native account fills", "registered_input": str(ACCOUNT / "fills.parquet"), "coverage_end": "2026-09-04", "status": "NATIVE_ACTIVITY_PRESENT", "evidence": "794 IFCGR fill rows in canonical account"},
    ]
    pd.DataFrame(rows).to_csv(OUT / "required_precapital_source_trace.csv", index=False)


def main():
    cov = build_coverage(); source_trace()
    fails = cov[cov.coverage_status == "FAIL_MISSING_PRECAPITAL"]
    decision = {"status": "BLOCKED_REQUIRED_PRECAPITAL_SOURCE_UNAVAILABLE" if len(fails) else "GATE_A_PASS", "failed_rows": int(len(fails)), "failed_strategy_years": fails[["strategy", "year"]].to_dict("records")}
    (OUT / "gate_decision.json").write_text(json.dumps(decision, indent=2, default=str), encoding="utf-8")
    (OUT / "input_manifest.json").write_text(json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in [PARENT / "REPORT.md", PARENT / "output/opportunity_master.csv.gz", ACCOUNT / "fills.parquet", ACCOUNT / "ifcgr_intents.parquet"] if p.exists()}, indent=2), encoding="utf-8")
    report(decision, cov)


def report(decision, cov):
    fails = cov[cov.coverage_status == "FAIL_MISSING_PRECAPITAL"]
    text = ["# Causal Capital Admission Closure V1", "", "## FINAL_DECISION", "", decision["status"], "", "## Gate A", "", f"覆盖矩阵包含 {len(cov)} 个 strategy-year 单元；失败 {len(fails)} 个。", "", "SMV6 在 2024、2025、2026 YTD 的连续 Native fills 存在，但已注册的 callback pre-capital producer 只到 2023。fills 是资金准入后的结果，不能倒推 legal opportunity population，因此不能把这些年份称为无信号，也不能继续 Gate B–H。", "", "IFCGR 的 canonical Native `ifcgr_intents.parquet` 覆盖到 2026-08-03，已纳入覆盖核对；其 PIT-B 来源等级沿用上游，不升级。", "", "## 阻断边界", "", "任务在 Gate A 按硬规则停止：`BLOCKED_REQUIRED_PRECAPITAL_SOURCE_UNAVAILABLE`。未生成 economic dedup、shadow lifecycle、capital conflict、priority map、account shared-cash replay 或 marginal capacity 结果，避免在输入不闭合时发表伪结论。", "", "详见 `output/strategy_year_coverage_reconciliation.csv` 与 `output/required_precapital_source_trace.csv`。"]
    (OUT.parent / "REPORT.md").write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__": main()
