#!/usr/bin/env python3
"""Render outcome-labelled, strictly pre-2022 discovery charts for V3.

The charts are development aids, not a frozen strategy.  Every market bar read
by this script is capped at 2021-12-31.  The feature panel was likewise built
from signals no later than 2021-11-30 with exits no later than 2021-12-31.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from PIL import Image, ImageDraw


ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare-broad-sell-pressure-cost-zone-demand-takeover-v3-development"
)
PANEL = ROOT / "pre2022_feature_panel.parquet"
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUTPUT = ROOT / "charts"


class ResearchError(RuntimeError):
    """Fail closed when the pre-2022 chart quarantine is violated."""


def selected_examples() -> pd.DataFrame:
    panel = pd.read_parquet(PANEL)
    for column in ("signal_date", "anchor_date", "entry_date", "exit_date"):
        panel[column] = pd.to_datetime(panel[column])
    if panel.signal_date.max() > pd.Timestamp("2021-11-30"):
        raise ResearchError("post-November-2021 signal in discovery panel")
    if panel.exit_date.max() > pd.Timestamp("2021-12-31"):
        raise ResearchError("post-2021 outcome in discovery panel")
    panel = panel.loc[panel.breadth.ge(12)].copy()
    panel["ret60_rank_pct"] = panel.groupby("signal_date").signal_ret60.rank(
        pct=True, ascending=True, method="average"
    )
    panel = panel.loc[panel.ret60_rank_pct.le(0.60)].copy()
    rows = []
    for _, part in panel.groupby("signal_date", sort=True):
        ordered = part.sort_values("net_return", kind="mergesort")
        rows.extend([ordered.iloc[0], ordered.iloc[-1]])
    result = pd.DataFrame(rows).drop_duplicates("event_id").reset_index(drop=True)
    result["example_kind"] = result.groupby("signal_date").net_return.transform(
        lambda x: np.where(x.eq(x.min()), "WORST", "BEST")
    )
    return result


def load_windows(examples: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect()
    con.register(
        "examples",
        examples[["event_id", "symbol", "signal_cal_idx", "invalid_step_cum"]],
    )
    stock = con.execute(
        f"""
        SELECT e.event_id,d.*
        FROM examples e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON d.symbol=e.symbol
         AND d.cal_idx BETWEEN e.signal_cal_idx-80 AND e.signal_cal_idx+35
         AND d.invalid_step_cum=e.invalid_step_cum
        WHERE d.trade_date<=DATE '2021-12-31'
        ORDER BY e.event_id,d.cal_idx
        """
    ).fetchdf()
    market = con.execute(
        f"""
        SELECT trade_date,
          median(step_return) AS market_ret,
          avg(CASE WHEN step_return>0 THEN 1.0 ELSE 0.0 END) AS market_up,
          causal_industry,
          median(step_return) AS industry_ret
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date<=DATE '2021-12-31'
          AND hard_valid AND current_valid AND current_day_data_tradable
          AND market_rule_valid AND corporate_action_valid
          AND NOT corporate_action_blocking AND NOT is_st
        GROUP BY GROUPING SETS ((trade_date),(trade_date,causal_industry))
        ORDER BY trade_date
        """
    ).fetchdf()
    con.close()
    stock["trade_date"] = pd.to_datetime(stock.trade_date)
    market["trade_date"] = pd.to_datetime(market.trade_date)
    if stock.trade_date.max() > pd.Timestamp("2021-12-31"):
        raise ResearchError("post-2021 stock bar entered charts")
    if market.trade_date.max() > pd.Timestamp("2021-12-31"):
        raise ResearchError("post-2021 market bar entered charts")
    return stock, market


def candles(ax: plt.Axes, part: pd.DataFrame) -> None:
    for x, row in enumerate(part.itertuples(index=False)):
        color = "#d62728" if row.coord_close >= row.coord_open else "#2ca02c"
        ax.vlines(x, row.coord_low, row.coord_high, color=color, linewidth=0.6)
        low = min(row.coord_open, row.coord_close)
        height = max(abs(row.coord_close - row.coord_open), 1e-6)
        ax.add_patch(Rectangle((x - 0.32, low), 0.64, height, color=color, alpha=0.78))


def render_one(row: pd.Series, stock: pd.DataFrame, market: pd.DataFrame, path: Path) -> None:
    part = stock.loc[stock.event_id.eq(row.event_id)].sort_values("cal_idx").copy()
    if part.empty:
        raise ResearchError(f"missing window: {row.event_id}")
    part = part.reset_index(drop=True)
    signal_x = int(part.index[part.cal_idx.eq(int(row.signal_cal_idx))][0])
    anchor_x = int(part.index[part.cal_idx.eq(int(row.anchor_cal_idx))][0])
    prior = part.loc[part.cal_idx.lt(int(row.signal_cal_idx))]
    prior20 = prior.tail(20)
    support = float(prior20.coord_low.min())
    resistance = float(prior20.coord_high.max())
    anchored = float(
        np.average(
            prior.loc[prior.cal_idx.ge(int(row.anchor_cal_idx)), "coord_close"],
            weights=prior.loc[prior.cal_idx.ge(int(row.anchor_cal_idx)), "volume"],
        )
    )

    fig, axes = plt.subplots(
        3, 1, figsize=(12, 7.2), sharex=True,
        gridspec_kw={"height_ratios": [3.6, 1.0, 1.35]},
    )
    ax, vol_ax, context_ax = axes
    candles(ax, part)
    ax.axvline(anchor_x, color="#8c564b", linestyle="--", linewidth=1.1, label="seller anchor")
    ax.axvline(signal_x, color="#9467bd", linestyle="--", linewidth=1.1, label="reclaim")
    ax.axhline(float(row.anchor_cost), color="#ff7f0e", linewidth=1.2, label="anchor-day VWAP")
    ax.axhline(anchored, color="#1f77b4", linewidth=1.0, linestyle=":", label="anchor-to-prior VWAP")
    ax.axhline(support, color="#2ca02c", linewidth=0.8, linestyle=":", label="prior20 support")
    ax.axhline(resistance, color="#d62728", linewidth=0.8, linestyle=":", label="prior20 resistance")
    ax.legend(loc="upper left", ncol=3, fontsize=7)
    ax.grid(alpha=0.15)

    colors = np.where(part.coord_close.ge(part.coord_open), "#d62728", "#2ca02c")
    vol_ax.bar(np.arange(len(part)), part.turnover_fraction, color=colors, alpha=0.65, width=0.72)
    vol_ax.axvline(signal_x, color="#9467bd", linestyle="--", linewidth=0.8)
    vol_ax.set_ylabel("turnover", fontsize=8)
    vol_ax.grid(alpha=0.12)

    dates = part[["trade_date"]].copy()
    market_daily = market.loc[market.causal_industry.isna(), ["trade_date", "market_ret", "market_up"]]
    industry_daily = market.loc[
        market.causal_industry.eq(row.causal_industry), ["trade_date", "industry_ret"]
    ]
    context = dates.merge(market_daily, on="trade_date", how="left").merge(
        industry_daily, on="trade_date", how="left"
    )
    context["market_curve"] = (1.0 + context.market_ret.fillna(0)).cumprod()
    context["industry_curve"] = (1.0 + context.industry_ret.fillna(0)).cumprod()
    context_ax.plot(context.index, context.market_curve / context.market_curve.iloc[signal_x], label="market median", linewidth=1.0)
    context_ax.plot(context.index, context.industry_curve / context.industry_curve.iloc[signal_x], label="industry median", linewidth=1.0)
    context_ax.axvline(signal_x, color="#9467bd", linestyle="--", linewidth=0.8)
    context_ax.axhline(1.0, color="black", linewidth=0.5)
    context_ax.legend(loc="upper left", fontsize=7)
    context_ax.grid(alpha=0.15)

    ticks = np.linspace(0, len(part) - 1, min(8, len(part)), dtype=int)
    context_ax.set_xticks(ticks)
    context_ax.set_xticklabels(part.iloc[ticks].trade_date.dt.strftime("%Y-%m-%d"), rotation=30, ha="right", fontsize=7)
    fig.suptitle(
        f"{row.example_kind} {row.symbol} {row.causal_industry} | signal {row.signal_date:%Y-%m-%d} "
        f"| net {row.net_return:+.2%} hold {int(row.holding_sessions)} | ret60 {row.signal_ret60:+.1%}",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def contact_sheets(paths: list[Path]) -> None:
    sheet_dir = OUTPUT / "contact_sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    thumb = (600, 360)
    for offset in range(0, len(paths), 6):
        group = paths[offset : offset + 6]
        sheet = Image.new("RGB", (thumb[0] * 2, thumb[1] * 3), "white")
        draw = ImageDraw.Draw(sheet)
        for index, path in enumerate(group):
            image = Image.open(path).convert("RGB")
            image.thumbnail((thumb[0], thumb[1] - 18))
            x = (index % 2) * thumb[0]
            y = (index // 2) * thumb[1]
            sheet.paste(image, (x, y + 18))
            draw.text((x + 4, y + 2), path.stem, fill="black")
        sheet.save(sheet_dir / f"sheet_{offset // 6 + 1:02d}.jpg", quality=90)


def main() -> None:
    examples = selected_examples()
    stock, market = load_windows(examples)
    chart_dir = OUTPUT / "individual"
    chart_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, row in examples.iterrows():
        path = chart_dir / (
            f"{index + 1:03d}_{row.example_kind}_{row.symbol.replace('.', '_')}_"
            f"{row.signal_date:%Y%m%d}.png"
        )
        render_one(row, stock, market, path)
        paths.append(path)
    contact_sheets(paths)
    print(f"rendered {len(paths)} charts and {(len(paths) + 5) // 6} sheets to {OUTPUT}")


if __name__ == "__main__":
    main()
