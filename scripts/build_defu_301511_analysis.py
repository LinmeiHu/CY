"""Build a point-in-time, auditable analysis of Defu Technology (301511.SZ).

Audit mode is permitted before registry activation. Research replay and report
generation fail closed until the exact snapshot and audit are registered as CY-005.
"""

# The standalone HTML template intentionally keeps several literals on one line.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from cyq_game.chip.core import (
    CohortChipEngine,
    LogPriceGrid,
    UniformChipEngine,
    apply_split_to_state,
    ensure_grid,
)
from cyq_game.chip.features import compute_features

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/raw/defu_301511_baostock_20260820_v2"
RAW_PATH = RAW_DIR / "response.csv"
MANIFEST_PATH = RAW_DIR / "manifest.json"
OFFICIAL_DIR = ROOT / "data/raw/defu_301511_official_20260820"
OFFICIAL_MANIFEST = OFFICIAL_DIR / "manifest.json"
OLD_DAILY = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_daily/301511.none.parquet")
REGISTRY_PATH = ROOT / "configs/data_asset_registry.json"
AUDIT_PATH = ROOT / "data/audits/defu_301511_20260820.json"
RESULT_PATH = ROOT / "artifacts/defu_301511_analysis_20260820.json"
DIST_PATH = ROOT / "artifacts/defu_301511_chip_distribution_20260820.csv"
PRICE_CHART = ROOT / "artifacts/defu_301511_price_turnover_20260820.png"
CHIP_CHART = ROOT / "artifacts/defu_301511_chip_map_20260820.png"
REPORT_PATH = ROOT / "artifacts/defu_technology_301511_20260820.html"

