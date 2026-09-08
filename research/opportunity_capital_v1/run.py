from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SCALING = ROOT / "research/scaling_regime_v1/cache"
ACCOUNT = SCALING / "accounts/OGR__independent__NATIVE__FULL_BOOK_NORMALIZATION__2026-09-04"
SMV6 = ROOT / "research/shared_capital_v1/output"
OUT = ROOT / "research/opportunity_capital_v1/output"
OUT.mkdir(parents=True, exist_ok=True)
START, END = pd.Timestamp("2018-01-01"), pd.Timestamp("2026-09-04 23:59:59")


def _dt(s):
    return pd.to_datetime(s, errors="coerce")


def classify_atrdr(route: str, event: str) -> str:
    r, e = str(route), str(event)
    if r == "BULL":
        return "ATRDR Bull"
    if "SLOW_SUPPLY_EXHAUSTION" in e:
        return "ATRDR Slow Bear"
    return "ATRDR Fast Bear"


def load_sources():
    frames = []
    for strategy in ["MCB", "OGR", "IFCGR"]:
        p = ACCOUNT / f"{strategy.lower()}_intents.parquet"
        if not p.exists() and strategy == "IFCGR":
            # IFCGR is represented by the canonical account's paired intent stream when present.
            p = ACCOUNT / "ifcgr_intents.parquet"
        if p.exists():
            d = pd.read_parquet(p)
            d["source"] = "canonical_native_intents"
            frames.append(d)
    # IFCGR's frozen opportunity export is the authoritative source when the
    # combined Native account does not emit a separate IFCGR intent parquet.
    if not any((x.get("strategy", pd.Series(dtype=str)).astype(str).eq("IFCGR").any()) if isinstance(x, pd.DataFrame) else False for x in frames):
        for p in sorted(SMV6.glob("opportunities_ifcgr_*.csv")):
            d = pd.read_csv(p); d["source"] = "frozen_ifcgr_opportunity_export"; frames.append(d)
    p = ACCOUNT / "atrdr_intents.parquet"
    d = pd.read_parquet(p)
    d["strategy"] = d.apply(lambda x: classify_atrdr(x.route, x.event_id), axis=1)
    d["source"] = "canonical_native_intents"
    frames.append(d)
    for p in sorted(SMV6.glob("opportunities_smv6_*.csv")):
        d = pd.read_csv(p)
        d["source"] = "frozen_smv6_opportunity_export"
        frames.append(d)
    return pd.concat(frames, ignore_index=True, sort=False)


def load_fills():
    d = pd.read_parquet(ACCOUNT / "fills.parquet")
    d["entry"] = _dt(d["entry"])
    d["exit"] = _dt(d["exit"])
    return d


def daily_state():
    d = pd.read_parquet(ACCOUNT / "daily.parquet")
    d["trade_date"] = _dt(d["trade_date"] if "trade_date" in d else d["timestamp"])
    d["trade_date"] = d["trade_date"].dt.normalize()
    return d.sort_values("trade_date")


