#!/usr/bin/env python3
"""Fixed historical sleeve-NAV comparison for the five registered strategies."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "research/market_behavior_os_v2/STRATEGY_ALIAS_REGISTRY.json"
DEFAULT_OUT = ROOT / "research/five_strategy_marginal_value_v1/output"
AS_OF_DEFAULT = "2026-08-03"

# These are frozen output roots, not discovery paths.  The adapter deliberately
# reads only the compact accepted-trade and account-NAV ledgers.
SOURCES = {
    "ATRDR": {
        "trade": "/Volumes/quant/CY_quant_research/ashare_simple_regime_complementary_demand_router_v29/stage_b/accepted_trades.parquet",
        "nav": "/Volumes/quant/CY_quant_research/ashare_simple_regime_complementary_demand_router_v29/stage_b/portfolio_nav.parquet",
        "nav_col": "combined_nav", "cash_col": None, "gross_col": "utilization", "date_col": "trade_date",
        "stage": "2014-2025 historical plus 2026 diagnostic", "cost": "20bp/side included",
    },
    "MCB": {
        "trade": "/Volumes/quant/CY_quant_research/bull_cross_board_confirmation_v72/stage_b/combined_accepted.parquet",
        "nav": "/Volumes/quant/CY_quant_research/bull_cross_board_confirmation_v72/stage_b/combined_nav.parquet",
        "nav_col": "combined_nav", "cash_col": None, "gross_col": None, "date_col": "trade_date",
        "stage": "2014-2023 scientific; later diagnostic", "cost": "20bp/side included",
    },
    "OGR": {
        "trade": "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024/diagnostic_2022_2024/orderly_demand/portfolio_accepted.parquet",
        "nav": "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024/diagnostic_2022_2024/orderly_demand/portfolio_nav.parquet",
        "nav_col": "nav", "cash_col": "cash", "gross_col": "gross_exposure", "date_col": "trade_date",
        "stage": "2022-2024 consumed dependent validation", "cost": "20bp/side included",
    },
    "IFCGR": {
        "trade": "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy065_through_20260904_v1/stage_b/lane/portfolio_accepted.parquet",
        "nav": "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_v29r2_issuer_fact_rollforward_cy065_through_20260904_v1/stage_b/lane/portfolio_nav.parquet",
        "nav_col": "nav", "cash_col": "cash", "gross_col": "gross_exposure", "date_col": "trade_date",
        "stage": "2022-2024 dependent validation; 2025-26 diagnostic", "cost": "20bp/side included",
    },
    "SMV6": {
        "trade": "/Users/linmei/Documents/CY-supermind-v6/research/supermind_v6/output/v6_hybrid_longest_replay_events.parquet",
        "nav": "/Users/linmei/Documents/CY-supermind-v6/research/supermind_v6/output/v6_hybrid_longest_daily_equity.parquet",
        "nav_col": "nav", "cash_col": "cash", "gross_col": "gross_exposure", "date_col": "trade_date",
        "stage": "shadow replay only", "cost": "zero fees/slippage; not comparable net return",
    },
}


def read_parquet(path: str) -> pd.DataFrame:
    """DuckDB avoids a local PyArrow reader incompatibility with old ledgers."""
    return duckdb.sql("select * from read_parquet(?)", params=[path]).df()


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metric(nav: pd.DataFrame) -> dict[str, float | int | None]:
    nav = nav.sort_values("date").drop_duplicates("date").copy()
    if len(nav) < 2:
        return {key: None for key in ("total_return", "cagr", "max_drawdown", "sharpe", "tail5", "worst_year", "avg_utilization")} | {"days": len(nav)}
    ret = nav.nav.pct_change().dropna()
    years = (nav.date.iloc[-1] - nav.date.iloc[0]).days / 365.25
    total = nav.nav.iloc[-1] / nav.nav.iloc[0] - 1
    drawdown = nav.nav / nav.nav.cummax() - 1
    yearly = nav.set_index("date").nav.resample("YE").last().pct_change().dropna()
    return {
        "days": len(nav), "total_return": total,
        "cagr": (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else None,
        "max_drawdown": drawdown.min(),
        "sharpe": math.sqrt(252) * ret.mean() / ret.std(ddof=1) if len(ret) > 1 and ret.std(ddof=1) else None,
        "tail5": ret.nsmallest(max(1, math.ceil(len(ret) * .05))).mean(),
        "worst_year": yearly.min() if len(yearly) else None,
        "avg_utilization": nav.utilization.mean() if "utilization" in nav else None,
    }


def load_nav(name: str, as_of: pd.Timestamp) -> pd.DataFrame:
    spec = SOURCES[name]
    data = read_parquet(spec["nav"])
    out = pd.DataFrame({"date": pd.to_datetime(data[spec["date_col"]]), "nav": data[spec["nav_col"]]})
    if spec["cash_col"] and spec["cash_col"] in data:
        out["cash"] = data[spec["cash_col"]]
    if spec["gross_col"] and spec["gross_col"] in data:
        out["utilization"] = data[spec["gross_col"]]
    elif "utilization" in data:
        out["utilization"] = data.utilization
    if "active_positions" in data:
        out["active_positions"] = data.active_positions
    elif "position_count" in data:
        out["active_positions"] = data.position_count
    out = out[(out.date <= as_of) & out.nav.notna()].sort_values("date")
    # Gap-repair ledgers emit one 50/50 sleeve row per board.  Aggregate the
    # pre-existing account rows; selecting one duplicate would halve NAV.
    if out.date.duplicated().any():
        sums = [c for c in ("nav", "cash", "utilization", "active_positions") if c in out]
        out = out.groupby("date", as_index=False)[sums].sum()
    return out


def load_trades(name: str, start: pd.Timestamp, end: pd.Timestamp, as_of: pd.Timestamp) -> pd.DataFrame:
    raw = read_parquet(SOURCES[name]["trade"])
    if name == "SMV6":
        buys = raw[raw.event_type == "BUY_FILLED"].copy()
        return pd.DataFrame({"strategy": name, "event_id": buys.index.astype(str), "symbol": buys.symbol,
            "signal_date": pd.to_datetime(buys.signal_date), "entry_date": pd.to_datetime(buys.trade_date),
            "exit_date": pd.NaT, "net_return": np.nan, "holding_sessions": np.nan, "route": "ETF", "completed": False})
    event = "event_id" if "event_id" in raw else "gap_id"
    out = pd.DataFrame({"strategy": name, "event_id": raw[event].astype(str), "symbol": raw.symbol.astype(str),
        "signal_date": pd.to_datetime(raw.signal_date), "entry_date": pd.to_datetime(raw.entry_date),
        "exit_date": pd.to_datetime(raw.exit_date), "net_return": raw.net_return,
        "holding_sessions": raw.holding_sessions, "route": raw["lane"] if "lane" in raw else "NA",
        "completed": raw["completed"] if "completed" in raw else raw.status.eq("COMPLETED")})
    out = out[(out.signal_date >= start) & (out.signal_date <= end)].copy()
    # Right-censored outcomes are intentionally not used in trade-return statistics.
    out.loc[out.exit_date > as_of, ["net_return", "holding_sessions"]] = np.nan
    out["mature"] = out.exit_date.le(as_of) & out.completed
    return out


def event_rows(label: str, left: pd.DataFrame, right: pd.DataFrame) -> list[dict]:
    keys = ["symbol", "signal_date"]
    l = left.drop_duplicates(keys); r = right.drop_duplicates(keys)
    merged = l.merge(r, on=keys, how="outer", suffixes=("_left", "_right"), indicator=True)
    rows = []
    for side, title in [("both", "common"), ("left_only", "left_only"), ("right_only", "right_only")]:
        part = merged[merged._merge == side]
        values = pd.concat([part.get("net_return_left", pd.Series(dtype=float)), part.get("net_return_right", pd.Series(dtype=float))]) if side == "both" else part[f"net_return_{'left' if side == 'left_only' else 'right'}"]
        rows.append({"comparison": label, "match_method": "symbol+signal_date exact key (not complete economic-event identity)", "group": title,
            "events": len(part), "signal_dates": part.signal_date.nunique(), "mature_return_mean": values.dropna().mean(), "mature_return_median": values.dropna().median(), "mature_n": values.notna().sum()})
    return rows


def risk_rows(navs: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    names = list(navs)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            joined = navs[a].merge(navs[b], on="date", suffixes=("_a", "_b"))
            ra, rb = joined.nav_a.pct_change(), joined.nav_b.pct_change()
            valid = pd.DataFrame({"a": ra, "b": rb}).dropna()
            worst_a = valid.a <= valid.a.quantile(.05) if len(valid) >= 20 else pd.Series(False, index=valid.index)
            worst_b = valid.b <= valid.b.quantile(.05) if len(valid) >= 20 else pd.Series(False, index=valid.index)
            # Missing position counts are unknown, not evidence of being flat.
            held = None if "active_positions_a" not in joined or "active_positions_b" not in joined else (
                (joined.active_positions_a > 0) & (joined.active_positions_b > 0)
            )
            rows.append({"left": a, "right": b, "common_days": len(valid), "daily_return_corr": valid.a.corr(valid.b) if len(valid) > 1 else None,
                "both_held_days": int(held.sum()) if held is not None else None,
                "both_held_corr": valid.loc[held.iloc[1:].to_numpy()].a.corr(valid.loc[held.iloc[1:].to_numpy()].b) if held is not None and held.sum() > 2 else None,
                "right_mean_on_left_tail": valid.loc[worst_a, "b"].mean(), "right_loss_rate_on_left_tail": (valid.loc[worst_a, "b"] < 0).mean(),
                "left_mean_on_right_tail": valid.loc[worst_b, "a"].mean(), "left_loss_rate_on_right_tail": (valid.loc[worst_b, "a"] < 0).mean()})
    return rows


def composite(navs: dict[str, pd.DataFrame], members: list[str], window_members: list[str] | None = None) -> pd.DataFrame:
    window_members = window_members or members
    common = None
    for name in window_members:
        x = navs[name][["date", "nav"]].rename(columns={"nav": name})
        common = x if common is None else common.merge(x, on="date", how="inner")
    if common is None or common.empty:
        return pd.DataFrame(columns=["date", "nav", "utilization"])
    common = common.sort_values("date")
    q = common[window_members].div(common[window_members].iloc[0])
    common["nav"] = .25 * q[members].sum(axis=1) + .25 * (4 - len(members))
    common["utilization"] = np.nan
    return common[["date", "nav", "utilization"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-start", default="2018-01-01"); parser.add_argument("--signal-end", default=AS_OF_DEFAULT)
    parser.add_argument("--as-of", default=AS_OF_DEFAULT); parser.add_argument("--output-root", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stage", choices=("inventory", "analysis", "report", "all"), default="all")
    args = parser.parse_args(); out = args.output_root; out.mkdir(parents=True, exist_ok=True)
    start, end, as_of = map(pd.Timestamp, (args.signal_start, args.signal_end, args.as_of))
    registry = json.loads(REGISTRY.read_text())
    selected = {s["short_code"].split("-")[0]: s for s in registry["strategies"]}
    navs, trades, manifest = {}, {}, {"as_of": str(as_of.date()), "strategies": {}, "smv6_accounting_status": "SMV6_ACCOUNTING_BLOCKED"}
    for name, spec in SOURCES.items():
        paths = {k: spec[k] for k in ("trade", "nav")}
        exists = all(Path(p).is_file() for p in paths.values())
        if exists:
            navs[name], trades[name] = load_nav(name, as_of), load_trades(name, start, end, as_of)
        identity = next((s for s in registry["strategies"] if s["short_code"].split("-")[0] == name), None)
        manifest["strategies"][name] = {"registered_id": identity["strategy_id"] if identity else None, "contract_or_identity": identity["identity"] if identity else None,
            "paths": paths, "sha256": {k: sha256(v) for k, v in paths.items()} if exists else None, "available": exists,
            "coverage": [str(navs[name].date.min().date()), str(navs[name].date.max().date())] if exists and len(navs[name]) else None,
            "evidence_stage": spec["stage"], "cost_basis": spec["cost"],
            "semantic_preflight": {"ECONOMIC_SEQUENCE": "frozen contract", "CAUSAL_BACKGROUND": "frozen contract", "STATE_VARIABLES": "see contract", "EVENT_FORMATION_TIME": "completed signal", "CONFIRMATION_TRIGGER": "strategy-specific", "ENTRY_TIME": "next legal entry", "OUTCOME_START_TIME": "entry", "POSSIBLE_SEMANTIC_AMBIGUITIES": "no new interpretation", "CHOSEN_TIME_ANCHORS": "signal_date/entry_date/as_of"}}
    smv = navs["SMV6"]
    negative = smv[smv.cash < 0] if "cash" in smv else pd.DataFrame()
    manifest["smv6_accounting"] = {"negative_cash_days": len(negative), "minimum_cash": negative.cash.min() if len(negative) else 0,
        "maximum_gross_exposure": smv.utilization.max() if "utilization" in smv else None,
        "reason": "existing shadow ledger permits negative cash / gross exposure above NAV; no state replay attempted"}
    (out / "input_manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
    summaries = []
    for name in SOURCES:
        t, n = trades[name], navs[name]
        mature = t[t.mature] if "mature" in t else t.iloc[0:0]
        row = {"strategy": name, "trades": len(t), "mature_trades": len(mature), "independent_signal_dates": t.signal_date.nunique(),
            "trade_mean": mature.net_return.mean(), "trade_median": mature.net_return.median(), "win_rate": (mature.net_return > 0).mean(), "holding_sessions": mature.holding_sessions.mean(), **metric(n), "coverage_start": n.date.min(), "coverage_end": n.date.max(), "account_eligible_for_main_composite": name != "SMV6"}
        summaries.append(row)
    pd.DataFrame(summaries).to_csv(out / "strategy_summary.csv", index=False)
    pairwise = []
    pairwise += event_rows("A ATRDR_BULL_vs_MCB", trades["ATRDR"][trades["ATRDR"].route.str.contains("BULL")], trades["MCB"])
    pairwise += event_rows("B OGR_vs_IFCGR", trades["OGR"], trades["IFCGR"])
    for route in ("BEAR_WORSENING_FAST_CAPITULATION", "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"):
        pairwise += event_rows("C " + route + "_vs_OGR", trades["ATRDR"][trades["ATRDR"].route.eq(route)], trades["OGR"])
    pd.DataFrame(pairwise).to_csv(out / "pairwise_increment.csv", index=False)
    pd.DataFrame(risk_rows(navs)).to_csv(out / "overlap_and_risk.csv", index=False)
    # SMV6 is excluded from eligible members: its 25% is cash, exactly as required.
    portfolios = []
    for label, members in (("A_REDUCED_SMV6_CASH", ["ATRDR", "MCB", "OGR"]), ("B_REDUCED_SMV6_CASH", ["ATRDR", "MCB", "IFCGR"])):
        base = composite(navs, members); base.to_csv(out / f"{label}_nav.csv", index=False)
        portfolios.append({"portfolio": label, "type": "HISTORICAL_SLEEVE_NAV_COMPOSITE_REDUCED_SMV6_CASH", "members": "+".join(members) + "+25% cash", **metric(base)})
        for removed in members:
            # Preserve the original full-composite dates: deleting a sleeve must
            # not silently extend its history or change the comparison window.
            reduced = composite(navs, [x for x in members if x != removed], window_members=members)
            portfolios.append({"portfolio": label + "_WITHOUT_" + removed + "_CASH", "type": "fixed initial 25% sleeve replaced by cash", "members": "+".join(x for x in members if x != removed) + "+cash", **metric(reduced)})
    pd.DataFrame(portfolios).to_csv(out / "portfolio_comparison.csv", index=False)
    report = f"""# 五策略边际价值与资金组合研究 V1\n\n截至 {as_of.date()}；所有组合均为 `HISTORICAL_SLEEVE_NAV_COMPOSITE`，不是统一订单级回测。\n\n## 核算结论\n\nSMV6 shadow 账户有 {len(negative)} 个负现金日，最低现金 {negative.cash.min() if len(negative) else 0:.6f}，且最大 gross exposure {smv.utilization.max():.6f}。现有资料没有可安全复用的状态回放以局部重放成交，故 `SMV6_ACCOUNTING_BLOCKED`；旧 shadow 曲线不进入主组合。A/B 仅给出 SMV6 的 25% 留现金的缩减版本，SMV6 边际贡献 `NOT_ESTIMABLE`。\n\n## 直接回答\n\n1. ATRDR 牛市路线和 MCB 的精确键匹配结果见 `pairwise_increment.csv`；它只识别同证券同信号日，不能声称穷尽经济事件。MCB 是 V65 的严格跨板确认质量配置，ATRDR 牛市路线不是其父子替代。\n2. OGR/IFCGR 的保留、否决机会仅按可读取 2022--2024 账本键匹配描述；没有将父策略价格倒用于子策略。\n3. ATRDR 两条熊市路线与 OGR 的共同日期/事件同样只以键匹配报告；共同亏损以 `overlap_and_risk.csv` 的日账户指标为准。\n4. SMV6 账户不可用于无杠杆净收益主比较，不能据此主张改善股票策略困难阶段。\n5. 每个已合格子账户相对留现金的固定权重删除对照在 `portfolio_comparison.csv`；SMV6 为 `NOT_ESTIMABLE`，非零贡献。\n\n成本模型各自冻结且不完全一致（SMV6 为零费率 shadow），因此未混入 SMV6，也未做额外 20bp 压力（股票逐日成交额口径不统一）。最优先下一步：在不改变 SMV6 状态机的条件下，取得能重放候选、持仓和现金约束的原生执行账本。\n"""
    (out / "REPORT.md").write_text(report)


if __name__ == "__main__":
    main()
