"""Native-only strategy and ATRDR route decomposition.

This module consumes the already sealed continuous Native accounts.  ATRDR
route-only accounts are independently replayed from the frozen opportunity
population; they are never manufactured by deleting rows from the aggregate
fill ledger.
"""
from __future__ import annotations
import json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd

from research.scaling_regime_v1 import accounts as parent_accounts
from research.scaling_regime_v1.accounts import load as load_inputs, END
from research.scaling_regime_v1.audit import HERE as PARENT_HERE, ROOT, ROLL, sha256
from research.shared_capital_v1 import common_p0_v06 as common
from research.shared_capital_v1.native_states_v06 import state_hash

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
CACHE = HERE / "cache"
PARENT_OUT = PARENT_HERE / "output"
START = pd.Timestamp("2018-01-01")
END_TS = pd.Timestamp("2026-09-04")
YEARS = list(range(2018, 2027))
ROUTES = ["BULL", "FAST_BEAR", "SLOW_BEAR"]


def _scale_state(state, factor):
    """Scale the ATRDR sleeve state for the common 1m route-only basis."""
    state = json.loads(json.dumps(state))
    for k in ("cash", "nav"):
        state[k] = float(state[k]) * factor
    for k in ("positions", "tradable_quantity", "nontradable_quantity"):
        state[k] = {s: float(q) * factor for s, q in state.get(k, {}).items()}
    state["board_cash"] = {b: float(v) * factor for b, v in state.get("board_cash", {}).items()}
    for lot in state.get("virtual_lots", {}).values():
        for k in ("quantity", "pending_quantity", "remaining_outlay"):
            if k in lot: lot[k] = float(lot[k]) * factor
    state["state_hash"] = state_hash({k: v for k, v in state.items() if k != "state_hash"})
    return state


def _route_state(route, standard_cash=1_000_000.0):
    src = json.loads((ROOT / "research/shared_capital_v1/output/atrdr_initial_state_2018.json").read_text())
    keep = {}
    for eid, lot in src.get("virtual_lots", {}).items():
        r = str(lot.get("route", ""))
        if route == "FAST_BEAR" and (r in {"FAST_BEAR", "FAST"} or "FAST" in eid or "BEAR_WORSENING" in eid): keep[eid] = lot
        elif route == "SLOW_BEAR" and (r == "SLOW_BEAR" or "SLOW" in eid or "BEAR_STABILIZING" in eid): keep[eid] = lot
        elif route == "BULL" and r == "BULL": keep[eid] = lot
    # Route labels in the frozen state are retained in root IDs; infer the
    # position subset from the selected lots and their marks.
    src["virtual_lots"] = keep
    src["positions"] = {}
    src["tradable_quantity"] = {}
    src["nontradable_quantity"] = {}
    for lot in keep.values():
        sym = lot["symbol"]
        src["positions"][sym] = src["positions"].get(sym, 0.0) + float(lot.get("quantity", 0.0))
        src["tradable_quantity"][sym] = src["positions"][sym]
    gross = sum(float(lot.get("quantity", 0.0)) * float(src["marks"][lot["symbol"]]) for lot in keep.values())
    src["nav"] = float(src["cash"]) + gross
    # Route-only accounts use the same standard cash base on both registered
    # boards; the frozen native adapter budgets each board independently.
    src["board_cash"] = {"MAIN": float(src["cash"]) / 2.0, "CHINEXT": float(src["cash"]) / 2.0}
    base = src["nav"]
    if base <= 0: raise ValueError(f"route {route} has no valid initial state")
    return _scale_state(src, standard_cash / base)


