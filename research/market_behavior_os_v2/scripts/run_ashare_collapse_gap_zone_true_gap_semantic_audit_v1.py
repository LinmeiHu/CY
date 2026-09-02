#!/usr/bin/env python3
# ruff: noqa: E501
"""Outcome-blind semantic damage audit for the frozen collapse-gap-zone V1 lane."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-TRUE-GAP-SEMANTIC-AUDIT-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_true_gap_semantic_audit_v1")
EPISODE_PRIMITIVES = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/episode_strict_gap_primitives.parquet")
DEV_SOURCE = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_strategy_development_v1/source_events.parquet")
VAL_SOURCE = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/source_events_validation.parquet")
DEV_TRADES = OS_ROOT / "artifacts/ASHARE-COLLAPSE-GAP-ZONE-ENTRY-ADMISSION-DEVELOPMENT-V1_executed_trades.parquet"
VAL_TRADES = OS_ROOT / "artifacts/ASHARE-COLLAPSE-GAP-ZONE-DUAL-FRESH-K10-VALIDATION-V1_trades.parquet"
TRUE_PRIMITIVES = EXTERNAL / "true_strict_gap_primitives_2014_2023.parquet"
AUDIT_ROWS = OS_ROOT / f"artifacts/{EXPERIMENT}_rows.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class SemanticAuditError(RuntimeError):
    """Fail closed on identity or forbidden outcome use."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def build_true_primitives() -> pd.DataFrame:
    con = duckdb.connect()
    query = f"""
      SELECT *,
        high<prev_low AS true_strict_gap,
        high*coordinate_factor AS true_lower_coord,
        prev_low*coordinate_factor AS true_upper_coord,
        prev_low-high AS true_width_abs,
        (prev_low-high)/prev_close AS true_width_pct_vs_prev_close,
        (prev_low*coordinate_factor-high*coordinate_factor)
          /nullif(peak_coord_high-postcollapse_low_coord,0) AS true_width_share_of_peak_to_low,
        (
          (prev_low-high)/prev_close>=0.025 OR
          (prev_low*coordinate_factor-high*coordinate_factor)
            /nullif(peak_coord_high-postcollapse_low_coord,0)>=0.08
        ) AS true_significance_pass,
        1-postcollapse_low_coord/nullif(high*coordinate_factor,0) AS post_true_gap_depth
      FROM read_parquet('{EPISODE_PRIMITIVES}')
      WHERE high<prev_low
      ORDER BY collapse_episode_id,gap_date,gap_primitive_id
    """
    frame = con.execute(query).fetchdf()
    con.close()
    if frame.empty or not frame.true_strict_gap.all():
        raise SemanticAuditError("true primitive construction failed")
    write_parquet(frame, TRUE_PRIMITIVES)
    return frame


def load_trade_identities() -> pd.DataFrame:
    con = duckdb.connect()
    dev = con.execute(f"""
      SELECT event_id,symbol,board,entry_date,entry_time,entry_raw_price,entry_coord_price
      FROM read_parquet('{DEV_TRADES}') WHERE lane='L3_DUAL_FRESH'
      ORDER BY event_id
    """).fetchdf()
    val = con.execute(f"""
      SELECT event_id,symbol,board,entry_date,entry_time,entry_raw_price,entry_coord_price
      FROM read_parquet('{VAL_TRADES}') ORDER BY event_id
    """).fetchdf()
    con.close()
    dev["period"] = "DEVELOPMENT"
    val["period"] = "VALIDATION"
    rows = pd.concat([dev, val], ignore_index=True)
    if len(dev) != 207 or len(val) != 94 or rows.event_id.duplicated().any():
        raise SemanticAuditError(f"frozen identity mismatch: development={len(dev)} validation={len(val)}")
    forbidden = [c for c in rows if any(x in c.lower() for x in ("return", "exit", "pnl", "winner"))]
    if forbidden:
        raise SemanticAuditError(f"outcome columns selected: {forbidden}")
    return rows


def load_sources() -> pd.DataFrame:
    cols = ["event_id", "collapse_episode_id", "target_primitive_id", "zone_formation_cal_idx", "L", "U"]
    dev = pd.read_parquet(DEV_SOURCE, columns=cols)
    val = pd.read_parquet(VAL_SOURCE, columns=cols)
    source = pd.concat([dev, val], ignore_index=True).drop_duplicates("event_id", keep=False)
    # Events cannot occur in both source periods; fail closed if the concatenation does.
    expected = len(dev) + len(val)
    if len(source) != expected:
        duplicates = pd.concat([dev, val], ignore_index=True).event_id.duplicated(keep=False).sum()
        raise SemanticAuditError(f"source event collision: {duplicates}")
    return source