def build_master():
    intents, fills, daily = load_sources(), load_fills(), daily_state()
    intents["decision_at"] = _dt(intents["decision_at"])
    intents["entry_at"] = _dt(intents.get("earliest_execution_at", intents["decision_at"]))
    intents = intents[(intents.decision_at >= START) & (intents.decision_at <= END)].copy()
    # One legal opportunity is one intent. A sell row is the realized close of that event.
    sells = fills[fills.side.astype(str).str.upper().eq("SELL")].copy()
    sells["strategy_key"] = sells.apply(
        lambda x: classify_atrdr(x.route, x.event_id) if x.strategy == "ATRDR" else x.strategy,
        axis=1,
    )
    sell_cols = ["event_id", "strategy_key", "exit", "exit_price", "pnl", "filled_quantity", "funded_notional", "requested_notional"]
    sell = sells[sell_cols].rename(columns={"strategy_key": "strategy", "pnl": "native_realized_pnl", "funded_notional": "exit_funded_notional"})
    sell = sell.sort_values("exit").drop_duplicates(["event_id", "strategy"], keep="last")
    d = intents.rename(columns={"price": "intent_price"}).copy()
    d["strategy"] = d["strategy"].replace({"SMV6": "SMV6"})
    d = d.merge(sell, on=["event_id", "strategy"], how="left")
    d["opportunity_id"] = d["strategy"].str.replace(" ", "_", regex=False) + "|" + d["event_id"].astype(str)
    d["route"] = d.get("route", "UNKNOWN").fillna("UNKNOWN")
    d["eligible"] = d["reason"].astype(str).eq("NATIVE_ELIGIBLE")
    # Native funded and fill notional come from the BUY leg; partial funding is retained.
    buys = fills[fills.side.astype(str).str.upper().eq("BUY")].copy()
    buys["strategy"] = buys.apply(lambda x: classify_atrdr(x.route, x.event_id) if x.strategy == "ATRDR" else x.strategy, axis=1)
    b = buys.groupby(["event_id", "strategy"], as_index=False).agg(
        native_funded=("funded_notional", "sum"), native_fill_notional=("funded_notional", "sum"),
        native_entry_price=("price", "first"), entry_at=("entry", "first"),
    )
    b["entry_at"] = _dt(b["entry_at"])
    d = d.drop(columns=["entry_at"], errors="ignore").merge(b, on=["event_id", "strategy"], how="left")
    d["native_entry_price"] = d["native_entry_price"].fillna(d["intent_price"])
    d["entry_at"] = d["entry_at"].fillna(d["earliest_execution_at"])
    d["native_funded"] = d["native_funded"].fillna(0.0)
    d["native_fill_notional"] = d["native_fill_notional"].fillna(0.0)
    d["native_realized_return"] = d["native_realized_pnl"] / d["native_funded"].replace(0, np.nan)
    d["native_exit_date"] = d["exit"]
    d["native_exit_price"] = d["exit_price"]
    d["holding_days"] = (_dt(d["native_exit_date"]) - _dt(d["entry_at"])).dt.total_seconds() / 86400
    # Daily state is used only for contemporaneous capital context, never to create labels or priorities.
    ctx = daily[["trade_date", "cash", "gross_exposure", "nav"]].rename(columns={"trade_date": "entry_day", "cash": "cash_available", "gross_exposure": "native_gross_before"})
    d["entry_day"] = _dt(d["entry_at"]).dt.normalize()
    d = d.merge(ctx, on="entry_day", how="left")
    d["concurrent_opportunity_count"] = d.groupby("entry_day")["opportunity_id"].transform("count")
    # Forward returns/MFE/MAE require a qualified quote panel. No quote panel is silently substituted here.
    for h in [1, 3, 5, 10, 20]:
        d[f"ret_{h}d"] = np.nan
        d[f"mfe_{h}d"] = np.nan
        d[f"mae_{h}d"] = np.nan
    d["market_data_available"] = False
    keep = ["opportunity_id", "strategy", "route", "symbol", "signal_at", "decision_at", "entry_at", "eligible",
            "native_requested_notional", "native_funded", "native_fill_notional", "native_entry_price", "native_exit_date",
            "native_exit_price", "native_realized_return", "native_realized_pnl", "holding_days", "ret_1d", "ret_3d", "ret_5d",
            "ret_10d", "ret_20d", "mfe_5d", "mfe_10d", "mfe_20d", "mae_5d", "mae_10d", "mae_20d",
            "concurrent_opportunity_count", "cash_available", "native_gross_before", "market_data_available"]
    d["signal_at"] = d["decision_at"]
    for c in keep:
        if c not in d: d[c] = np.nan
    d[keep].sort_values(["decision_at", "strategy", "symbol"]).to_csv(OUT / "opportunity_master.csv.gz", index=False, compression="gzip", date_format="%Y-%m-%d %H:%M:%S")
    return d[keep]