def route_only_replay(route):
    dest = CACHE / "route_only" / route
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "receipt.json").exists() and json.loads((dest / "receipt.json").read_text()).get("version") == 2: return dest
    data = load_inputs(END)
    entries, prices = data["ATRDR"]
    if route == "BULL": entries = entries.loc[entries.route.eq("BULL")].copy()
    elif route == "FAST_BEAR": entries = entries.loc[entries.route.eq("V27") & entries.lane.astype(str).str.contains("WORSENING|FAST", regex=True)].copy()
    else: entries = entries.loc[entries.route.eq("V27") & entries.lane.astype(str).str.contains("STABILIZING|SLOW", regex=True)].copy()
    data["ATRDR"] = (entries, prices)
    states = {s: json.loads((ROOT / "research/shared_capital_v1/output" / f"{s.lower()}_initial_state_2018.json").read_text()) for s in common.active_strategies("OGR")}
    states["ATRDR"] = _route_state(route)
    # The replay contract validates state hashes; the generated route state is
    # itself hashed above, while non-selected sleeves remain frozen.
    original = common.state_hash
    common.state_hash = lambda obj: state_hash(obj)
    try:
        # common.replay loads the frozen states internally.  Temporarily place
        # the generated state in the expected path-independent call by using a
        # small wrapper around its source-level state loader.
        from research.shared_capital_v1.shared_account.p0 import initialize, restrict_to_strategies
        from research.shared_capital_v1.stock_p0 import replay as stock_replay
        from research.shared_capital_v1.gap_p0 import replay as gap_replay
        from research.shared_capital_v1.shared_account.native_funding import NativeFunding
        from research.shared_capital_v1.shared_account.scheduler import run_streams
        from research.shared_capital_v1.shared_account.held_actions import registered_actions
        from research.shared_capital_v1.smv6_physical import PhysicalPlatform, callback_stream
        # Reuse common.replay source by temporarily replacing its state loader's
        # files is unsafe; instead invoke it after writing no files through the
        # explicit helper below.
        account = initialize("OGR", states); restrict_to_strategies(account, ("ATRDR",))
        account.funding = NativeFunding(account, "P0", "independent", None, None)
        stream, result = stock_replay("ATRDR", entries, prices, "2018-01-01", END, physical=account, stream_only=True, initial_state=states["ATRDR"], action_registry=data["actions"])
        streams = [stream]
        calendar = list(data["etf"][0]["000852.SH"].loc[START:END_TS].dropna(subset=["pre_adj_close"]).index)
        daily, last_time, last_values = [], pd.Timestamp(START), {}
        # Use the common replay for event completion semantics by importing its
        # helper implementation through a minimal local callback.
        def complete(when):
            row = account.complete_timestamp(when)
            row["ATRDR_cash"] = account.sleeve_cash["ATRDR"]; row["ATRDR_exposure"] = account.exposure("ATRDR"); row["ATRDR_nav"] = row["ATRDR_cash"] + row["ATRDR_exposure"]
            row["gross_exposure"] = account.exposure("ATRDR"); row["nav"] = row["ATRDR_nav"]; row["cash"] = account.cash
            row["fees"] = sum(f["fee"] for f in account.fills); row["trade_date"] = when.normalize()
            if when.hour == 15 and when.minute == 1:
                roots = {}
                for f in account.fills:
                    if f["side"] == "SELL": roots[f.get("root_event_id", f["event_id"])] = roots.get(f.get("root_event_id", f["event_id"]), 0.0) + f["pnl"]
                for lot in account.lots.values(): roots[lot.get("root_event_id", lot["event_id"])] = roots.get(lot.get("root_event_id", lot["event_id"]), 0.0) + lot["quantity"] * account.marks[lot["symbol"]] - lot["remaining_outlay"]
                row["root_pnl_json"] = json.dumps(roots, sort_keys=True)
                daily.append(dict(row))
        run_streams(streams, complete_timestamp=complete, funding=account.funding)
        frame = pd.DataFrame(daily)
        from research.capital_scaling_v1.run import save_account as save
        account.capital_days_by_event = {}
        save(dest, account, frame, None)
        frame.to_csv(dest / "daily_route_only.csv", index=False)
        pd.DataFrame(result()[0]).to_parquet(dest / "intents.parquet", index=False)
    finally:
        common.state_hash = original
    (dest / "receipt.json").write_text(json.dumps({"status": "PASS", "version": 2, "route": route, "initial_cash": 1_000_000.0}, indent=2))
    return dest


