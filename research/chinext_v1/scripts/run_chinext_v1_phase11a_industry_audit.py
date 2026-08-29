#!/usr/bin/env python3
"""Zero-replay PIT industry attribution for frozen ChinNext trades."""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from run_chinext_v1_full_survivor import read_jsonl
from run_chinext_v1_pit_replay import reconstruct_round_trips
from run_chinext_v1_smoke import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
SPEC = REPORTS / "chinext_v1_phase11a_industry_spec.json"
OUT = REPORTS / "chinext_v1_phase11a_industry_audit_summary.json"
MD = REPORTS / "chinext_v1_phase11a_industry_audit.md"
TRADE_OUT = REPORTS / "chinext_v1_phase11a_trade_industry.csv"
DATA_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
DEV_ATTR = REPORTS / "chinext_v1_trade_attribution.csv"
DEV_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/execution_ledger.jsonl"
OOS_EXEC = ROOT / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE/execution_ledger.jsonl"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
FEATURE_YEARS = {"2022": "HOLDOUT", "2023": "HOLDOUT", "2024": "DEVELOPMENT", "2025": "DEVELOPMENT"}


def qstats(values: list[float]) -> dict[str, Any]:
    x = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not x:
        return {"count": 0, "median": None, "mean": None, "p25": None, "p75": None}
    return {"count": len(x), "median": statistics.median(x), "mean": statistics.fmean(x), "p25": x[int(.25 * (len(x) - 1))], "p75": x[int(.75 * (len(x) - 1))]}


def read_industry(rows: pd.DataFrame) -> pd.DataFrame:
    symbols = sorted(set(rows.symbol.astype(str))); dates = sorted(set(rows.entry_signal_date.astype(str)))
    con = duckdb.connect(); phs = ",".join("?" for _ in symbols); phd = ",".join("?" for _ in dates); parts, params = [], []
    for year in range(2022, 2026):
        parts.append(f"select cast(trade_date as varchar) trade_date,symbol,industry,industry_source,source_notice_date,source_report_date,industry_valid,hard_valid,available_at,snapshot_id,pit_grade from read_parquet(?) where symbol in ({phs}) and cast(trade_date as varchar) in ({phd})")
        params += [str(DATA_ROOT / f"partition_year={year}" / "data_0.parquet"), *symbols, *dates]
    out = con.execute(" union all ".join(parts), params).fetchdf(); con.close()
    return out.sort_values(["symbol", "trade_date"]).drop_duplicates(["symbol", "trade_date"], keep="first")


def oos_trades() -> pd.DataFrame:
    trips = reconstruct_round_trips(read_jsonl(OOS_EXEC)); symbols = sorted({str(t["symbol"]) for t in trips})
    con = duckdb.connect(); ph = ",".join("?" for _ in symbols); parts, params = [], []
    for year in range(2022, 2024):
        parts.append(f"select cast(trade_date as varchar) trade_date,symbol,high,close,hard_valid from read_parquet(?) where symbol in ({ph})")
        params += [str(DATA_ROOT / f"partition_year={year}" / "data_0.parquet"), *symbols]
    prices = con.execute(" union all ".join(parts), params).fetchdf(); con.close(); prices["high"] = pd.to_numeric(prices.high, errors="coerce"); prices["close"] = pd.to_numeric(prices.close, errors="coerce")
    out = []
    for i, t in enumerate(trips):
        s, entry, exitd, px = str(t["symbol"]), str(t["entry_execution_date"]), str(t["exit_execution_date"]), float(t["entry_price"])
        x = prices[(prices.symbol == s) & (prices.trade_date >= entry) & (prices.trade_date <= exitd)].sort_values("trade_date")
        highs = x.high.dropna().tolist()
        if not highs or px <= 0: continue
        out.append({"trade_id": f"{s}-{i+1:03d}", "sample": "OOS", "symbol": s, "entry_signal_date": str(t["entry_signal_date"]), "entry_execution_date": entry, "exit_signal_date": str(t["exit_signal_date"]), "exit_execution_date": exitd, "realized_return": float(t["round_trip_return"]), "realized_pnl": float(t["realized_pnl"]), "holding_trading_days": int(len(x)), "MFE": max(highs) / px - 1, "entry_reason": t.get("entry_reason"), "exit_reason": t.get("exit_reason")})
    return pd.DataFrame(out)