def audit() -> pd.DataFrame:
    true = build_true_primitives()
    trades = load_trade_identities()
    sources = load_sources()
    rows = trades.merge(sources, on="event_id", how="left", validate="one_to_one")
    if rows.collapse_episode_id.isna().any():
        raise SemanticAuditError("missing source identity")

    selected = true[[
        "gap_primitive_id", "true_lower_coord", "true_upper_coord", "true_width_abs",
        "true_width_pct_vs_prev_close", "true_significance_pass", "post_true_gap_depth",
    ]].rename(columns={"gap_primitive_id": "target_primitive_id"})
    rows = rows.merge(selected, on="target_primitive_id", how="left", validate="many_to_one")
    rows["selected_target_is_true_gap"] = rows.true_lower_coord.notna()
    rows["selected_target_survives"] = rows.selected_target_is_true_gap & rows.true_significance_pass.eq(True)
    rows["entry_reached_true_target"] = (
        rows.selected_target_survives
        & rows.entry_coord_price.ge(rows.true_lower_coord)
        & rows.entry_coord_price.le(rows.true_upper_coord)
    )

    meaningful = true.loc[true.true_significance_pass].copy()
    by_episode = {key: part for key, part in meaningful.groupby("collapse_episode_id", sort=False)}
    lower_counts: list[int] = []
    lower_ids: list[str] = []
    lowest_lowers: list[float] = []
    for row in rows.itertuples(index=False):
        part = by_episode.get(row.collapse_episode_id)
        if part is None or not np.isfinite(row.true_lower_coord):
            lower = pd.DataFrame()
        else:
            lower = part.loc[
                part.gap_cal_idx.gt(row.zone_formation_cal_idx)
                & part.gap_cal_idx.le(row.zone_formation_cal_idx + 15)
                & part.true_lower_coord.lt(row.true_lower_coord)
            ]
        lower_counts.append(len(lower))
        lower_ids.append(";".join(lower["gap_primitive_id"].astype(str)) if not lower.empty else "")
        lowest_lowers.append(float(lower.true_lower_coord.min()) if not lower.empty else np.nan)
    rows["lower_significant_true_layer_count"] = lower_counts
    rows["lower_significant_true_layer_ids"] = lower_ids
    rows["lowest_later_true_lower_coord"] = lowest_lowers
    rows["legacy_trade_semantically_valid"] = (
        rows.selected_target_survives
        & rows.entry_reached_true_target
        & rows.lower_significant_true_layer_count.eq(0)
    )
    return rows.sort_values(["period", "entry_date", "event_id"], kind="mergesort").reset_index(drop=True)


def summarize(rows: pd.DataFrame) -> dict[str, object]:
    def one(frame: pd.DataFrame) -> dict[str, object]:
        n = len(frame)
        return {
            "trades": n,
            "selected_target_not_true_gap": int((~frame.selected_target_is_true_gap).sum()),
            "selected_target_fails_true_significance": int((~frame.selected_target_survives).sum()),
            "entry_did_not_reach_true_target": int((~frame.entry_reached_true_target).sum()),
            "lower_significant_true_layer_exists": int(frame.lower_significant_true_layer_count.gt(0).sum()),
            "semantically_valid": int(frame.legacy_trade_semantically_valid.sum()),
            "semantically_valid_rate": float(frame.legacy_trade_semantically_valid.mean()) if n else None,
        }
    return {
        "experiment": EXPERIMENT,
        "classification": "V1_SEMANTIC_CONTRACT_INVALID",
        "outcome_columns_read": 0,
        "return_analysis_count": 0,
        "threshold_selection_count": 0,
        "corrected_strategy_replay_count": 0,
        "periods": {name: one(part) for name, part in rows.groupby("period", sort=True)},
        "combined": one(rows),
    }


def report_text(result: dict[str, object], rows: pd.DataFrame) -> str:
    combined = result["combined"]
    example = rows.loc[rows.event_id.eq("600250.SH|2022-03-08|Z02")].iloc[0]
    lines = [
        "# A-share Collapse-Gap-Zone True-Gap Semantic Audit V1",
        "",
        "This audit reads frozen identities and entries only. It does not read exits, returns, NAV, or outcome statistics.",
        "",
        "## Verdict",
        "",
        "`V1_SEMANTIC_CONTRACT_INVALID`",
        "",
        "V1 used `[Open_t, Low_{t-1}]`; the intended no-trade gap is `[High_t, Low_{t-1}]`. Future post-zone depth is no longer allowed to erase gap identity.",
        "",
        "## Damage summary",
        "",
        "| Period | Trades | Target not true | Entry below true gap | Lower true layer | Semantically valid |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("DEVELOPMENT", "VALIDATION"):
        item = result["periods"][name]
        lines.append(f"| {name} | {item['trades']} | {item['selected_target_not_true_gap']} | {item['entry_did_not_reach_true_target']} | {item['lower_significant_true_layer_exists']} | {item['semantically_valid']} |")
    lines += [
        f"| COMBINED | {combined['trades']} | {combined['selected_target_not_true_gap']} | {combined['entry_did_not_reach_true_target']} | {combined['lower_significant_true_layer_exists']} | {combined['semantically_valid']} |",
        "",
        "## 600250.SH example",
        "",
        f"- Legacy target survives as true gap: `{bool(example.selected_target_survives)}`.",
        f"- Entry reached true target: `{bool(example.entry_reached_true_target)}`.",
        f"- Lower significant true layers: `{int(example.lower_significant_true_layer_count)}` (`{example.lower_significant_true_layer_ids}`).",
        f"- Legacy trade semantically valid: `{bool(example.legacy_trade_semantically_valid)}`.",
        "",
        "## Governance",
        "",
        "No corrected return replay is authorized by this audit. A corrected V2 contract must be frozen before any Development economics are regenerated. 2022-2023 cannot regain first external Validation status.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    rows = audit()
    result = summarize(rows)
    write_parquet(rows, AUDIT_ROWS)
    atomic_text(RESULT, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_text(REPORT, report_text(result, rows))
    hashes = {str(path): sha256(path) for path in (SPEC, TRUE_PRIMITIVES, AUDIT_ROWS, RESULT, REPORT)}
    print(json.dumps({**result, "hashes": hashes}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