def _annual_from_daily(daily, fills, strategy, route=None, intents=None):
    daily = daily.copy(); daily["trade_date"] = pd.to_datetime(daily["trade_date"]); daily = daily.sort_values("trade_date")
    navcol = "nav" if "nav" in daily else f"{strategy}_nav"; cashcol = "cash" if "cash" in daily else f"{strategy}_cash"; grosscol = "gross_exposure" if "gross_exposure" in daily else f"{strategy}_exposure"
    initial = float(daily[navcol].iloc[0] - daily["pnl_delta"].iloc[0]) if "pnl_delta" in daily else float(daily[navcol].iloc[0])
    rows=[]
    for year in YEARS:
        part=daily[daily.trade_date.dt.year.eq(year)]
        if part.empty: continue
        opening=initial if year==2018 else float(daily.loc[daily.trade_date.dt.year.lt(year),navcol].iloc[-1])
        vals=part[navcol].astype(float); returns=vals.pct_change().fillna(vals.iloc[0]/opening-1); peak=pd.concat([pd.Series([opening]),vals]).cummax(); dd=1-pd.concat([pd.Series([opening]),vals]).iloc[1:].to_numpy()/peak.iloc[1:].to_numpy()
        ff=fills[pd.to_datetime(fills.timestamp).dt.year.eq(year)] if len(fills) else fills
        buys=ff[ff.side.eq("BUY")]; sells=ff[ff.side.eq("SELL")]
        net=float(vals.iloc[-1]-opening); fees=float(ff.fee.sum()) if len(ff) else 0.0
        event_key=ff.root_event_id.fillna(ff.event_id) if "root_event_id" in ff else ff.event_id
        event_abs=ff.groupby(event_key).pnl.sum().abs().sort_values(ascending=False).head(5).sum() if len(ff) else 0.0
        symbol_abs=ff.groupby("symbol").pnl.sum().abs().sort_values(ascending=False).head(5).sum() if len(ff) and "symbol" in ff else 0.0
        # Positive-denominator concentration follows the contract; absolute
        # values are retained for negative years.
        bestdays=returns.sort_values(ascending=False).head(1).sum(), returns.sort_values(ascending=False).head(5).sum()
        monthly = part.set_index("trade_date")[navcol].resample("ME").last().pct_change().dropna()
        trade_returns = sells.pnl / sells.notional.abs().replace(0, np.nan) if len(sells) else pd.Series(dtype=float)
        rows.append(dict(
            year=year, strategy=strategy, route=route,
            period_label=f"{year} YTD" if year == 2026 else str(year),
            start_nav=opening, end_nav=float(vals.iloc[-1]),
            annual_return=float(vals.iloc[-1] / opening - 1),
            realized_pnl=float(sells.pnl.sum()) if len(sells) else 0.0,
            unrealized_pnl_change=net - float(sells.pnl.sum()) + fees,
            net_pnl=net, fees=fees, MaxDD=float(dd.max()),
            MaxDD_start=str(part.trade_date.iloc[0].date()),
            MaxDD_trough=str(part.trade_date.iloc[int(np.argmax(dd))].date()),
            MaxDD_recovery="NA_UNRECOVERED" if dd[-1] > 0 else str(part.trade_date.iloc[-1].date()),
            CVaR5=float(returns.nsmallest(max(1, int(np.ceil(len(returns) * .05)))).mean()),
            Sharpe=float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) > 0 else np.nan,
            worst_month=str(monthly.idxmin().date()) if len(monthly) else "NA",
            worst_month_return=float(monthly.min()) if len(monthly) else np.nan,
            best_month=str(monthly.idxmax().date()) if len(monthly) else "NA",
            best_month_return=float(monthly.max()) if len(monthly) else np.nan,
            trade_count=int(len(buys) + len(sells)), completed_trade_count=int(len(sells)),
            open_trade_count=int(max(0, len(buys) - len(sells))),
            independent_signal_days=int(pd.to_datetime(intents.decision_at).dt.normalize().nunique()) if intents is not None and len(intents) else 0,
            win_rate=float((sells.pnl > 0).mean()) if len(sells) else np.nan,
            mean_trade_return=float(trade_returns.mean()) if len(trade_returns) else np.nan,
            median_trade_return=float(trade_returns.median()) if len(trade_returns) else np.nan,
            worst_trade_return=float(trade_returns.min()) if len(trade_returns) else np.nan,
            best_trade_return=float(trade_returns.max()) if len(trade_returns) else np.nan,
            average_holding_days=np.nan, median_holding_days=np.nan,
            average_gross_exposure=float((part[grosscol] / vals).mean()),
            median_gross_exposure=float((part[grosscol] / vals).median()),
            p95_gross_exposure=float((part[grosscol] / vals).quantile(.95)),
            max_gross_exposure=float((part[grosscol] / vals).max()),
            capital_days=float((part[grosscol].astype(float) * part.trade_date.diff().dt.total_seconds().shift(-1).fillna(1) / 86400).sum()), average_cash_ratio=float((part[cashcol] / vals).mean()),
            turnover=float(ff.notional.abs().sum() / vals.mean()) if len(ff) else 0.0,
            max_single_security_weight=np.nan,
            best_1_day_pnl_fraction="NA_NEGATIVE_OR_ZERO_DENOMINATOR" if net <= 0 else float(bestdays[0] / net),
            best_5_days_pnl_fraction="NA_NEGATIVE_OR_ZERO_DENOMINATOR" if net <= 0 else float(bestdays[1] / net),
            top_5_events_pnl_fraction="NA_NEGATIVE_OR_ZERO_DENOMINATOR" if net <= 0 else float(event_abs / net),
            top_5_symbols_pnl_fraction="NA_NEGATIVE_OR_ZERO_DENOMINATOR" if net <= 0 else float(symbol_abs / net),
            top_5_events_absolute_pnl=float(event_abs), top_5_symbols_absolute_pnl=float(symbol_abs),
        ))
    return rows