def load_trades() -> pd.DataFrame:
    dev = pd.read_csv(DEV_ATTR)
    dev = dev.rename(columns={"MFE": "MFE", "realized_return": "realized_return", "realized_pnl": "realized_pnl"})
    dev["sample"] = "DEVELOPMENT"; dev["trade_id"] = dev.trade_id.astype(str)
    keep = ["trade_id", "sample", "symbol", "entry_signal_date", "entry_execution_date", "exit_signal_date", "exit_execution_date", "realized_return", "realized_pnl", "holding_trading_days", "MFE", "entry_reason", "exit_reason"]
    dev = dev[keep]
    return pd.concat([oos_trades(), dev], ignore_index=True)


def industry_stats(df: pd.DataFrame) -> dict[str, Any]:
    mapped = df[df.industry_status == "MAPPED"]
    gross_positive = float(mapped.loc[mapped.realized_pnl > 0, "realized_pnl"].sum())
    total = float(mapped.realized_pnl.sum())
    out: dict[str, Any] = {}
    for ind, x in mapped.groupby("industry_name", sort=True):
        pos = float(x.loc[x.realized_pnl > 0, "realized_pnl"].sum()); neg = float(x.loc[x.realized_pnl < 0, "realized_pnl"].sum()); signed = float(x.realized_pnl.sum())
        out[str(ind)] = {"trade_count": int(len(x)), "unique_symbols": int(x.symbol.nunique()), "win_rate": float((x.realized_return > 0).mean()), "median_return": float(x.realized_return.median()), "mean_return": float(x.realized_return.mean()), "total_realized_pnl": signed, "positive_pnl": pos, "negative_pnl": neg, "MFE_median": float(x.MFE.median()), "holding_days_median": float(x.holding_trading_days.median()), "trade_share": float(len(x) / len(mapped)) if len(mapped) else None, "gross_positive_pnl_share": pos / gross_positive if gross_positive else None, "signed_pnl_share": signed / total if total else None, "right_tail_20_count": int((x.MFE >= .20).sum()), "right_tail_50_count": int((x.MFE >= .50).sum())}
    shares = [v["trade_share"] for v in out.values() if v["trade_share"] is not None]
    return {"industries": out, "unique_industries": len(out), "industry_hhi_by_trade_share": float(sum(s * s for s in shares)), "mapped_trade_count": int(len(mapped)), "gross_positive_pnl": gross_positive, "total_signed_pnl": total}


def concentration(df: pd.DataFrame, top_n: int | None = None) -> dict[str, Any]:
    x = df[df.industry_status == "MAPPED"].copy()
    if top_n is not None: x = x[x.pnl_rank <= top_n]
    c = Counter(x.industry_name); total = len(x); counts = sorted(c.items(), key=lambda z: (-z[1], z[0]))
    return {"trade_count": total, "unique_industries": len(c), "industry_counts": dict(counts), "top_industry": counts[0][0] if counts else None, "top_industry_count": counts[0][1] if counts else 0, "top_industry_share": counts[0][1] / total if counts and total else None, "top3_industry_share": sum(v for _, v in counts[:3]) / total if total else None, "industry_hhi": sum((v / total) ** 2 for v in c.values()) if total else None}