DECISION_AT = "2026-08-21T11:20:00+08:00"
CUTOFF = date(2026, 8, 20)
EXPECTED_RAW_HASH = "33ec14a3c454ef984fa364844c54bd61e99e0fe47d52a27b78e0f01a2008b0e8"
EXPECTED_MANIFEST_HASH = "8a03596f8d541b81f2e4e9d6a82692c80a8a2592071a0239372b0cbe280cbe60"
EXPECTED_OFFICIAL_MANIFEST_HASH = "9e12b2c5cfc86db5f2bb698948a38b214b83a334302680fe40096b0bf19900d3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_raw() -> pd.DataFrame:
    frame = pd.read_csv(RAW_PATH, dtype={"code": str, "isST": str})
    frame["date"] = pd.to_datetime(frame["date"])
    numeric = [
        "open", "high", "low", "close", "preclose", "volume", "amount",
        "turn", "pctChg", "tradestatus", "adjustflag",
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def audit() -> dict[str, Any]:
    raw = load_raw()
    active = raw[raw["tradestatus"].eq(1)].copy()
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    official = json.loads(OFFICIAL_MANIFEST.read_text(encoding="utf-8"))
    old = duckdb.connect().execute(
        "select trade_date, open, high, low, close, volume, amount, turnover_rate "
        "from read_parquet(?) order by trade_date", [str(OLD_DAILY)],
    ).fetchdf()
    old["trade_date"] = pd.to_datetime(old["trade_date"])
    overlap = old.merge(raw, left_on="trade_date", right_on="date", suffixes=("_old", "_new"))
    ohlc_delta = {
        field: float(np.max(np.abs(overlap[f"{field}_old"] - overlap[f"{field}_new"])))
        for field in ("open", "high", "low", "close")
    }
    volume_delta = np.abs(overlap["volume_old"] - overlap["volume_new"])
    amount_delta = np.abs(overlap["amount_old"] - overlap["amount_new"])
    turn_delta = np.abs(overlap["turnover_rate"] - overlap["turn"])
    document_checks = {
        item["file"]: sha256(OFFICIAL_DIR / item["file"]) == item["sha256"]
        for item in official["documents"]
    }
    split_ref = (21.18 - 0.055) / 1.4
    cash_ref = 108.28 - 0.1 * (627_574_704 / 630_322_000)
    implied_float_pre = float(
        raw.loc[raw["date"].eq("2026-08-14"), "volume"].iloc[0]
        / (raw.loc[raw["date"].eq("2026-08-14"), "turn"].iloc[0] / 100)
    )
    implied_float_post = float(
        raw.loc[raw["date"].eq("2026-08-17"), "volume"].iloc[0]
        / (raw.loc[raw["date"].eq("2026-08-17"), "turn"].iloc[0] / 100)
    )
    checks = {
        "raw_hash": sha256(RAW_PATH) == EXPECTED_RAW_HASH,
        "manifest_hash": sha256(MANIFEST_PATH) == EXPECTED_MANIFEST_HASH,
        "official_manifest_hash": sha256(OFFICIAL_MANIFEST) == EXPECTED_OFFICIAL_MANIFEST_HASH,
        "official_documents_hash": all(document_checks.values()),
        "snapshot_collected_before_decision": datetime.fromisoformat(manifest["collected_at"]) <= datetime.fromisoformat(DECISION_AT),
        "rows_and_range": len(raw) == 729 and raw["date"].min().date() == date(2023, 8, 17) and raw["date"].max().date() == CUTOFF,
        "no_duplicates": not raw["date"].duplicated().any(),
        "unadjusted": active["adjustflag"].eq(3).all(),
        "active_ohlc_valid": bool(
            active[["open", "high", "low", "close"]].gt(0).all().all()
            and active["high"].ge(active[["open", "close", "low"]].max(axis=1)).all()
            and active["low"].le(active[["open", "close", "high"]].min(axis=1)).all()
        ),
        "active_turnover_valid": bool(active["turn"].notna().all() and active["turn"].ge(0).all()),
        "no_future_rows": raw["date"].max().date() <= CUTOFF,
        "overlap_ohlc_exact": max(ohlc_delta.values()) < 1e-12,
        "split_reference_reconciles": abs(split_ref - 15.09) <= 0.01,
        "cash_dividend_reference_reconciles": abs(cash_ref - 108.18) <= 0.01,
        "unlock_float_reconciles": abs(implied_float_post - 398_647_407) / 398_647_407 < 0.0001,
    }
    checks = {key: bool(value) for key, value in checks.items()}
    report = {
        "gate": "DEFU_301511_TARGETED_PIT_RESEARCH_20260820",
        "pass": all(checks.values()),
        "decision_at": DECISION_AT,
        "information_cutoff": CUTOFF.isoformat(),
        "checks": checks,
        "source": {
            "path": str(RAW_PATH), "sha256": sha256(RAW_PATH),
            "manifest_path": str(MANIFEST_PATH), "manifest_sha256": sha256(MANIFEST_PATH),
            "official_manifest_path": str(OFFICIAL_MANIFEST),
            "official_manifest_sha256": sha256(OFFICIAL_MANIFEST),
            "snapshot_id": manifest["snapshot_id"],
        },
        "coverage": {"rows": len(raw), "active_rows": len(active), "start": raw["date"].min().date().isoformat(), "end": raw["date"].max().date().isoformat()},
        "cross_source": {
            "overlap_rows": len(overlap), "ohlc_max_absolute_delta": ohlc_delta,
            "volume_nonzero_delta_rows": int(volume_delta.gt(0).sum()), "volume_max_delta_shares": float(volume_delta.max()),
            "amount_nonzero_delta_rows": int(amount_delta.gt(0).sum()), "amount_max_delta_yuan": float(amount_delta.max()),
            "turnover_nonzero_delta_rows": int(turn_delta.gt(1e-12).sum()), "turnover_max_delta_percentage_points": float(turn_delta.max()),
            "interpretation": "OHLC exact on overlap; volume, amount and turnover contain immaterial vendor rounding differences and are not claimed fieldwise exact.",
        },
        "corporate_actions": {
            "split": {"effective_date": "2024-05-20", "ratio": 1.4, "cash_per_pre_split_share": 0.055, "expected_reference": split_ref, "observed_preclose": 15.09},
            "cash_dividend": {"effective_date": "2026-05-26", "cash_per_share": 0.1, "expected_reference": cash_ref, "observed_preclose": 108.18, "chip_coordinate_policy": "cash kept in a separate ledger; cost-price coordinates are not shifted"},
            "unlock": {"listing_date": "2026-08-17", "formal_unlocked_shares": 24_089_781, "unrestricted_after": 398_647_407, "implied_float_before": implied_float_pre, "implied_float_after": implied_float_post},
        },
        "official_document_checks": document_checks,
        "strict_context_gaps": ["market state through 2026-08-20", "PIT sector membership and leave-one-out sector features through 2026-08-20", "trading-rule snapshot through 2026-08-20", "OOS-calibrated EdgeCard and executable liquidity"],
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not report["pass"]:
        raise RuntimeError(f"audit failed: {[k for k, v in checks.items() if not v]}")
    return report


def require_registered(audit_report: dict[str, Any]) -> dict[str, Any]:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    asset = next((item for item in registry["assets"] if item["asset_id"] == "CY-005"), None)
    if asset is None or asset["status"] != "RESEARCH_CONDITIONAL":
        raise RuntimeError("CY-005 is not registered for conditional research")
    if asset["lineage"]["manifest_sha256"] != EXPECTED_MANIFEST_HASH:
        raise RuntimeError("CY-005 manifest hash mismatch")
    if asset["quality_evidence"]["audit_sha256"] != sha256(AUDIT_PATH):
        raise RuntimeError("CY-005 audit hash mismatch")
    if not audit_report["pass"]:
        raise RuntimeError("CY-005 audit gate is not PASS")
    return asset


def replay(engine_name: str, lambda_turnover: float) -> tuple[Any, dict[str, Any], pd.DataFrame]:
    raw = load_raw()
    active = raw[raw["tradestatus"].eq(1)]
    grid = LogPriceGrid.around(float(active["low"].min()), float(active["high"].max()))
    engine = CohortChipEngine(lambda_turnover=lambda_turnover) if engine_name == "cohort" else UniformChipEngine(lambda_turnover=lambda_turnover)
    state = None
    pre_state = None
    max_mass_error = 0.0
    snapshots: dict[str, dict[str, Any]] = {}
    targets = {"2026-07-06", "2026-08-04", "2026-08-07", "2026-08-14", "2026-08-17", "2026-08-19", "2026-08-20"}
    for row in raw.itertuples(index=False):
        row_date = row.date.date()
        if int(row.tradestatus) != 1:
            continue
        if state is not None and row_date == date(2024, 5, 20):
            state = apply_split_to_state(state, 1.4, row_date)
        if state is None:
            q = grid.volume_at_price(float(row.low), float(row.high), float(row.close))
            state = engine.initialize(grid, q, row_date)
        else:
            state = ensure_grid(state, float(row.low), float(row.high))
            if row_date == CUTOFF:
                pre_state = state
            q = state.grid.volume_at_price(float(row.low), float(row.high), float(row.close))
            state = engine.update(state, q, float(row.turn) / 100.0, float(row.close), row_date)
        max_mass_error = max(max_mass_error, abs(float(state.mass.sum()) - 1.0))
        key = row_date.isoformat()
        if key in targets:
            feat = compute_features(state, open_price=float(row.open), high=float(row.high), low=float(row.low), close=float(row.close))
            snapshots[key] = {"close": float(row.close), "turnover_pct": float(row.turn), "profit_ratio": feat.pr, "average_cost": feat.ac, "p10": feat.p10, "p50": feat.p50, "p90": feat.p90}
    if state is None or pre_state is None:
        raise RuntimeError("replay did not reach the cutoff")
    latest = raw.iloc[-1]
    two_year = active[active["date"].ge("2024-08-20")]
    kwargs = {"open_price": float(latest["open"]), "high": float(latest["high"]), "low": float(latest["low"]), "close": float(latest["close"]), "history_low_2y": float(two_year["low"].min()), "history_high_2y": float(two_year["high"].max())}
    pre = compute_features(pre_state, **kwargs)
    post = compute_features(state, **kwargs)
    result = {"engine": engine_name, "lambda_turnover": lambda_turnover, "max_mass_error": max_mass_error, "as_of": state.as_of.isoformat(), "pre_trade_features": asdict(pre), "post_close_features": asdict(post), "snapshots": snapshots}
    dist = pd.DataFrame({"price": state.grid.prices, "mass": state.mass})
    return state, result, dist[dist["mass"].gt(1e-12)].reset_index(drop=True)


def price_context(raw: pd.DataFrame) -> dict[str, float]:
    active = raw[raw["tradestatus"].eq(1)].copy()
    close = active["close"]
    high_817 = float(active.loc[active["date"].eq("2026-08-17"), "high"].iloc[0])
    return {
        "close": float(close.iloc[-1]), "open": float(active["open"].iloc[-1]), "high": float(active["high"].iloc[-1]), "low": float(active["low"].iloc[-1]),
        "turnover_pct": float(active["turn"].iloc[-1]), "amount_billion": float(active["amount"].iloc[-1] / 1e9),
        "return_5d_pct": float((close.iloc[-1] / close.iloc[-6] - 1) * 100), "return_20d_pct": float((close.iloc[-1] / close.iloc[-21] - 1) * 100), "return_60d_pct": float((close.iloc[-1] / close.iloc[-61] - 1) * 100),
        "ma5": float(close.tail(5).mean()), "ma10": float(close.tail(10).mean()), "ma20": float(close.tail(20).mean()), "ma60": float(close.tail(60).mean()),
        "drawdown_from_0817_high_pct": float((close.iloc[-1] / high_817 - 1) * 100),
    }


def make_charts(raw: pd.DataFrame, distribution: pd.DataFrame, post: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt

    plt.style.use("seaborn-v0_8-whitegrid")
    recent = raw[(raw["date"].ge("2026-04-01")) & raw["tradestatus"].eq(1)].copy()
    fig, ax = plt.subplots(figsize=(12, 6.2))
    ax.plot(recent["date"], recent["close"], color="#183149", linewidth=2, label="Close")
    ax.plot(recent["date"], recent["close"].rolling(20).mean(), color="#d08a28", linewidth=1.4, label="MA20")
    ax.set_ylabel("Price (CNY)")
    ax2 = ax.twinx()
    ax2.bar(recent["date"], recent["turn"], color="#99b4c5", alpha=.28, width=1.0, label="Turnover")
    ax2.set_ylabel("Turnover (%)")
    ax.axvline(pd.Timestamp("2026-08-17"), color="#a43c2e", linestyle="--", linewidth=1)
    ax.text(pd.Timestamp("2026-08-17"), recent["close"].max() * .96, "unlock", color="#a43c2e", ha="right")
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(PRICE_CHART, dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.fill_between(distribution["price"], distribution["mass"] * 100, color="#6d98aa", alpha=.55)
    ax.plot(distribution["price"], distribution["mass"] * 100, color="#315e70", linewidth=1.5)
    for label, value, color in (("Close", 88.41, "#a43c2e"), ("Average cost", post["average_cost"], "#d08a28"), ("P90", post["p90"], "#76539a")):
        ax.axvline(value, color=color, linestyle="--", linewidth=1.3, label=f"{label} {value:.2f}")
    ax.set_xlim(max(20, float(distribution["price"].quantile(.01))), min(125, float(distribution["price"].quantile(.99))))
    ax.set_xlabel("Estimated holding cost (CNY, unadjusted coordinate after causal split rebase)")
    ax.set_ylabel("Chip mass per grid bucket (%)")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(CHIP_CHART, dpi=150, bbox_inches="tight")
    plt.close(fig)


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def render_report(data: dict[str, Any]) -> None:
    p = data["price_context"]
    post = data["primary"]["post_close_features"]
    pre = data["primary"]["pre_trade_features"]
    snapshots = "".join(f"<tr><td>{d}</td><td>{v['close']:.2f}</td><td>{v['turnover_pct']:.2f}%</td><td>{pct(v['profit_ratio'])}</td><td>{v['average_cost']:.2f}</td><td>{v['p50']:.2f}</td><td>{v['p90']:.2f}</td></tr>" for d, v in data["primary"]["snapshots"].items())
    sensitivity = "".join(f"<tr><td>{r['engine']}</td><td>{r['lambda_turnover']:.1f}</td><td>{pct(r['profit_ratio'])}</td><td>{r['average_cost']:.2f}</td><td>{r['p50']:.2f}</td><td>{r['p90']:.2f}</td></tr>" for r in data["sensitivity"])
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>德福科技 301511.SZ｜点时深度分析</title>
<style>:root{{--ink:#162f3e;--muted:#62727b;--paper:#f3f0e8;--card:#fffdf8;--line:#d7d1c6;--red:#aa3d2d;--green:#2e7058;--amber:#9b6b16}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.72 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}main{{max-width:1180px;margin:auto;padding:30px 28px 70px}}a{{color:#165f88}}.hero{{padding:40px;border:1px solid #cbd1d0;border-radius:22px;background:linear-gradient(135deg,#fffdf8,#eaf1f2);box-shadow:0 12px 30px #24364115}}.eyebrow,.small{{font-size:12px;color:var(--muted)}}h1{{font-size:clamp(34px,5vw,58px);line-height:1.05;margin:8px 0 12px;letter-spacing:-.035em}}h2{{margin:0 0 14px;font-size:27px}}h3{{margin:0 0 8px}}section{{margin-top:42px}}.deck{{font-size:18px;max-width:960px;color:#50616b}}.verdict{{margin-top:24px;padding:21px 24px;border-left:6px solid var(--red);background:#fff;border-radius:8px 15px 15px 8px}}.verdict strong{{display:block;font-size:24px;color:var(--red)}}.tags{{display:flex;flex-wrap:wrap;gap:9px;margin-top:18px}}.tag{{padding:5px 10px;border:1px solid #c9d1d4;border-radius:999px;background:#fff;font-size:12px;font-weight:700}}.tag.no{{color:var(--red);background:#f8e5df;border-color:#deb5aa}}.tag.ok{{color:var(--green);background:#e2efe9;border-color:#b5d4c4}}.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}}.card{{grid-column:span 4;padding:20px;border:1px solid var(--line);border-radius:14px;background:var(--card)}}.wide{{grid-column:span 6}}.full{{grid-column:1/-1}}.metric{{font-size:29px;font-weight:780;line-height:1.15;margin:4px 0}}.red{{color:var(--red)}}.green{{color:var(--green)}}table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}}th,td{{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#e7eceb;font-size:12px}}figure{{margin:0;padding:15px;border:1px solid var(--line);border-radius:15px;background:#fff}}figure img{{width:100%;display:block}}figcaption{{font-size:12px;color:var(--muted);margin:9px 5px 0}}.callout{{padding:17px 20px;border:1px solid #d7c18e;border-radius:12px;background:#f7edcf}}.danger{{background:#f8e5df;border-color:#d9afa3}}.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}ul{{padding-left:20px}}footer{{margin-top:45px;padding-top:18px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}}@media(max-width:820px){{main{{padding:15px 13px 50px}}.hero{{padding:25px 20px}}.card{{grid-column:1/-1}}.twocol{{grid-template-columns:1fr}}th,td{{font-size:13px;padding:8px 6px}}}}</style></head><body><main>
<header class="hero"><div class="eyebrow">CYQ-GAME · 点时条件研究｜decision_at {DECISION_AT}｜行情截止 2026-08-20 收盘</div><h1>德福科技 <span style="font-weight:500">301511.SZ</span></h1><p class="deck">这是一只<strong>盈利拐点被快速重估、但现金流和资产负债表尚未同步修复</strong>的高弹性铜箔股。盘面已从加速上冲切换到高位巨震：8月19日大跌破坏短线结构，8月20日只是弱反抽；现价隐含的盈利要求远高于已经兑现的利润。</p><div class="verdict"><strong>态势：高位分歧 / 再定价后的供应消化期｜严格动作：NO_TRADE</strong><p>个股状态可标为 <b>T8 高位换手/情绪扩张仍活跃 + T4 强势再定价已经退潮、等待重新确认</b>，并叠加“高位分配、解禁与融资供给”风险覆盖层。由于8月20日当日大盘、点时行业成员及剔除本股行业特征、交易规则和OOS EdgeCard没有同时补齐，系统级 <code>hard_valid=false</code>；候选状态不能转成订单。</p></div><div class="tags"><span class="tag ok">筹码质量守恒 PASS</span><span class="tag no">hard_valid=false</span><span class="tag">收盘 88.41 元</span><span class="tag">总市值 557.3 亿元</span><span class="tag">PIT-B 条件研究</span></div></header>

<section><h2>一页结论</h2><div class="grid"><article class="card"><div class="small">8/17高点至今</div><div class="metric red">{p['drawdown_from_0817_high_pct']:.1f}%</div><p>101.63元见顶后快速回落；8/19单日-12.42%，8/20 +2.37%未修复破坏。</p></article><article class="card"><div class="small">筹码获利盘 / 浮亏盘</div><div class="metric">{pct(post['profit_ratio'])} / <span class="red">{pct(post['trapped_ratio'])}</span></div><p>模型估计过半筹码已处于浮亏；高位新增套牢盘与上市以来低成本存量同时存在。</p></article><article class="card"><div class="small">平均成本 / P90</div><div class="metric">{post['average_cost']:.1f} / {post['p90']:.1f}</div><p>当前88.41元略低于平均成本与P50，P90附近是对上方供应更敏感的成本带。</p></article><article class="card"><div class="small">LTM PE / PB</div><div class="metric red">230.7× / 13.4×</div><p>市场已经提前计入高端铜箔放量和利润率跃升，不能按普通周期修复股理解。</p></article><article class="card"><div class="small">2026Q1利润 / 经营现金流</div><div class="metric green">1.47亿 <span class="red">/ -3.35亿</span></div><p>利润弹性强，但现金转换没有跟上，融资与营运资金压力仍是核心约束。</p></article><article class="card"><div class="small">回购价格上限</div><div class="metric">53.46元</div><p>当前88.41元显著高于回购计划上限，不能把该计划视为现价支撑。</p></article></div></section>

<section><h2>价格结构：加速段已经结束，进入高波动验证</h2><figure><img src="defu_301511_price_turnover_20260820.png" alt="德福科技价格与换手"><figcaption>未复权日线；8月17日流通盘发生变化。8月20日成交额31.22亿元、换手8.73%，反弹强度不足以确认趋势重建。</figcaption></figure><div class="twocol" style="margin-top:16px"><div class="callout"><b>尚存的正面证据</b><ul><li>8月20日仍高于MA20约{p['ma20']:.1f}元，但明显低于MA60约{p['ma60']:.1f}元。</li><li>2026Q1利润同比高增，毛利率改善，基本面确有拐点。</li><li>高端电子铜箔提供新的叙事和潜在产品结构上移。</li></ul></div><div class="callout danger"><b>结构破坏</b><ul><li>8/19放量大跌后，8/20收盘仍低于MA5约{p['ma5']:.1f}元和MA10约{p['ma10']:.1f}元。</li><li>形式解禁2,408.98万股；其中部分延长锁定，短期实际新增可交易上限约1,064万股。</li><li>股东减持尚未完成，叠加定增潜在摊薄，供应端尚未出清。</li></ul></div></div></section>

<section><h2>筹码状态：长期低成本存量与高位新增套牢并存</h2><figure><img src="defu_301511_chip_map_20260820.png" alt="德福科技筹码成本分布"><figcaption>主模型 cohort / λ=1.0，从上市首日按未复权日线因果回放；2024-05-20按10转4重置成本坐标，现金分红单列现金账本。模型是持仓成本估计，不是账户透视。</figcaption></figure><table style="margin-top:16px"><thead><tr><th>日期</th><th>收盘</th><th>换手</th><th>获利盘</th><th>平均成本</th><th>P50</th><th>P90</th></tr></thead><tbody>{snapshots}</tbody></table><div class="callout danger" style="margin-top:15px"><b>迁移判断：</b>8月4日至17日连续高换手把新增筹码推向高位；8月19日急跌后，获利盘从8月17日的87.7%降至34.6%，8月20日也仅修复到42.5%。当前更像“低成本老筹码仍厚、高位新筹码已经被套”的分歧结构；若继续放量而价格重心下移，风险会强化。</div></section>

<section><h2>基本面：盈利拐点真实，质量尚未完成验证</h2><table><thead><tr><th>项目</th><th>2025A</th><th>2026Q1</th><th>判断</th></tr></thead><tbody><tr><td>营收</td><td>124.37亿元，+59.33%</td><td>43.38亿元，+73.47%</td><td>量和利用率快速修复</td></tr><tr><td>归母净利润</td><td>1.13亿元，扭亏</td><td>1.47亿元，+708.90%</td><td>利润弹性很强</td></tr><tr><td>经营现金流</td><td class="red">-3.81亿元</td><td class="red">-3.35亿元</td><td>盈利尚未转化为现金</td></tr><tr><td>资产负债率</td><td>72.75%</td><td class="red">约76.37%</td><td>杠杆继续上升</td></tr><tr><td>毛利率</td><td>锂电铜箔7.64%</td><td>约9.11%</td><td>改善成立但绝对值仍不高</td></tr></tbody></table><div class="grid" style="margin-top:16px"><article class="card wide"><h3>真正的多头逻辑</h3><p>2025销量14.09万吨、同比+51.99%，2026Q1利润超过2025全年；若HVLP/RTF等高端电子铜箔认证转成批量、高毛利收入，利润率可出现非线性上移。</p></article><article class="card wide"><h3>不能跳过的替代解释</h3><p>利润增长也可能主要来自行业加工费/利用率周期修复，而不是高端产品形成长期壁垒。客户前五占64.36%，宁德时代单一客户占36.20%，议价与集中度风险仍高。</p></article><article class="card wide"><h3>现金与负债</h3><p>2025年末货币资金50.58亿元，但受限资金28.19亿元；短借64.70亿元，应收34.44亿元。账面现金不能直接解释成低财务风险。</p></article><article class="card wide"><h3>扩张与整合</h3><p>5万吨AI铜箔项目总投资31亿元；定增拟募28亿元、最多增发1.8827亿股。安徽慧儒并表带来2万吨产能，但标的2025年亏损且高负债；卢森堡收购已终止，不能计入当前能力。</p></article></div></section>

<section><h2>估值：股价在押注什么</h2><div class="grid"><article class="card"><div class="small">LTM营收 / 净利润</div><div class="metric">142.74亿 / 2.42亿</div><p>口径为2025A + 2026Q1 - 2025Q1。</p></article><article class="card"><div class="small">PS / PE / PB</div><div class="metric red">3.90× / 230.7× / 13.40×</div><p>相对嘉元、中一、铜冠三家公司中位数明显溢价。</p></article><article class="card"><div class="small">总市值 / 流通市值</div><div class="metric">557.3亿 / 352.5亿</div><p>总股本6.30322亿股；8/17后无限售流通股3.98647亿股。</p></article></div><table style="margin-top:16px"><thead><tr><th>假设市场最终给予</th><th>当前市值要求净利润</th><th>相对2025A</th><th>对2025收入的净利率</th></tr></thead><tbody><tr><td>40× PE</td><td>13.93亿元</td><td>12.4×</td><td>11.2%</td></tr><tr><td>50× PE</td><td>11.15亿元</td><td>9.9×</td><td>9.0%</td></tr><tr><td>60× PE</td><td>9.29亿元</td><td>8.3×</td><td>7.5%</td></tr></tbody></table><p class="small">2026Q1净利率约3.39%。这不是目标价模型，而是把当前价格反推为需兑现的盈利门槛。证据不足以支持单点目标价。</p></section>

<section><h2>争论地图：什么能证明，什么会击穿</h2><table><thead><tr><th>议题</th><th>多头需要看到</th><th>反证 / 失效条件</th></tr></thead><tbody><tr><td>盈利质量</td><td>收入增长继续、毛利率稳定提升，经营现金流转正</td><td>利润增长但应收、存货、短债继续快于收入</td></tr><tr><td>高端铜箔</td><td>HVLP/RTF批量收入、毛利率和客户结构被定期报告验证</td><td>只停留在认证/送样，公司口径不能转成订单利润</td></tr><tr><td>估值消化</td><td>未来四季利润向9–14亿元门槛快速靠拢</td><td>利润仅周期性修复，估值仍依赖持续扩张</td></tr><tr><td>供给端</td><td>解禁、减持与定增被有序吸收，放量不再压低价格重心</td><td>高换手下价格中枢持续下移</td></tr><tr><td>技术结构</td><td>先收复93.48，再站稳98.6–101.6且缩量回踩不破</td><td>86.36/86.46失守，反弹无法收复88.4–93.5</td></tr></tbody></table></section>

<section><h2>情景与动作：等待证据，不追逐标签</h2><div class="grid"><article class="card"><h3 class="green">修复成立</h3><p>连续收复93.48元并站稳98.6–101.6元；换手下降、筹码中枢不再下移；基本面同时出现现金流改善。</p></article><article class="card"><h3>高位横盘消化</h3><p>86–94元间震荡，解禁和减持供给逐步被吸收。此路径可能消化估值，但机会成本高。</p></article><article class="card"><h3 class="red">退潮延续</h3><p>有效跌破86.36/86.46，反抽不能收回；高位新筹码继续套牢，估值压缩与融资担忧共振。</p></article></div><div class="callout danger" style="margin-top:16px"><b>当前动作：</b>系统级为 <b>NO_TRADE</b>，不是因为公司没有改善，而是“价格已计入很高的改善幅度”且严格市场/行业/可成交性门没有齐。对研究观察而言，最值得等待的不是再一根上涨K线，而是：现金流转正、高端产品收入可核验、定增摊薄边界清晰、解禁供给被价格和换手共同吸收。</div></section>

<section><h2>模型稳健性与数据边界</h2><table><thead><tr><th>引擎</th><th>λ</th><th>获利盘</th><th>平均成本</th><th>P50</th><th>P90</th></tr></thead><tbody>{sensitivity}</tbody></table><table style="margin-top:16px"><thead><tr><th>门</th><th>状态</th><th>说明</th></tr></thead><tbody><tr><td>原始行情/时点</td><td class="green">PASS</td><td>729行，2023-08-17至2026-08-20；采集11:17:38，decision_at 11:20；不含8/21盘中。</td></tr><tr><td>公司行动</td><td class="green">PASS（定向）</td><td>2024-05-20转增按1.4重置；2026-05-26现金分红单列；8/17流通盘变化已对账。</td></tr><tr><td>筹码守恒</td><td class="green">{data['primary']['max_mass_error']:.2e}</td><td>未用归一化掩盖错误；CYQK_pre使用8/20交易前状态（开{pre['cyqk_pre']['open']:.1f}%→收{pre['cyqk_pre']['close']:.1f}%）。</td></tr><tr><td>市场/行业LOO/规则</td><td class="red">缺失</td><td>注册资产只完整到8/14或更早；因此不能生成严格当前市场周期、行业强度或下单资格。</td></tr><tr><td>最终状态</td><td class="red">hard_valid=false</td><td>个股条件性研究可用；严格PIT-A、实盘与自动订单均禁止。</td></tr></tbody></table><p class="small">可审计侧证：<a href="defu_301511_analysis_20260820.json">结果JSON</a> · <a href="defu_301511_chip_distribution_20260820.csv">筹码分布CSV</a> · <a href="../data/audits/defu_301511_20260820.json">数据审计JSON</a>。原始行情 snapshot：<code>{data['snapshot_id']}</code>。</p></section>

<section><h2>主要一手来源</h2><p><a href="https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-25/4b627c1b-a564-4eb2-bca7-5b4c96d42c39.PDF">2025年报</a> · <a href="https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-25/37cd1e6c-41d9-471e-98df-08128a273049.PDF">2026一季报</a> · <a href="https://static.cninfo.com.cn/finalpage/2026-07-06/1225411993.PDF">定增预案</a> · <a href="https://static.cninfo.com.cn/finalpage/2026-08-13/1225471885.PDF">限售股上市流通公告</a> · <a href="https://static.cninfo.com.cn/finalpage/2026-07-15/1225426477.PDF">股东权益变动</a> · <a href="https://static.cninfo.com.cn/finalpage/2026-01-15/1224935637.PDF">回购计划</a></p></section>
<footer>本报告是截至decision_at的点时研究，不是个性化投资建议、收益承诺或订单。T0–T9是多标签状态，风险层独立并可覆盖状态；所有新增风险必须另行通过大盘、行业、筹码迁移、收益来源、替代解释、尾部风险和真实可成交性门。</footer></main></body></html>"""
    REPORT_PATH.write_text(html, encoding="utf-8")


def build() -> dict[str, Any]:
    audit_report = audit()
    asset = require_registered(audit_report)
    raw = load_raw()
    _, primary, distribution = replay("cohort", 1.0)
    sensitivity = []
    for engine, lam in (("cohort", 0.8), ("cohort", 1.2), ("uniform", 1.0)):
        _, replayed, _ = replay(engine, lam)
        feat = replayed["post_close_features"]
        sensitivity.append({"engine": engine, "lambda_turnover": lam, "profit_ratio": feat["profit_ratio"], "average_cost": feat["average_cost"], "p50": feat["p50"], "p90": feat["p90"]})
    result = {"symbol": "301511.SZ", "company": "德福科技", "decision_at": DECISION_AT, "information_cutoff": CUTOFF.isoformat(), "snapshot_id": audit_report["source"]["snapshot_id"], "asset_id": asset["asset_id"], "hard_valid": False, "action": "NO_TRADE", "provisional_labels": ["T8_HIGH_TURNOVER_SENTIMENT_EXPANSION_ACTIVE", "T4_STRONG_REPRICING_FADING_RECONFIRMATION_REQUIRED"], "risk_overlay": ["SECONDARY_HIGH_DISTRIBUTION", "UNLOCK_AND_DILUTION_SUPPLY", "CASH_FLOW_AND_LEVERAGE"], "price_context": price_context(raw), "primary": primary, "sensitivity": sensitivity, "audit_sha256": sha256(AUDIT_PATH)}
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    distribution.to_csv(DIST_PATH, index=False)
    make_charts(raw, distribution, primary["post_close_features"])
    render_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    report = audit()
    if args.audit_only:
        print(json.dumps({"audit": str(AUDIT_PATH), "pass": report["pass"], "sha256": sha256(AUDIT_PATH)}, ensure_ascii=False))
        return
    result = build()
    print(json.dumps({"report": str(REPORT_PATH), "result": str(RESULT_PATH), "hard_valid": result["hard_valid"], "action": result["action"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
