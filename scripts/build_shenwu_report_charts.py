"""Build repaired price/turnover and chip-distribution charts for 000820.SZ."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "configs/data_asset_registry.json"
RAW = ROOT / "data/raw/shenwu_000820_repair_20260820/baostock_daily/response.csv"
CHIPS = ROOT / "artifacts/shenwu_000820_chip_distribution_20260820.csv"
RESULT = ROOT / "artifacts/shenwu_000820_chip_result_20260820.json"
PRICE_OUTPUT = ROOT / "artifacts/shenwu_000820_price_turnover.png"
CHIP_OUTPUT = ROOT / "artifacts/shenwu_000820_chip_map.png"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_registered() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    asset = next(item for item in registry["assets"] if item["asset_id"] == "CY-004")
    expected = asset["lineage"]["response_sha256"]
    if sha256(RAW) != expected:
        raise RuntimeError("CY-004 hash mismatch; refusing silent data substitution")


def style_axes(*axes: plt.Axes) -> None:
    for axis in axes:
        axis.set_facecolor("#f7f3eb")
        axis.spines[["top", "right"]].set_visible(False)
        axis.grid(axis="y", color="#d8d1c5", linewidth=0.7, alpha=0.75)


def build_price_chart(frame: pd.DataFrame) -> None:
    recent = frame.loc[frame["date"] >= "2026-01-01"].copy()
    recent["ma20"] = recent["close"].rolling(20).mean()
    fig, (ax_price, ax_turn) = plt.subplots(
        2, 1, figsize=(12.8, 6.9), sharex=True,
        gridspec_kw={"height_ratios": [2.25, 1]},
    )
    fig.patch.set_facecolor("#f7f3eb")
    style_axes(ax_price, ax_turn)
    ax_price.plot(recent.date, recent.close, color="#17324d", linewidth=2.1, label="收盘价")
    ax_price.plot(recent.date, recent.ma20, color="#b9892e", linewidth=1.4, label="MA20")
    ax_price.axvline(pd.Timestamp("2026-07-30"), color="#41785f", linestyle="--", linewidth=1.2)
    ax_price.annotate(
        "摘帽复牌\n7月30日",
        xy=(pd.Timestamp("2026-07-30"), 3.20),
        xytext=(pd.Timestamp("2026-06-12"), 4.1),
        arrowprops={"arrowstyle": "->", "color": "#41785f"}, color="#315c49",
    )
    ax_price.annotate(
        "高换手峰值\n8月4日 4.26元 / 32.30%",
        xy=(pd.Timestamp("2026-08-04"), 4.26),
        xytext=(pd.Timestamp("2026-05-18"), 4.65),
        arrowprops={"arrowstyle": "->", "color": "#a43c2e"}, color="#8d3328",
    )
    ax_price.scatter(pd.Timestamp("2026-08-20"), 3.40, s=48, color="#a43c2e", zorder=4)
    ax_price.set_ylabel("未复权收盘价（元）")
    ax_price.legend(loc="upper left", frameon=False, ncol=2)
    ax_turn.bar(recent.date, recent.turn, width=1.0, color="#6c899b", alpha=0.88)
    ax_turn.set_ylabel("换手率（%）")
    ax_turn.set_xlabel("交易日")
    ax_turn.set_ylim(bottom=0)
    fig.suptitle(
        "神雾节能 000820.SZ｜摘帽脉冲后快速退潮",
        x=0.07, ha="left", fontsize=16, fontweight="bold", color="#17324d",
    )
    fig.text(
        0.07, 0.925,
        "来源：注册修复资产 CY-004；截至 2026-08-20 收盘。价格与换手仅描述交易事实。",
        color="#5f6470",
    )
    fig.tight_layout(rect=(0.04, 0.04, 0.98, 0.90))
    fig.savefig(PRICE_OUTPUT, dpi=180, bbox_inches="tight")
    plt.close(fig)


def build_chip_chart() -> None:
    chips = pd.read_csv(CHIPS)
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    features = result["primary"]["post_close_features"]
    close = result["price_context"]["close"]
    mask = (chips.price >= 2.65) & (chips.price <= 4.65)
    plot = chips.loc[mask].copy()
    fig, ax = plt.subplots(figsize=(12.8, 5.7))
    fig.patch.set_facecolor("#f7f3eb")
    style_axes(ax)
    ax.fill_between(plot.price, plot.mass, color="#6d8da0", alpha=0.55)
    ax.plot(plot.price, plot.mass, color="#31566f", linewidth=1.6)
    lines = [
        (close, "#a43c2e", "现价 3.40"),
        (features["average_cost"], "#b9892e", "平均成本 3.71"),
        (features["p50"], "#704f8f", "成本中位 3.72"),
        (features["p90"], "#8f3f52", "P90 4.11"),
    ]
    ymax = plot.mass.max()
    for price, color, label in lines:
        ax.axvline(price, color=color, linestyle="--", linewidth=1.35)
        ax.text(price + 0.012, ymax * 0.92, label, rotation=90, va="top", color=color, fontsize=9)
    ax.axvspan(3.33, 3.40, color="#4d8b68", alpha=0.11, label="近端承接区 3.33–3.40")
    ax.axvspan(3.69, 3.76, color="#b9892e", alpha=0.12, label="中央压力区 3.69–3.76")
    ax.axvspan(4.07, 4.11, color="#a43c2e", alpha=0.12, label="重压力区 4.07–4.11")
    ax.set_xlabel("持仓成本价（元）")
    ax.set_ylabel("估计筹码质量（离散网格）")
    ax.legend(loc="upper left", frameon=False, ncol=3)
    ax.set_title(
        "2026-08-20 收盘后筹码成本分布｜84.07% 处于浮亏",
        loc="left",
        fontsize=16,
        fontweight="bold",
    )
    fig.text(
        0.125, 0.89,
        "主模型：cohort / λ=1.0；总质量守恒误差 7.99×10⁻¹⁵。筹码是成本状态估计，不是账户透视。",
        color="#5f6470",
    )
    fig.tight_layout(rect=(0.04, 0.04, 0.98, 0.86))
    fig.savefig(CHIP_OUTPUT, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    assert_registered()
    frame = pd.read_csv(RAW)
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ("close", "turn"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[(frame.tradestatus == 1) & frame.close.notna()].copy()
    PRICE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": ["Arial Unicode MS", "PingFang SC", "Heiti TC", "DejaVu Sans"],
        "axes.unicode_minus": False, "font.size": 10,
    })
    build_price_chart(frame)
    build_chip_chart()


if __name__ == "__main__":
    main()