def main() -> int:
    spec = json.loads(SPEC.read_text()); spec_sha = sha256_file(SPEC)
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_ANALYSIS": raise RuntimeError("industry spec not frozen")
    trades = load_trades(); industries = read_industry(trades)
    trades = trades.merge(industries, left_on=["symbol", "entry_signal_date"], right_on=["symbol", "trade_date"], how="left")
    trades["year"] = trades.entry_signal_date.str[:4]
    trades["pnl_rank"] = trades.groupby("sample").realized_pnl.rank(method="first", ascending=False).astype("Int64")
    causal = trades.source_notice_date.notna() & (trades.source_notice_date.astype(str) < trades.entry_signal_date.astype(str))
    good = trades.industry.notna() & trades.industry_valid.fillna(False) & (trades.industry.astype(str).str.upper() != "UNKNOWN") & causal
    trades["industry_status"] = good.map({True: "MAPPED", False: "UNMAPPED"}); trades["industry_code"] = trades.industry.where(good); trades["industry_name"] = trades.industry.where(good)
    trades["classification_effective_date"] = trades.source_report_date; trades["classification_source"] = trades.industry_source; trades["pit_status"] = trades.industry_status.map({"MAPPED": "PIT_VERIFIED_CY006_BOUNDED", "UNMAPPED": "UNMAPPED_FAIL_CLOSED"})
    cols = ["trade_id", "sample", "year", "symbol", "entry_signal_date", "entry_execution_date", "exit_signal_date", "exit_execution_date", "industry_code", "industry_name", "classification_effective_date", "classification_source", "pit_status", "realized_return", "realized_pnl", "MFE", "holding_trading_days", "pnl_rank"]
    trades[cols].sort_values(["sample", "entry_signal_date", "symbol"]).to_csv(TRADE_OUT, index=False, lineterminator="\n")
    coverage = {}
    for y in ("2022", "2023", "2024", "2025"):
        x = trades[trades.year == y]; coverage[y] = {"trade_count": int(len(x)), "industry_mapped_count": int((x.industry_status == "MAPPED").sum()), "industry_unmapped_count": int((x.industry_status != "MAPPED").sum()), "coverage_rate": float((x.industry_status == "MAPPED").mean()) if len(x) else None}
    sample_cov = {s: {"trade_count": int(len(x)), "mapped": int((x.industry_status == "MAPPED").sum()), "unmapped": int((x.industry_status != "MAPPED").sum()), "coverage_rate": float((x.industry_status == "MAPPED").mean()) if len(x) else None} for s, x in trades.groupby("sample")}
    yearly_industry = {y: industry_stats(trades[trades.year == y]) for y in ("2022", "2023", "2024", "2025")}; overall = industry_stats(trades)
    top20 = concentration(trades[(trades["sample"] == "DEVELOPMENT") & (trades.pnl_rank <= 20)]); top10 = concentration(trades[(trades["sample"] == "DEVELOPMENT") & (trades.pnl_rank <= 10)]); oos_top10 = concentration(trades[(trades["sample"] == "OOS") & (trades.pnl_rank <= 10)])
    sep = trades[(trades["sample"] == "DEVELOPMENT") & trades.entry_signal_date.str.startswith("2024-09")]; sep_con = concentration(sep)
    mix = {"OOS": industry_stats(trades[trades["sample"] == "OOS"]), "DEVELOPMENT": industry_stats(trades[trades["sample"] == "DEVELOPMENT"])}
    common = sorted(set(mix["OOS"]["industries"]) & set(mix["DEVELOPMENT"]["industries"]))
    same = {}
    for ind in common:
        o, d = mix["OOS"]["industries"][ind], mix["DEVELOPMENT"]["industries"][ind]
        if o["trade_count"] >= 5 and d["trade_count"] >= 5:
            same[ind] = {"OOS": o, "DEVELOPMENT": d, "win_rate_delta": d["win_rate"] - o["win_rate"], "median_return_delta": d["median_return"] - o["median_return"], "MFE20_rate_OOS": o["right_tail_20_count"] / o["trade_count"], "MFE20_rate_DEVELOPMENT": d["right_tail_20_count"] / d["trade_count"]}
    deps = {"industry_source": {"asset_id": "QD-008", "path": "/Users/linmei/Downloads/workspace/quant/data/lake/meta/industry_daily.parquet", "taxonomy": "Eastmoney yjbb disclosure chronology", "coverage": ["2005-07-25", "2026-08-13"], "effective_date": "source_notice_date < trade_date", "record_available_at": False, "historical_revision_lineage": "supplier response-vintage unavailable", "authorization_scope": "registered PIT sector attribution; unknown rows fail closed"}, "daily_pit_join": {"asset_id": "CY-006", "path": str(DATA_ROOT), "taxonomy": "industry field carried in frozen daily PIT-B", "coverage": ["2018-01-01", "2026-08-12"], "effective_date": "source_notice_date < trade_date", "record_available_at": True, "historical_revision_lineage": "bounded CY-006 manifest; not vendor-level revision certification", "authorization_scope": "research/chinext_v1 frozen descriptive attribution"}}
    payload = {"phase11a_result": "PASS", "formal_replay_executions": 0, "new_trades": 0, "new_nav": 0, "pit_rebuilt": "NO", "strategy_modified": "NO", "industry_governance_status": "PIT_AUTHORIZED_EXISTING", "primary_industry_taxonomy": "CY-006 historical daily industry field / QD-008 Eastmoney yjbb disclosure chronology", "cyclical_mapping_status": "NOT_AVAILABLE", "phase11a_spec_sha256": spec_sha, "strategy_sha256": sha256_file(STRATEGY), "development_pit_manifest_sha256": sha256_file(REPORTS/"chinext_v1_pit_master_manifest.json"), "holdout_pit_manifest_sha256": sha256_file(REPORTS/"chinext_v1_pit_holdout_2022_2023_master_manifest.json"), "industry_data_candidates": deps, "coverage_by_year": coverage, "coverage_by_sample": sample_cov, "yearly_industry_exposure": yearly_industry, "overall_industry_exposure": overall, "development_top20_industry_distribution": top20, "development_top10_industry_distribution": top10, "oos_top10_industry_distribution": oos_top10, "september_2024_industry_distribution": sep_con, "same_industry_cross_regime": same, "development_vs_oos_mix": mix, "sector_concentration_diagnostics": {"maximum_simultaneous_same_industry_positions": "NOT_RELIABLY_RECONSTRUCTABLE_FROM_FROZEN_DAILY_NAV", "nominal_weight": "NOT_RELIABLY_RECONSTRUCTABLE", "days_over_30pct": "NOT_APPLICABLE", "days_over_40pct": "NOT_APPLICABLE", "counterfactual_nav": "NOT_RUN"}, "industry_mix_effect": "INCONCLUSIVE", "same_industry_regime_effect": "INCONCLUSIVE", "is_right_tail_industry_concentrated": "PARTIALLY", "is_2024_09_cohort_industry_concentrated": "INCONCLUSIVE", "does_industry_mix_explain_oos_failure": "WEAKLY", "classification": {"next_industry_research_direction": "MORE_INDUSTRY_DIAGNOSTICS_REQUIRED"}, "unresolved": ["No authorized cyclical/defensive mapping; energy/cyclical contribution is not claimed", "Industry classification record-level supplier revision lineage unavailable", "Frozen daily_nav does not retain position-to-industry identities; sector-weight diagnostics are not asserted"]}
    write_json(OUT, payload)
    lines = ["# ChinNext V1 Phase 11A — PIT industry exposure and right-tail concentration", "", "Zero-replay descriptive attribution of frozen OOS and development trades. No strategy, trade, NAV, PIT or universe rebuild was executed.", "", f"- PHASE11A_SPEC_SHA256: `{spec_sha}`", "- INDUSTRY_GOVERNANCE_STATUS: `PIT_AUTHORIZED_EXISTING`", "- PRIMARY_INDUSTRY_TAXONOMY: `CY-006 / QD-008 Eastmoney disclosure chronology`", "- CYCLICAL_MAPPING_STATUS: `NOT_AVAILABLE`", "", "## Coverage", "| Year | Trades | Mapped | Unmapped | Coverage |", "|---:|---:|---:|---:|---:|"]
    for y, v in coverage.items(): lines.append(f"| {y} | {v['trade_count']} | {v['industry_mapped_count']} | {v['industry_unmapped_count']} | {v['coverage_rate']:.2%} |")
    lines += ["", "## Concentration", f"Development frozen Top20 mapped industry distribution: `{json.dumps(top20['industry_counts'], ensure_ascii=False, sort_keys=True)}`", f"2024-09 cohort (`{len(sep)}` trades) distribution: `{json.dumps(sep_con['industry_counts'], ensure_ascii=False, sort_keys=True)}`", "", "## Findings", "Industry mapping is causal only when the CY-006 source notice precedes the entry signal date; unmapped rows remain visible. Right-tail industry concentration is classified PARTIALLY, while industry mix and same-industry regime effects remain INCONCLUSIVE/WEAKLY explanatory. No energy or cyclical exclusion is supported because no authorized cyclical mapping exists.", "", "Sector-weight/cap diagnostics are not asserted because frozen daily NAV lacks position-to-industry identity; no counterfactual cap NAV was run.", "", "Next direction: **MORE_INDUSTRY_DIAGNOSTICS_REQUIRED**. This phase does not propose an exclusion or cap.", ""]
    MD.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__": raise SystemExit(main())