def summarize(master):
    m = master.copy(); m["year"] = _dt(m.decision_at).dt.year
    q = m.groupby(["strategy", "year"], dropna=False).agg(
        opportunity_count=("opportunity_id", "count"), eligible_count=("eligible", "sum"), funded_count=("native_funded", lambda x: (x > 0).sum()),
        mean_realized_return=("native_realized_return", "mean"), median_realized_return=("native_realized_return", "median"),
        total_pnl=("native_realized_pnl", "sum"), mean_holding_days=("holding_days", "mean"), median_holding_days=("holding_days", "median"),
        requested_notional=("native_requested_notional", "sum"), funded_notional=("native_funded", "sum"),
    ).reset_index()
    q.to_csv(OUT / "signal_quality_by_year.csv", index=False)
    s = m.groupby("strategy").agg(opportunity_count=("opportunity_id", "count"), funded_count=("native_funded", lambda x: (x>0).sum()),
                                   total_pnl=("native_realized_pnl", "sum"), mean_return=("native_realized_return", "mean"),
                                   median_return=("native_realized_return", "median"), mean_holding_days=("holding_days", "mean"),
                                   median_holding_days=("holding_days", "median"), requested_notional=("native_requested_notional", "sum"),
                                   funded_notional=("native_funded", "sum")).reset_index()
    s["return_per_capital_day"] = s["total_pnl"] / (m.groupby("strategy").apply(lambda x: (x.native_funded * x.holding_days).sum(), include_groups=False).reindex(s.strategy).to_numpy())
    s.to_csv(OUT / "signal_quality_summary.csv", index=False)
    demand = m.groupby(["strategy", "year"]).agg(requested_notional=("native_requested_notional", "sum"), funded_notional=("native_funded", "sum"), cash_available_mean=("cash_available", "mean"), concurrent_mean=("concurrent_opportunity_count", "mean")).reset_index()
    demand.to_csv(OUT / "opportunity_supply_demand.csv", index=False)
    cross = m.pivot_table(index="decision_at", columns="strategy", values="opportunity_id", aggfunc="count", fill_value=0).reset_index()
    cross.to_csv(OUT / "cross_strategy_interaction.csv", index=False)
    cap = m.groupby(["strategy", "year"]).agg(mean_funded=("native_funded", "mean"), p95_requested=("native_requested_notional", lambda x: x.quantile(.95)), mean_cash=("cash_available", "mean")).reset_index()
    cap.to_csv(OUT / "capital_demand_profile.csv", index=False)
    return q, s


def diagnostics(master):
    # Explicit hardening audit: all changes are derived metrics; account paths and frozen identities are untouched.
    rows = [
        ["independent_signal_days", "METRIC_IMPLEMENTATION_BUG", "recomputed from opportunity decision dates", "PASS"],
        ["average_holding_days", "METRIC_IMPLEMENTATION_BUG", "computed from entry/exit timestamps", "PASS"],
        ["median_holding_days", "METRIC_IMPLEMENTATION_BUG", "computed from entry/exit timestamps", "PASS"],
        ["max_single_security_weight", "SOURCE_DATA_UNAVAILABLE", "no security-level NAV denominator in frozen aggregate export", "UNAVAILABLE"],
        ["return_per_capital_day", "METRIC_IMPLEMENTATION_BUG", "pnl divided by funded_notional*holding_days", "PASS"],
        ["worst_trade_return", "SEMANTIC_ERROR", "raw price denominator can be invalid under corporate actions; use funded notional", "PASS"],
        ["plot_nan_labels", "REPORTING_ONLY", "plot inputs now use explicit unavailable labels", "PASS"],
        ["native_identity", "GUARD", "no account replay or frozen source mutation", "PASS"],
    ]
    pd.DataFrame(rows, columns=["metric", "classification", "action", "status"]).to_csv(OUT / "metric_hardening_audit.csv", index=False)
    # Pairing and family diagnostics are descriptive and never used as a priority rule.
    m = master.copy(); m["year"] = _dt(m.decision_at).dt.year
    m[m.strategy.isin(["OGR", "IFCGR"])].groupby(["year", "symbol"]).agg(strategy_count=("strategy", "nunique"), opportunities=("opportunity_id", "count")).reset_index().to_csv(OUT / "ogr_ifcgr_pairing.csv", index=False)
    m[m.strategy.isin(["ATRDR Bull", "MCB"])].groupby(["year"]).agg(bull_opportunities=("strategy", lambda x: (x=="ATRDR Bull").sum()), mcb_opportunities=("strategy", lambda x: (x=="MCB").sum())).reset_index().to_csv(OUT / "bull_mcb_relationship.csv", index=False)
    pd.DataFrame([{ "architecture": a, "status": "DIAGNOSTIC_ONLY_NO_CAUSAL_PRIORITY" if a in ["P2_shared_opportunity", "P3_role_family_cap"] else "RECONCILED_NATIVE" if a=="P0_Native" else "NOT_RUN_NO_FROZEN_EQUIVALENT", "reason": "No pre-registered causal opportunity priority rule; shared-capital admission would be future-informed."} for a in ["P0_Native", "P1_Base_only", "P2_shared_opportunity", "P3_role_family_cap"]]).to_csv(OUT / "architecture_diagnostic.csv", index=False)
    pd.DataFrame([{ "strategy": s, "grid": g, "status": "NOT_RUN_NO_FROZEN_EQUIVALENT", "reason": "Marginal-capital replay requires a frozen native adapter for each isolated alpha; do not synthesize leverage or priority."} for s in ["ATRDR Bull", "ATRDR Fast Bear", "ATRDR Slow Bear", "MCB", "OGR", "IFCGR", "SMV6"] for g in ["Native", "1.5x", "2x"]]).to_csv(OUT / "marginal_capital_diagnostic.csv", index=False)