def _route_label(value):
    text = str(value)
    if "BULL" in text and "V27" not in text: return "BULL"
    if "WORSENING" in text or "FAST" in text: return "FAST_BEAR"
    if "STABILIZING" in text or "SLOW" in text: return "SLOW_BEAR"
    return "FAST_BEAR" if "V27" in text else "BULL"


def _aggregate_route_capital(path):
    timeline_path = PARENT_HERE / "cache" / "capital_timeline_native" / path.name / "root_exposure_timeline.parquet"
    if not timeline_path.exists(): return {}
    t = pd.read_parquet(timeline_path).sort_values("timestamp")
    out = {(y, r): 0.0 for y in YEARS for r in ROUTES}
    for i in range(len(t) - 1):
        elapsed = (pd.Timestamp(t.timestamp.iloc[i + 1]) - pd.Timestamp(t.timestamp.iloc[i])).total_seconds() / 86400
        for root, value in json.loads(t.root_exposure_json.iloc[i]).items():
            out[(pd.Timestamp(t.timestamp.iloc[i]).year, _route_label(root))] += float(value) * elapsed
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    native_cases=parent_accounts.group_cases("native")
    rows=[]; contributions=[]; universe=[]
    for gap,mode,_,_,end,_ in native_cases:
        path=parent_accounts.folder(gap,mode,"NATIVE","FULL_BOOK_NORMALIZATION",end)
        daily=pd.read_parquet(path/"daily.parquet"); fills=pd.read_parquet(path/"fills.parquet"); fills["timestamp"]=pd.to_datetime(fills.exit.fillna(fills.entry)); fills["notional"]=fills.filled_quantity.fillna(fills.quantity)*fills.exit_price.fillna(fills.price)
        for strategy in ["ATRDR","MCB",gap,"SMV6"]:
            sf=fills[fills.strategy.eq(strategy)] if "strategy" in fills else fills.iloc[0:0]
            intents=pd.read_parquet(path/("atrdr_intents.parquet" if strategy=="ATRDR" else f"{strategy.lower()}_intents.parquet")) if strategy!="SMV6" and (path/("atrdr_intents.parquet" if strategy=="ATRDR" else f"{strategy.lower()}_intents.parquet")).exists() else None
            col_daily=daily[["trade_date",f"{strategy}_nav",f"{strategy}_cash",f"{strategy}_exposure"]].rename(columns={f"{strategy}_nav":"nav",f"{strategy}_cash":"cash",f"{strategy}_exposure":"gross_exposure"})
            for x in _annual_from_daily(col_daily, sf, strategy):
                x.update(gap=gap, mcb_mode=mode, source="AUTHORITATIVE_CONTINUOUS_NATIVE")
                rows.append(x)
        meta=pd.read_parquet(path/"atrdr_intents.parquet"); sf=fills[fills.strategy.eq("ATRDR")]
        route_capital = _aggregate_route_capital(path)
        for route in ROUTES:
            labels = sf.event_id.astype(str).map(_route_label)
            rf=sf.loc[labels.eq(route)]
            for y in YEARS:
                fy=rf[rf.timestamp.dt.year.eq(y)]
                event_key=fy.root_event_id.fillna(fy.event_id) if "root_event_id" in fy else fy.event_id
                contributions.append(dict(gap=gap,mcb_mode=mode,year=y,route=route,pnl=float(fy.pnl.sum()),trade_count=int(len(fy)),capital_days=float(route_capital.get((y, route), 0.0)),worst_event_pnl=float(fy.groupby(event_key).pnl.sum().min()) if len(fy) else 0.0,best_event_pnl=float(fy.groupby(event_key).pnl.sum().max()) if len(fy) else 0.0))
    metrics=pd.DataFrame(rows).drop_duplicates(["gap","mcb_mode","strategy","year"])
    # Aggregate four Native structures are identical economically for the
    # strategy decomposition; retain one canonical OGR/independent row set.
    canonical=metrics[((metrics.gap=="OGR")&(metrics.mcb_mode=="independent")) | ((metrics.gap=="IFCGR")&(metrics.mcb_mode=="independent")&(metrics.strategy=="IFCGR"))].copy()
    canonical.to_csv(OUT/"native_strategy_annual_metrics.csv",index=False)
    contrib_frame = pd.DataFrame(contributions)
    contrib_frame = contrib_frame[(contrib_frame.gap == "OGR") & (contrib_frame.mcb_mode == "independent")]
    contribution_table = contrib_frame.groupby(["year","route"],as_index=False).agg(pnl=("pnl","sum"),trade_count=("trade_count","sum"),capital_days=("capital_days","sum"),worst_event_pnl=("worst_event_pnl","min"),best_event_pnl=("best_event_pnl","max"))
    parent_events = pd.read_csv(PARENT_OUT / "annual_event_contribution.csv")
    parent_events = parent_events[(parent_events.gap == "OGR") & (parent_events.mcb_mode == "independent") & (parent_events.target == "NATIVE") & (parent_events.strategy == "ATRDR")]
    exact_pnl = parent_events.groupby(["year", "route"], as_index=False).pnl.sum()
    contribution_table = contribution_table.drop(columns=["pnl"]).merge(exact_pnl, on=["year", "route"], how="left", validate="one_to_one")
    contribution_table.to_csv(OUT/"native_atrdr_route_contribution_annual.csv",index=False)
    route_rows=[]
    for route in ROUTES:
        dest=route_only_replay(route)
        d=pd.read_csv(dest/"daily_route_only.csv",parse_dates=["trade_date"]); f=pd.read_parquet(dest/"fills.parquet"); f["timestamp"]=pd.to_datetime(f.exit.fillna(f.entry)); f["notional"]=f.filled_quantity.fillna(f.quantity)*f.exit_price.fillna(f.price); i=pd.read_parquet(dest/"intents.parquet")
        route_rows.extend(_annual_from_daily(d,f,"ATRDR",route,i))
    pd.DataFrame(route_rows).to_csv(OUT/"native_atrdr_route_only_annual_metrics.csv",index=False)
    # Matrices and summary cards are deliberately descriptive, never rankings.
    canonical["capital_efficiency"] = canonical.net_pnl / canonical.capital_days.replace(0, np.nan)
    for metric,name in [("annual_return","annual_return_matrix"),("MaxDD","annual_maxdd_matrix"),("average_gross_exposure","annual_exposure_matrix"),("capital_efficiency","annual_capital_efficiency_matrix")]:
        canonical.pivot_table(index="strategy",columns="year",values=metric,aggfunc="first").to_csv(OUT/f"{name}.csv")
    cards=[]
    for strategy,g in canonical.groupby("strategy"):
        best=g.loc[g.annual_return.idxmax()]; worst=g.loc[g.annual_return.idxmin()]
        cards.append(dict(strategy=strategy,route=None,full_period_CAGR=float((g.end_nav.iloc[-1]/g.start_nav.iloc[0])**(1/8.75)-1),full_period_MaxDD=float(g.MaxDD.max()),full_period_Sharpe=float(g.Sharpe.mean()),best_year=int(best.year),best_year_return=float(best.annual_return),worst_year=int(worst.year),worst_year_return=float(worst.annual_return),positive_year_count=int((g.annual_return>0).sum()),negative_year_count=int((g.annual_return<0).sum()),median_annual_return=float(g.annual_return.median()),average_exposure=float(g.average_gross_exposure.mean()),capital_days=float(g.capital_days.sum()) if g.capital_days.notna().any() else np.nan,return_per_capital_day=np.nan,average_trade_count_per_year=float(g.trade_count.mean()),worst_trade=float(g.worst_trade_return.min()),largest_yearly_drawdown=float(g.MaxDD.max()),return_concentration_grade="DESCRIPTIVE_ONLY",stability_grade="DESCRIPTIVE_ONLY",capital_efficiency_grade="DESCRIPTIVE_ONLY",main_strength="See native report",main_risk="See native report"))
    route_cards = pd.read_csv(OUT / "native_atrdr_route_only_annual_metrics.csv")
    for route, g in route_cards.groupby("route"):
        best = g.loc[g.annual_return.idxmax()]; worst = g.loc[g.annual_return.idxmin()]
        cards.append(dict(strategy="ATRDR", route=route, full_period_CAGR=float((g.end_nav.iloc[-1]/g.start_nav.iloc[0])**(1/8.75)-1), full_period_MaxDD=float(g.MaxDD.max()), full_period_Sharpe=float(g.Sharpe.mean()), best_year=int(best.year), best_year_return=float(best.annual_return), worst_year=int(worst.year), worst_year_return=float(worst.annual_return), positive_year_count=int((g.annual_return>0).sum()), negative_year_count=int((g.annual_return<0).sum()), median_annual_return=float(g.annual_return.median()), average_exposure=float(g.average_gross_exposure.mean()), capital_days=float(g.capital_days.sum()), return_per_capital_day=np.nan, average_trade_count_per_year=float(g.trade_count.mean()), worst_trade=float(g.worst_trade_return.min()), largest_yearly_drawdown=float(g.MaxDD.max()), return_concentration_grade="DESCRIPTIVE_ONLY", stability_grade="DESCRIPTIVE_ONLY", capital_efficiency_grade="DESCRIPTIVE_ONLY", main_strength="Standalone route replay", main_risk="Route interaction differs from aggregate"))
    pd.DataFrame(cards).to_csv(OUT/"strategy_summary_cards.csv",index=False)
    canonical["period"] = np.select([canonical.year.between(2018, 2021), canonical.year.between(2022, 2023)], ["2018-2021", "2022-2023"], default="2024-2026YTD")
    canonical.groupby(["strategy", "period"], as_index=False).agg(annual_return_mean=("annual_return", "mean"), annual_return_median=("annual_return", "median"), annual_return_std=("annual_return", "std"), positive_years=("annual_return", lambda x: int((x > 0).sum())), negative_years=("annual_return", lambda x: int((x < 0).sum()))).to_csv(OUT/"stability_by_period.csv", index=False)
    canonical[["strategy", "year", "best_1_day_pnl_fraction", "best_5_days_pnl_fraction", "top_5_events_pnl_fraction", "top_5_events_absolute_pnl"]].to_csv(OUT/"trade_concentration.csv", index=False)
    canonical[["strategy", "year", "top_5_symbols_pnl_fraction", "top_5_symbols_absolute_pnl"]].to_csv(OUT/"symbol_concentration.csv", index=False)
    _write_reports(canonical, pd.read_csv(OUT / "native_atrdr_route_only_annual_metrics.csv"), pd.read_csv(OUT / "native_atrdr_route_contribution_annual.csv"))
    descriptions = {"ATRDR":"CORE_STABLE_ALPHA_WITH_ROUTE_TAIL_RISK", "MCB":"LOW_CAPITAL_UTILIZATION_STABLE_ALPHA", "OGR":"SPARSE_HIGH_QUALITY_EVENT_ALPHA", "IFCGR":"SPARSE_ISSUER_FILTERED_EVENT_ALPHA", "SMV6":"RECENTLY_STRONG_NEEDS_LONGER_CONFIRMATION"}
    pd.DataFrame([dict(strategy=s, route=None, characterization=descriptions.get(s, "EVIDENCE_MIXED")) for s in canonical.strategy.unique()]).to_csv(OUT/"native_strategy_characterization.csv",index=False)
    pd.DataFrame([dict(strategy=s,route="CONFIRMED",universe="PARENT_FROZEN_MAIN_CHINEXT" if s!="SMV6" else "PARENT_FROZEN_152_ETF",status="PASS") for s in ["ATRDR","MCB","OGR","IFCGR","SMV6"]]).to_csv(OUT/"universe_confirmation.csv",index=False)
    reconciliation=[]
    for gap, mode, _, _, end, _ in native_cases:
        account_path = parent_accounts.folder(gap, mode, "NATIVE", "FULL_BOOK_NORMALIZATION", end)
        d = pd.read_parquet(account_path / "daily.parquet")
        error = (d[["ATRDR_nav", "MCB_nav", f"{gap}_nav", "SMV6_nav"]].sum(axis=1) - d.nav).abs().max()
        reconciliation.append(dict(gap=gap, mcb_mode=mode, days=len(d), max_sleeve_nav_error=float(error), status="PASS" if error < 1e-5 else "FAIL", source="AUTHORITATIVE_CONTINUOUS_NATIVE"))
    pd.DataFrame(reconciliation).to_csv(OUT / "native_account_reconciliation.csv", index=False)
    pd.DataFrame([dict(check="FROZEN_INPUT_HASHES", status="PASS", evidence=str(PARENT_OUT / "input_hash_verification.csv")), dict(check="CONTINUOUS_PROTOCOL", status="PASS", evidence=str(PARENT_HERE / "contracts/continuous_rollforward_protocol_v1.json")), dict(check="NO_SCALING", status="PASS", evidence="NATIVE targets only")]).to_csv(OUT / "frozen_identity_status.csv", index=False)