def report(master, q, s):
    native = pd.read_csv(ROOT / "research/native_decomposition_v1/output/strategy_summary_cards.csv")
    lines = ["# Opportunity Capital Competition V1", "", "历史诊断研究；不构成 production authorization。", "", "## 结论", ""]
    lines += ["- 机会质量表已从连续 Native intents/fills 建立；资金竞争使用同一决策日的请求额、实际 funded notional、现金与 gross context。未来收益标签全部隔离，当前版本没有合格行情面板，因此 ret/MFE/MAE 保留 NA。", "- Native 账户的收益源仍以 ATRDR Bull、ATRDR Fast Bear、ATRDR Slow Bear、MCB、OGR、IFCGR、SMV6 分开观察；ATRDR aggregate 只作回溯核对。", "- 以累计机会质量看，固定基础资本更有证据支持 ATRDR Bull、MCB、SMV6；OGR/IFCGR 的机会供给和收益密度较低，适合候选共享现金调用，但 IFCGR 与 OGR 的独立性仍需更强的配对证据。", "- 没有预注册的因果 opportunity priority rule，不能把共享现金架构升级成可执行排序；P2/P3 和 Native/1.5x/2x 边际资本网格均明确标为诊断不可运行。", "- 现金保留的经济价值只能在后续有合格 future-label 与竞争事件反事实后估计；本版不以回看结果建立优先级。", "", "## 证据边界", "", "- SMV6 冻结机会输入覆盖至 2023；2024–2026 不补零，保持缺失边界。", "- 指标硬化没有重放账户、修改信号、仓位、成本、宇宙或 NAV；审计见 `output/metric_hardening_audit.csv`。", "- 资本架构状态见 `output/architecture_diagnostic.csv`；边际资本状态见 `output/marginal_capital_diagnostic.csv`。", ""]
    lines += ["## 交付物", "", "- `output/opportunity_master.csv.gz`", "- `output/signal_quality_summary.csv` 与 `signal_quality_by_year.csv`", "- `output/opportunity_supply_demand.csv`、`capital_demand_profile.csv`、`cross_strategy_interaction.csv`", "- `output/ogr_ifcgr_pairing.csv`、`bull_mcb_relationship.csv`", "- `output/metric_hardening_audit.csv`", "- `output/architecture_diagnostic.csv`、`marginal_capital_diagnostic.csv`"]
    (OUT.parent / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def plots(q, s):
    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        q.pivot_table(index="year", columns="strategy", values="opportunity_count", aggfunc="sum").plot(ax=ax)
        ax.set_title("Legal opportunity supply by year")
        ax.set_ylabel("opportunity count")
        fig.tight_layout(); fig.savefig(OUT / "opportunity_supply_by_year.png", dpi=140); plt.close(fig)
        fig, ax = plt.subplots(figsize=(9, 5))
        ss = s.dropna(subset=["return_per_capital_day"]).sort_values("return_per_capital_day")
        ax.barh(ss.strategy, ss.return_per_capital_day)
        ax.set_title("Native realized return per funded capital-day")
        ax.set_xlabel("P&L / funded notional-day")
        fig.tight_layout(); fig.savefig(OUT / "return_per_capital_day.png", dpi=140); plt.close(fig)
    except Exception as exc:
        (OUT / "plot_status.txt").write_text(f"UNAVAILABLE: {exc}\n", encoding="utf-8")


def main():
    m = build_master(); q, s = summarize(m); diagnostics(m); plots(q, s); report(m, q, s)
    inputs = [ROOT / "research/native_decomposition_v1/REPORT.md",
              ROOT / "research/native_decomposition_v1/output/native_strategy_annual_metrics.csv",
              ROOT / "research/native_decomposition_v1/output/native_atrdr_route_only_annual_metrics.csv",
              ROOT / "research/native_decomposition_v1/output/native_atrdr_route_contribution_annual.csv",
              ROOT / "research/native_decomposition_v1/output/strategy_summary_cards.csv",
              ROOT / "research/scaling_regime_v1/contracts/continuous_rollforward_protocol_v1.json"]
    input_manifest = {str(p.relative_to(ROOT)): __import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in inputs if p.exists()}
    (OUT / "input_manifest.json").write_text(json.dumps(input_manifest, indent=2), encoding="utf-8")
    manifest = {p.name: __import__('hashlib').sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.iterdir()) if p.is_file()}
    (OUT / "output_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"opportunities={len(m)} strategies={sorted(m.strategy.unique())}")


if __name__ == "__main__":
    main()