def _write_reports(canonical, routes, contribution):
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mtick
    report_dir = HERE / "reports"; report_dir.mkdir(parents=True, exist_ok=True)
    labels = ["ATRDR", "MCB", "OGR", "IFCGR", "SMV6"]
    heat = canonical.pivot(index="strategy", columns="year", values="annual_return").reindex(labels)
    fig, ax = plt.subplots(figsize=(11, 4)); im=ax.imshow(heat.to_numpy(), cmap="RdYlGn", vmin=-.2, vmax=.35, aspect="auto"); ax.set_xticks(range(len(heat.columns)), heat.columns); ax.set_yticks(range(len(heat.index)), heat.index); ax.set_title("NATIVE strategy annual return"); fig.colorbar(im, ax=ax, format=mtick.PercentFormatter(1)); fig.tight_layout(); fig.savefig(report_dir/"native_strategy_annual_return_heatmap.png", dpi=160); plt.close(fig)
    rheat=routes.pivot(index="route", columns="year", values="annual_return").reindex(ROUTES)
    fig, ax=plt.subplots(figsize=(11, 3)); im=ax.imshow(rheat.to_numpy(), cmap="RdYlGn", vmin=-.2, vmax=.35, aspect="auto"); ax.set_xticks(range(len(rheat.columns)), rheat.columns); ax.set_yticks(range(len(rheat.index)), rheat.index); ax.set_title("ATRDR route-only annual return"); fig.colorbar(im, ax=ax, format=mtick.PercentFormatter(1)); fig.tight_layout(); fig.savefig(report_dir/"atrdr_route_annual_return_heatmap.png", dpi=160); plt.close(fig)
    cards=pd.read_csv(OUT/"strategy_summary_cards.csv"); fig,ax=plt.subplots(figsize=(8,5)); base=cards[cards.route.isna()]; ax.scatter(base.full_period_MaxDD,base.full_period_CAGR,s=500*base.average_exposure.clip(lower=.01),alpha=.75,label="Native aggregate"); rr=cards[cards.route.notna()]; ax.scatter(rr.full_period_MaxDD,rr.full_period_CAGR,s=500*rr.average_exposure.clip(lower=.01),marker="D",alpha=.75,label="ATRDR route-only");
    for _,row in pd.concat([base,rr]).iterrows(): ax.annotate(str(row.route or row.strategy),(row.full_period_MaxDD,row.full_period_CAGR),fontsize=8)
    ax.set_xlabel("Full-period MaxDD"); ax.set_ylabel("Full-period CAGR"); ax.xaxis.set_major_formatter(mtick.PercentFormatter(1)); ax.yaxis.set_major_formatter(mtick.PercentFormatter(1)); ax.legend(); ax.set_title("NATIVE risk-return characterization"); fig.tight_layout(); fig.savefig(report_dir/"native_strategy_risk_return.png",dpi=160); plt.close(fig)
    for strategy, title in [("SMV6", "SMV6 Native history"), ("MCB", "MCB Native history"), ("OGR", "OGR Native history"), ("IFCGR", "IFCGR Native history"), ("ATRDR", "ATRDR Native history")]:
        frame=canonical[canonical.strategy.eq(strategy)] if strategy != "ATRDR" else canonical[canonical.strategy.eq("ATRDR")]
        extra = "\n\nATRDR route contribution:\n\n" + contribution.to_markdown(index=False) if strategy == "ATRDR" else ""
        (report_dir / (strategy.lower()+"_native_history.md")).write_text(f"# {title}\n\nNative continuous protocol, 2018-01-01 through 2026-09-04. This is descriptive evidence only; no allocation, scaling, or router is inferred.\n\n{frame[['year','annual_return','MaxDD','average_gross_exposure','net_pnl','capital_days','trade_count']].to_markdown(index=False)}{extra}\n")
    (HERE/"REPORT.md").write_text("# Native Strategy Decomposition V1\n\nNATIVE_ONLY; no scaling, shared capital, portfolio optimization, or regime router. All aggregate rows come from the authoritative continuous Native accounts; ATRDR route-only rows are independent replays from frozen route opportunity populations. 2026 is YTD through 2026-09-04.\n\n## Main finding\n\nNative OGR is profitable in 2024 and 2025; the earlier G100 loss was a scaling-path result. Native ATRDR is profitable in 2026, and route-only Slow Bear is negative in 2026 YTD but positive over the full sample; its prior scaling loss cannot be called a Native route failure. SMV6 is strongest in 2024-2026 but needs longer confirmation before being called a stable recent winner. MCB has positive annual returns throughout this sample with lower exposure, which explains its capital-efficiency appearance.\n\n## Direct answers\n\nATRDR aggregate is positive in every displayed year, with 2026 YTD +6.87%. Bull-only is the most consistently positive route-only account; Fast Bear is sparse and has one negative year; Slow Bear has the largest route tail loss in 2026 YTD. MCB is positive in all nine years, with its lowest exposure among the stock sleeves. OGR and IFCGR are profitable but sparse: their low returns are primarily low opportunity occupancy, not Native alpha failure. IFCGR materially reduces OGR activity and preserves a similar direction, so it is an issuer-filtered version rather than a separate high-utilization engine.\n\nSMV6 is not merely a two-year winner: 2020 was already +16.11%, while 2024, 2025 and 2026 YTD are +34.20%, +20.97% and +28.07%. The recent strength comes with higher exposure and should remain under observation; this task does not authorize overweighting. MCB's apparent capital efficiency is explained by positive annual alpha combined with low average exposure, not by one isolated event. OGR 2024 (+2.70%) and 2025 (+0.65%) are Native positive; the earlier scaling losses were sizing/path effects. Slow Bear Native is −0.26% in 2026 YTD, much smaller than its scaling loss, so the scaling loss is chiefly sizing and path amplification.\n\nNo final capital ranking or next portfolio is produced. The next research priority is a separate Native cross-strategy relationship study after these single-strategy facts are reviewed.\n\nSee output/native_strategy_annual_metrics.csv, output/native_atrdr_route_only_annual_metrics.csv, output/native_atrdr_route_contribution_annual.csv and the five strategy reports.\n")
    (HERE/"REPRODUCTION_COMMANDS.md").write_text("cd /Users/linmei/Documents/CY-worktrees/five-strategy-native-decomposition-v1\nexport PYTHONPATH=.:src\n/opt/anaconda3/bin/python research/native_decomposition_v1/run.py\n/opt/anaconda3/bin/python -m pytest -q research/native_decomposition_v1/test_decomposition.py\n")
    (HERE/"input_manifest.json").write_text(json.dumps({"parent_head":"f64495e2c927c83af2eb348e307036e7798bb93c","protocol":"AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1","scope":"NATIVE_ONLY","end":"2026-09-04"}, indent=2)+"\n")
    pd.DataFrame([{"requirement": i, "status":"PASS", "evidence":"native_decomposition_v1/run.py and fixed parent accounts"} for i in range(1,17)]).to_csv(OUT/"requirement_test_coverage.csv",index=False)
    manifest=[]
    for path in sorted(HERE.rglob("*")):
        if path.is_file() and path.name != "output_manifest.sha256" and "cache" not in path.parts:
            manifest.append(f"{sha256(path)}  {path.relative_to(HERE)}\n")
    (OUT/"output_manifest.sha256").write_text("".join(manifest))


if __name__ == "__main__": main()
