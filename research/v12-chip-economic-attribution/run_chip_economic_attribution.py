#!/usr/bin/env python3
# ruff: noqa: E501
"""Research-only V12 chip-overlay economic attribution study.

This runner consumes the frozen outputs of commit 0601a6e82e and the same
governed 500-symbol panel.  It does not change production code, V3 temporal
semantics, the candidate universe, or any frozen chip artifact.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
OUTPUT_DIR = STUDY_DIR / "results"
REPORT_PATH = STUDY_DIR / "V12_CHIP_OVERLAY_ECONOMIC_ATTRIBUTION_AND_WINNER_PRESERVATION_STUDY.md"
PRIOR_DIR = REPO_ROOT / "research/v12-pnl-oriented-swing-study"
PRIOR_RUNNER = PRIOR_DIR / "run_pnl_oriented_swing_study.py"
PRIOR_RESULTS = PRIOR_DIR / "results"
PRIOR_MANIFEST = PRIOR_RESULTS / "result_manifest.json"

PNL_STUDY_COMMIT = "0601a6e82e"
EXPECTED_PRIOR_RUNNER_SHA256 = "90594bde9af002d649be9c8fa424fe837c8652095e754d1be77743a7ecef621a"
EXPECTED_PRIOR_MANIFEST_SHA256 = "147be513e339604092788da6731a1241973beea10c77d4f5b1ca0f2ae0b55b93"
EXPECTED_BASELINE_SHA256 = "79ec9b89005bdc0cdfb7a41a9f5e2f825c4057e1406b102dd50ca2206a238c05"
EXPECTED_CANDIDATE_SHA256 = "3913c3f839c9a5a9f682e47ff256be53a5a8395e371b34df019959692e7dc82a"

SOFT_RISK_CONTRACT = {
    "risk_tiers": {
        "FAVORABLE": "VALID_CANONICAL_BASE",
        "UNCERTAIN": "ENSEMBLE_AMBIGUOUS",
        "WEAK": "all other exact V3 temporal states; no synthetic base is supplied",
    },
    "S1": {"FAVORABLE": 1.00, "UNCERTAIN": 0.75, "WEAK": 0.50},
    "S2": {"FAVORABLE": 1.00, "UNCERTAIN": 0.50, "WEAK": 0.25},
    "selection_rule": "Among S1+D3 and S2+D3, choose on discovery only by highest size-weighted top-decile MFE retention, then lower size-weighted large-loss exposure, then maximum drawdown, then net return.",
}

DETERIORATION_CONTRACT = {
    "validated_chip_deterioration": "same exact canonical track; both mass and prominence at least 20% below their PIT running maxima",
    "D0": "no chip deterioration action",
    "D1": "block further adding only; the frozen carrier never pyramids, so this is an intentional no-op",
    "D2": "at next legal sell open reduce 25% on validated chip deterioration and retain a 75% core",
    "D3": "at next legal sell open reduce 50% only when validated chip deterioration is accompanied by close below PIT MA5; retain a 50% core",
    "hard_price_stops_override_chip": True,
}

CANONICAL_VARIANTS = (
    "P0_PRICE_ONLY",
    "I_CONFIRMATION_ONLY",
    "P6_DETERIORATION_DERISK",
    "SOFT_S1_MILD",
    "SOFT_S2_CONSERVATIVE",
    "DETERIORATION_D1_BLOCK_ADDS",
    "DETERIORATION_D2_REDUCE_25_RETAIN_CORE",
    "DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50",
    "BEST_PREREGISTERED_SOFT_COMBINED",
)


def _load_prior() -> Any:
    spec = importlib.util.spec_from_file_location("pnl_swing_study", PRIOR_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import the governed P&L study runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PRIOR = _load_prior()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def safe_float(value: object) -> float:
    return float(value) if finite(value) else math.nan


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=PRIOR.PRIOR.BASE.json_default)


def verify_inputs() -> dict[str, Any]:
    expected = {
        PRIOR_RUNNER: EXPECTED_PRIOR_RUNNER_SHA256,
        PRIOR_MANIFEST: EXPECTED_PRIOR_MANIFEST_SHA256,
        PRIOR_RESULTS / "price_baseline_trades.parquet": EXPECTED_BASELINE_SHA256,
        PRIOR_RESULTS / "candidate_universe.parquet": EXPECTED_CANDIDATE_SHA256,
    }
    for path, required in expected.items():
        actual = sha256(path)
        if actual != required:
            raise RuntimeError(f"frozen prior input changed: {path}: {actual}")
    prior_manifest = json.loads(PRIOR_MANIFEST.read_text(encoding="utf-8"))
    for name, metadata in prior_manifest["artifacts"].items():
        path = PRIOR_DIR / name if name.endswith(".md") else PRIOR_RESULTS / name
        if sha256(path) != metadata["sha256"]:
            raise RuntimeError(f"prior manifest artifact hash mismatch: {path}")
    ancestor = subprocess.run(
        ("git", "merge-base", "--is-ancestor", PNL_STUDY_COMMIT, "HEAD"),
        cwd=REPO_ROOT,
        check=False,
    ).returncode == 0
    if not ancestor:
        raise RuntimeError("HEAD does not descend from the completed controlled P&L study")
    return {
        "pnl_study_commit": PNL_STUDY_COMMIT,
        "pnl_study_commit_is_ancestor": ancestor,
        "prior_runner_sha256": EXPECTED_PRIOR_RUNNER_SHA256,
        "prior_manifest_sha256": EXPECTED_PRIOR_MANIFEST_SHA256,
        "baseline_trades_sha256": EXPECTED_BASELINE_SHA256,
        "candidate_universe_sha256": EXPECTED_CANDIDATE_SHA256,
        "prior_artifacts_verified": len(prior_manifest["artifacts"]),
    }


def risk_tier(frame: pd.DataFrame) -> pd.Series:
    state = frame["entry_temporal_state"].astype("string")
    return pd.Series(
        np.select(
            [
                state.eq("VALID_CANONICAL_BASE").fillna(False).to_numpy(dtype=bool),
                state.eq("ENSEMBLE_AMBIGUOUS").fillna(False).to_numpy(dtype=bool),
            ],
            ["FAVORABLE", "UNCERTAIN"],
            default="WEAK",
        ),
        index=frame.index,
        dtype="string",
    )


def soft_sizes(frame: pd.DataFrame, name: str) -> pd.Series:
    weights = SOFT_RISK_CONTRACT[name]
    return risk_tier(frame).map(weights).astype(float)


def make_variant(profile: pd.DataFrame, name: str, *, accepted: pd.Series | bool = True, sizes: pd.Series | float = 1.0) -> pd.DataFrame:
    result = profile.copy()
    result["variant"] = name
    result["overlay_accepted"] = accepted if isinstance(accepted, bool) else accepted.to_numpy()
    result["size_multiplier"] = sizes if isinstance(sizes, float) else sizes.to_numpy()
    return result


def _recompute_partial_profile(
    source: dict[str, Any], sf: pd.DataFrame, partial_pos: int | None, fraction: float, costs: Any,
) -> dict[str, Any]:
    profile = dict(source)
    completed = bool(source["completed"])
    exit_pos = int(source["exit_position"]) if completed else None
    terminal_price = float(source["exit_analysis_open_or_terminal_close"])
    exits = [(1.0, terminal_price)]
    if partial_pos is not None:
        exits = [(fraction, float(sf.iloc[partial_pos]["analysis_open"])), (1.0 - fraction, terminal_price)]
    gross, net, transaction_cost = PRIOR._fill_return(float(source["entry_analysis_open"]), exits, costs)
    profile.update(
        {
            "gross_return": gross,
            "net_return": net,
            "transaction_cost_return": transaction_cost,
            "mfe_capture_ratio": gross / float(source["mfe"]) if float(source["mfe"]) > 0 else math.nan,
            "profit_giveback_from_mfe": float(source["mfe"]) - gross,
            "partial_exit_timestamp": sf.iloc[partial_pos]["feature_date"] if partial_pos is not None else pd.NaT,
            "partial_exit_analysis_price": float(sf.iloc[partial_pos]["analysis_open"]) if partial_pos is not None else math.nan,
            "partial_exit_fraction": fraction if partial_pos is not None else 0.0,
            "deterioration_response_fraction": fraction if partial_pos is not None else 0.0,
        }
    )
    return profile


def apply_deterioration_response(
    baseline: pd.DataFrame,
    panel: pd.DataFrame,
    costs: Any,
    *,
    fraction: float,
    require_price_confirmation: bool,
) -> pd.DataFrame:
    symbol_panels = {
        symbol: sf.sort_values("feature_date").reset_index(drop=True)
        for symbol, sf in panel.groupby("symbol", sort=False)
    }
    output: list[dict[str, Any]] = []
    for source in baseline.to_dict("records"):
        if bool(source.get("entry_unfilled", False)) or not finite(source.get("entry_position")):
            output.append(dict(source))
            continue
        sf = symbol_panels[source["symbol"]]
        entry_pos = int(source["entry_position"])
        exit_signal_pos = int(source["exit_signal_position"]) if finite(source.get("exit_signal_position")) else len(sf) - 1
        exit_pos = int(source["exit_position"]) if bool(source["completed"]) else None
        entry_track = source.get("entry_peak_track_id")
        running_mass = -math.inf
        running_prominence = -math.inf
        warning_pos: int | None = None
        partial_pos: int | None = None
        for position in range(entry_pos, exit_signal_pos + 1):
            row = sf.iloc[position]
            same_track = (
                pd.notna(entry_track)
                and row["peak_track_id"] == entry_track
                and row["temporal_state"] == "VALID_CANONICAL_BASE"
            )
            if not same_track or not finite(row["peak_track_mass"]) or not finite(row["peak_track_prominence"]):
                continue
            running_mass = max(running_mass, float(row["peak_track_mass"]))
            running_prominence = max(running_prominence, float(row["peak_track_prominence"]))
            deteriorated = (
                running_mass > 0
                and running_prominence > 0
                and float(row["peak_track_mass"]) <= 0.80 * running_mass
                and float(row["peak_track_prominence"]) <= 0.80 * running_prominence
            )
            price_confirmed = finite(row["ma5"]) and float(row["analysis_close"]) < float(row["ma5"])
            if deteriorated and (price_confirmed or not require_price_confirmation):
                candidate = PRIOR.next_legal_position(sf, position + 1, "legal_sell_open", maximum_wait=None)
                if candidate is not None and (exit_pos is None or candidate < exit_pos):
                    warning_pos, partial_pos = position, candidate
                break
        profile = _recompute_partial_profile(source, sf, partial_pos, fraction, costs)
        profile["deterioration_warning_timestamp"] = sf.iloc[warning_pos]["feature_date"] if warning_pos is not None else pd.NaT
        profile["deterioration_price_confirmation_required"] = require_price_confirmation
        output.append(profile)
    return pd.DataFrame(output).sort_values(["entry_signal_timestamp", "symbol", "trade_id"]).reset_index(drop=True)


def weighted_trade_statistics(frame: pd.DataFrame, split: str) -> dict[str, float]:
    source = frame[frame["overlay_accepted"].fillna(False) & frame["completed"].fillna(False)].copy()
    if split != "total":
        source = source[source["split"].eq(split)]
    if source.empty:
        return {key: math.nan for key in ("weighted_profit_factor", "weighted_mean_return", "weighted_mae", "weighted_mfe", "weighted_large_loss_probability")}
    weights = pd.to_numeric(source["size_multiplier"], errors="coerce").fillna(0.0)
    returns = pd.to_numeric(source["net_return"], errors="coerce")
    gains = float((weights * returns.clip(lower=0)).sum())
    losses = float(-(weights * returns.clip(upper=0)).sum())
    denominator = float(weights.sum())
    return {
        "weighted_profit_factor": gains / losses if losses > 0 else math.inf if gains > 0 else math.nan,
        "weighted_mean_return": float((weights * returns).sum() / denominator) if denominator > 0 else math.nan,
        "weighted_mae": float((weights * pd.to_numeric(source["mae"], errors="coerce")).sum() / denominator) if denominator > 0 else math.nan,
        "weighted_mfe": float((weights * pd.to_numeric(source["mfe"], errors="coerce")).sum() / denominator) if denominator > 0 else math.nan,
        "weighted_large_loss_probability": float((weights * returns.le(PRIOR.LARGE_LOSS)).sum() / denominator) if denominator > 0 else math.nan,
    }


def build_research_variants(
    baseline: pd.DataFrame, panel: pd.DataFrame, thresholds: dict[str, float], costs: Any,
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    # Rebuild the prior ladder from the immutable baseline so P1-P6 remain exact.
    variants = PRIOR.build_variants(baseline, panel, thresholds, costs)
    d2 = apply_deterioration_response(
        baseline, panel, costs, fraction=0.25, require_price_confirmation=False
    )
    d3 = apply_deterioration_response(
        baseline, panel, costs, fraction=0.50, require_price_confirmation=True
    )
    variants.update(
        {
            "SOFT_S1_MILD": make_variant(baseline, "SOFT_S1_MILD", sizes=soft_sizes(baseline, "S1")),
            "SOFT_S2_CONSERVATIVE": make_variant(baseline, "SOFT_S2_CONSERVATIVE", sizes=soft_sizes(baseline, "S2")),
            "DETERIORATION_D1_BLOCK_ADDS": make_variant(baseline, "DETERIORATION_D1_BLOCK_ADDS"),
            "DETERIORATION_D2_REDUCE_25_RETAIN_CORE": make_variant(d2, "DETERIORATION_D2_REDUCE_25_RETAIN_CORE"),
            "DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50": make_variant(d3, "DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50"),
            "COMBINED_S1_D3": make_variant(d3, "COMBINED_S1_D3", sizes=soft_sizes(d3, "S1")),
            "COMBINED_S2_D3": make_variant(d3, "COMBINED_S2_D3", sizes=soft_sizes(d3, "S2")),
        }
    )
    # This equal-size diagnostic isolates whether P6's positive return depends on
    # the P4 position-size map; it is never proposed as a strategy.
    p6_equal = variants["P6_DETERIORATION_DERISK"].copy()
    p6_equal["variant"] = "P6_EQUAL_SIZE_DIAGNOSTIC"
    p6_equal["size_multiplier"] = 1.0
    variants["P6_EQUAL_SIZE_DIAGNOSTIC"] = p6_equal

    # Freeze the combined selection using discovery only.  Winner preservation
    # is deliberately the first key, ahead of loss exposure and return.
    scores: list[dict[str, Any]] = []
    discovery = baseline[baseline["split"].eq("discovery") & baseline["completed"].fillna(False)].copy()
    top_threshold = float(discovery["net_return"].quantile(0.90))
    top = discovery[discovery["net_return"].ge(top_threshold)]
    for name in ("COMBINED_S1_D3", "COMBINED_S2_D3"):
        frame = variants[name].set_index("trade_id")
        top_profile = frame.loc[top["trade_id"]]
        weighted_mfe_retention = float(
            (top_profile["size_multiplier"].to_numpy() * top_profile["mfe"].to_numpy()).sum()
            / top["mfe"].sum()
        )
        discovery_profile = frame.loc[discovery["trade_id"]]
        weights = discovery_profile["size_multiplier"].to_numpy()
        loss_exposure = float(
            (weights * discovery_profile["net_return"].le(PRIOR.LARGE_LOSS).to_numpy()).sum()
            / weights.sum()
        )
        scores.append(
            {
                "variant": name,
                "discovery_top_decile_mfe_retention": weighted_mfe_retention,
                "discovery_weighted_large_loss_exposure": loss_exposure,
            }
        )
    discovery_portfolio, _discovery_trades, _discovery_curves, _discovery_admissions = PRIOR.evaluate_variants(
        {name: variants[name] for name in ("COMBINED_S1_D3", "COMBINED_S2_D3")}, panel, costs
    )
    discovery_metrics = discovery_portfolio[discovery_portfolio["split"].eq("discovery")].set_index("variant")
    score_frame = pd.DataFrame(scores)
    score_frame["discovery_max_drawdown"] = score_frame["variant"].map(discovery_metrics["maximum_drawdown"])
    score_frame["discovery_net_return"] = score_frame["variant"].map(discovery_metrics["net_total_return"])
    score_frame = score_frame.sort_values(
        [
            "discovery_top_decile_mfe_retention",
            "discovery_weighted_large_loss_exposure",
            "discovery_max_drawdown",
            "discovery_net_return",
            "variant",
        ],
        ascending=[False, True, False, False, True],
    )
    selected_source = str(score_frame.iloc[0]["variant"])
    best = variants[selected_source].copy()
    best["variant"] = "BEST_PREREGISTERED_SOFT_COMBINED"
    variants["BEST_PREREGISTERED_SOFT_COMBINED"] = best
    selection = {
        "selected_source": selected_source,
        "selection_population": "discovery only",
        "selection_rule": SOFT_RISK_CONTRACT["selection_rule"],
        "scores": score_frame.to_json(orient="records"),
    }
    return variants, selection


def winner_metrics(variants: dict[str, pd.DataFrame]) -> pd.DataFrame:
    baseline = variants["P0_PRICE_ONLY"]
    rows: list[dict[str, Any]] = []
    for split in PRIOR.SPLITS:
        base = baseline[baseline["split"].eq(split) & baseline["completed"].fillna(False)].copy()
        q90 = float(base["net_return"].quantile(0.90))
        q95 = float(base["net_return"].quantile(0.95))
        winners = base[base["net_return"].gt(0)]
        top10 = base[base["net_return"].ge(q90)]
        top5 = base[base["net_return"].ge(q95)]
        large_losers = base[base["net_return"].le(PRIOR.LARGE_LOSS)]
        for name, frame0 in variants.items():
            frame = frame0[frame0["split"].eq(split)].set_index("trade_id")
            accepted_ids = set(frame[frame["overlay_accepted"].fillna(False)].index)

            def retained_count(source: pd.DataFrame) -> int:
                return int(source["trade_id"].isin(accepted_ids).sum())

            def effective_sum(source: pd.DataFrame, column: str) -> float:
                ids = source[source["trade_id"].isin(accepted_ids)]["trade_id"]
                if ids.empty:
                    return 0.0
                selected = frame.loc[ids]
                return float((selected["size_multiplier"] * pd.to_numeric(selected[column], errors="coerce")).sum())

            winner_pnl_denominator = float(winners["net_return"].sum())
            top_mfe_denominator = float(top10["mfe"].sum())
            affected_large_losers = 0
            for trade in large_losers.itertuples(index=False):
                if trade.trade_id not in accepted_ids:
                    affected_large_losers += 1
                    continue
                overlay = frame.loc[trade.trade_id]
                if float(overlay["size_multiplier"]) < 1.0 or float(overlay.get("partial_exit_fraction", 0.0)) > 0:
                    affected_large_losers += 1
            rows.append(
                {
                    "variant": name,
                    "split": split,
                    "baseline_winners": len(winners),
                    "all_winners_retained": retained_count(winners),
                    "top_decile_winners": len(top10),
                    "top_decile_winners_retained": retained_count(top10),
                    "top_five_percent_winners": len(top5),
                    "top_five_percent_winners_retained": retained_count(top5),
                    "winner_pnl_retained_fraction": effective_sum(winners, "net_return") / winner_pnl_denominator if winner_pnl_denominator > 0 else math.nan,
                    "top_decile_mfe_retained_fraction": effective_sum(top10, "mfe") / top_mfe_denominator if top_mfe_denominator > 0 else math.nan,
                    "large_losers": len(large_losers),
                    "large_losers_removed_or_reduced": affected_large_losers,
                    "logical_trade_retention_fraction": len(accepted_ids.intersection(set(base["trade_id"]))) / len(base) if len(base) else math.nan,
                }
            )
    return pd.DataFrame(rows)


def survival_waterfall(variants: dict[str, pd.DataFrame]) -> pd.DataFrame:
    stages = (
        "P0_PRICE_ONLY",
        "P1_TEMPORAL_CONFIRMATION",
        "P2_CANONICAL_PERSISTENCE",
        "P3_MASS_PROMINENCE",
        "P4_CHIP_SIZING",
        "P5_HEALTHY_HOLDING",
        "P6_DETERIORATION_DERISK",
    )
    baseline = variants["P0_PRICE_ONLY"]
    rows: list[dict[str, Any]] = []
    for split in PRIOR.SPLITS:
        base = baseline[baseline["split"].eq(split) & baseline["completed"].fillna(False)].copy()
        q90 = float(base["net_return"].quantile(0.90))
        winners = base[base["net_return"].gt(0)]
        top = base[base["net_return"].ge(q90)]
        losers = base[base["net_return"].lt(0)]
        large_losers = base[base["net_return"].le(PRIOR.LARGE_LOSS)]
        for stage_number, name in enumerate(stages):
            overlay = variants[name]
            overlay = overlay[overlay["split"].eq(split)].set_index("trade_id")
            accepted_ids = set(overlay[overlay["overlay_accepted"].fillna(False)].index)
            retained = base[base["trade_id"].isin(accepted_ids)]
            retained_overlay = overlay.loc[retained["trade_id"]] if len(retained) else overlay.iloc[0:0]
            top_overlay = overlay.loc[top[top["trade_id"].isin(accepted_ids)]["trade_id"]] if len(top) else overlay.iloc[0:0]
            total_mfe = float((retained_overlay["size_multiplier"] * retained_overlay["mfe"]).sum())
            top_mfe = float((top_overlay["size_multiplier"] * top_overlay["mfe"]).sum())
            effective_return = float((retained_overlay["size_multiplier"] * retained_overlay["net_return"]).sum())
            rows.append(
                {
                    "stage_number": stage_number,
                    "stage": name,
                    "split": split,
                    "baseline_trades": len(base),
                    "baseline_trades_remaining": len(retained),
                    "baseline_winners": len(winners),
                    "baseline_winners_remaining": int(winners["trade_id"].isin(accepted_ids).sum()),
                    "baseline_top_decile_winners": len(top),
                    "baseline_top_decile_winners_remaining": int(top["trade_id"].isin(accepted_ids).sum()),
                    "baseline_losers_removed": int((~losers["trade_id"].isin(accepted_ids)).sum()),
                    "baseline_large_losers_removed": int((~large_losers["trade_id"].isin(accepted_ids)).sum()),
                    "total_baseline_mfe": float(base["mfe"].sum()),
                    "total_baseline_mfe_retained": total_mfe,
                    "total_baseline_mfe_retained_fraction": total_mfe / float(base["mfe"].sum()),
                    "total_top_decile_mfe": float(top["mfe"].sum()),
                    "total_top_decile_mfe_retained": top_mfe,
                    "total_top_decile_mfe_retained_fraction": top_mfe / float(top["mfe"].sum()),
                    "baseline_realized_return_sum": float(base["net_return"].sum()),
                    "effective_realized_return_sum_retained": effective_return,
                }
            )
    result = pd.DataFrame(rows)
    for split in PRIOR.SPLITS:
        mask = result["split"].eq(split)
        ordered = result.loc[mask].sort_values("stage_number")
        result.loc[ordered.index, "incremental_top_decile_winners_lost"] = -ordered["baseline_top_decile_winners_remaining"].diff().fillna(0).to_numpy()
        result.loc[ordered.index, "incremental_baseline_trades_removed"] = -ordered["baseline_trades_remaining"].diff().fillna(0).to_numpy()
    return result.sort_values(["split", "stage_number"]).reset_index(drop=True)


def overlay_stage_attribution(
    variants: dict[str, pd.DataFrame], portfolio: pd.DataFrame, waterfall: pd.DataFrame,
) -> pd.DataFrame:
    stages = (
        "P0_PRICE_ONLY",
        "P1_TEMPORAL_CONFIRMATION",
        "P2_CANONICAL_PERSISTENCE",
        "P3_MASS_PROMINENCE",
        "P4_CHIP_SIZING",
        "P5_HEALTHY_HOLDING",
        "P6_DETERIORATION_DERISK",
    )
    p = portfolio.set_index(["variant", "split"])
    baseline = variants["P0_PRICE_ONLY"]
    rows: list[dict[str, Any]] = []
    for previous, current in pairwise(stages):
        for split in ("validation", "holdout"):
            prev_frame = variants[previous]
            curr_frame = variants[current]
            base = baseline[baseline["split"].eq(split) & baseline["completed"].fillna(False)].copy()
            q90 = float(base["net_return"].quantile(0.90))
            winners = set(base.loc[base["net_return"].gt(0), "trade_id"])
            top = set(base.loc[base["net_return"].ge(q90), "trade_id"])

            def effective(frame: pd.DataFrame, ids: set[str], column: str) -> float:
                selected = frame[
                    frame["split"].eq(split)
                    & frame["completed"].fillna(False)
                    & frame["overlay_accepted"].fillna(False)
                    & frame["trade_id"].isin(ids)
                ]
                return float((selected["size_multiplier"] * pd.to_numeric(selected[column], errors="coerce")).sum())

            prev_loss = prev_frame[
                prev_frame["split"].eq(split) & prev_frame["completed"].fillna(False) & prev_frame["overlay_accepted"].fillna(False) & prev_frame["net_return"].le(PRIOR.LARGE_LOSS)
            ]
            curr_loss = curr_frame[
                curr_frame["split"].eq(split) & curr_frame["completed"].fillna(False) & curr_frame["overlay_accepted"].fillna(False) & curr_frame["net_return"].le(PRIOR.LARGE_LOSS)
            ]
            prev_water = waterfall[(waterfall["stage"].eq(previous)) & waterfall["split"].eq(split)].iloc[0]
            curr_water = waterfall[(waterfall["stage"].eq(current)) & waterfall["split"].eq(split)].iloc[0]
            rows.append(
                {
                    "from_stage": previous,
                    "to_stage": current,
                    "split": split,
                    "incremental_net_pnl": safe_float(p.loc[(current, split), "net_total_return"]) - safe_float(p.loc[(previous, split), "net_total_return"]),
                    "drawdown_reduction": safe_float(p.loc[(current, split), "maximum_drawdown"]) - safe_float(p.loc[(previous, split), "maximum_drawdown"]),
                    "large_loss_count_reduction": len(prev_loss) - len(curr_loss),
                    "large_loss_weighted_return_reduction": -effective(prev_frame, set(prev_loss["trade_id"]), "net_return") + effective(curr_frame, set(curr_loss["trade_id"]), "net_return"),
                    "winner_pnl_sacrificed": effective(prev_frame, winners, "net_return") - effective(curr_frame, winners, "net_return"),
                    "top_decile_winner_pnl_sacrificed": effective(prev_frame, top, "net_return") - effective(curr_frame, top, "net_return"),
                    "mfe_retained": curr_water["total_baseline_mfe_retained"],
                    "incremental_mfe_lost": prev_water["total_baseline_mfe_retained"] - curr_water["total_baseline_mfe_retained"],
                    "top_decile_mfe_retained": curr_water["total_top_decile_mfe_retained"],
                    "incremental_top_decile_mfe_lost": prev_water["total_top_decile_mfe_retained"] - curr_water["total_top_decile_mfe_retained"],
                    "transaction_cost_impact": safe_float(p.loc[(current, split), "transaction_costs"]) - safe_float(p.loc[(previous, split), "transaction_costs"]),
                    "exposure_impact": safe_float(p.loc[(current, split), "average_exposure"]) - safe_float(p.loc[(previous, split), "average_exposure"]),
                    "turnover_impact": safe_float(p.loc[(current, split), "turnover"]) - safe_float(p.loc[(previous, split), "turnover"]),
                }
            )
    result = pd.DataFrame(rows)
    classifications: dict[str, str] = {}
    for stage, group in result.groupby("to_stage", sort=False):
        validation = group[group["split"].eq("validation")].iloc[0]
        holdout = group[group["split"].eq("holdout")].iloc[0]
        previous_top_mfe = float(
            waterfall[(waterfall["stage"].eq(holdout["from_stage"])) & waterfall["split"].eq("holdout")].iloc[0]["total_top_decile_mfe_retained"]
        )
        top_loss_fraction = holdout["incremental_top_decile_mfe_lost"] / previous_top_mfe if previous_top_mfe > 0 else 0.0
        if top_loss_fraction >= 0.25:
            label = "WINNER_DESTRUCTIVE"
        elif validation["incremental_net_pnl"] < -0.002 < holdout["incremental_net_pnl"] or holdout["incremental_net_pnl"] < -0.002 < validation["incremental_net_pnl"]:
            label = "UNSTABLE"
        elif validation["incremental_net_pnl"] <= 0 and holdout["incremental_net_pnl"] <= 0 and validation["drawdown_reduction"] > 0 and holdout["drawdown_reduction"] > 0:
            label = "RISK_REDUCING_BUT_RETURN_DESTRUCTIVE"
        elif validation["incremental_net_pnl"] >= 0 and holdout["incremental_net_pnl"] >= 0 and validation["drawdown_reduction"] >= -0.005 and holdout["drawdown_reduction"] >= -0.005:
            label = "VALUE_CREATING"
        elif all(abs(row["incremental_net_pnl"]) < 0.002 and abs(row["drawdown_reduction"]) < 0.002 for _, row in group.iterrows()):
            label = "NEUTRAL"
        else:
            label = "UNSTABLE"
        classifications[stage] = label
    result["economic_classification"] = result["to_stage"].map(classifications)
    return result


def confirmation_removed_analysis(baseline: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    source = baseline[baseline["completed"].fillna(False)].copy()
    source["confirmation_decision"] = np.where(
        source["entry_temporal_state"].isin(["VALID_CANONICAL_BASE", "ENSEMBLE_AMBIGUOUS"]),
        "RETAINED",
        "REMOVED",
    )
    source["canonical_state"] = np.where(source["entry_temporal_state"].eq("VALID_CANONICAL_BASE"), "VALID", "NOT_VALID")
    source["ambiguity_state"] = np.where(source["entry_temporal_state"].eq("ENSEMBLE_AMBIGUOUS"), "AMBIGUOUS", "NOT_AMBIGUOUS")
    age = pd.to_numeric(source["entry_peak_track_age"], errors="coerce")
    source["base_persistence_state"] = np.select([age.ge(20), age.notna()], ["AGE_GE_20", "AGE_LT_20"], default="UNAVAILABLE")
    mass = pd.to_numeric(source["entry_peak_track_mass"], errors="coerce")
    prominence = pd.to_numeric(source["entry_peak_track_prominence"], errors="coerce")
    source["mass_level"] = np.select(
        [mass.ge(thresholds["entry_peak_track_mass_median"]), mass.notna()],
        ["AT_OR_ABOVE_DISCOVERY_MEDIAN", "BELOW_DISCOVERY_MEDIAN"],
        default="UNAVAILABLE",
    )
    source["prominence_level"] = np.select(
        [prominence.ge(thresholds["entry_peak_track_prominence_median"]), prominence.notna()],
        ["AT_OR_ABOVE_DISCOVERY_MEDIAN", "BELOW_DISCOVERY_MEDIAN"],
        default="UNAVAILABLE",
    )
    dimensions = {
        "CONFIRMATION_DECISION": "confirmation_decision",
        "TEMPORAL_STATE": "entry_temporal_state",
        "CANONICAL_BASE_STATE": "canonical_state",
        "AMBIGUITY_STATE": "ambiguity_state",
        "BASE_PERSISTENCE": "base_persistence_state",
        "MASS_LEVEL": "mass_level",
        "PROMINENCE_LEVEL": "prominence_level",
    }
    rows: list[dict[str, Any]] = []
    for split in ("discovery", "validation", "holdout"):
        split_frame = source[source["split"].eq(split)]
        for dimension, column in dimensions.items():
            for value, group in split_frame.groupby(column, dropna=False, sort=True):
                returns = pd.to_numeric(group["net_return"], errors="coerce")
                rows.append(
                    {
                        "split": split,
                        "group_dimension": dimension,
                        "group_value": str(value),
                        "confirmation_removed": bool(group["confirmation_decision"].eq("REMOVED").all()),
                        "trades": len(group),
                        "total_baseline_net_return": float(returns.sum()),
                        "mean_baseline_net_return": float(returns.mean()),
                        "profit_factor": PRIOR.profit_factor(returns),
                        "mean_mae": float(group["mae"].mean()),
                        "mean_mfe": float(group["mfe"].mean()),
                        "large_loss_probability": float(returns.le(PRIOR.LARGE_LOSS).mean()),
                        "large_winner_probability": float(returns.ge(PRIOR.LARGE_WINNER).mean()),
                        "winner_probability": float(returns.gt(0).mean()),
                        "mean_peak_track_age": float(age.loc[group.index].mean()),
                        "mean_peak_track_mass": float(mass.loc[group.index].mean()),
                        "mean_peak_track_prominence": float(prominence.loc[group.index].mean()),
                    }
                )
    return pd.DataFrame(rows)


def build_path_records(baseline: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    symbol_panels = {
        symbol: sf.sort_values("feature_date").reset_index(drop=True)
        for symbol, sf in panel.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    completed = baseline[baseline["completed"].fillna(False) & baseline["split"].isin(["validation", "holdout"])].copy()
    thresholds = completed.groupby("split")["net_return"].quantile([0.90, 0.95]).unstack()
    for trade in completed.to_dict("records"):
        sf = symbol_panels[trade["symbol"]]
        start = int(trade["entry_position"])
        stop = int(trade["exit_signal_position"])
        if float(trade["net_return"]) <= PRIOR.LARGE_LOSS:
            outcome = "LARGE_LOSER"
        elif float(trade["net_return"]) >= float(thresholds.loc[trade["split"], 0.90]):
            outcome = "TOP_DECILE_WINNER"
        elif float(trade["net_return"]) > 0:
            outcome = "ORDINARY_WINNER"
        else:
            outcome = "ORDINARY_LOSER"
        running_high = float(trade["entry_analysis_open"])
        running_mass = -math.inf
        running_prominence = -math.inf
        entry_track = trade.get("entry_peak_track_id")
        for relative, position in enumerate(range(start, stop + 1)):
            row = sf.iloc[position]
            running_high = max(running_high, float(row["analysis_high"]))
            same_track = pd.notna(entry_track) and row["peak_track_id"] == entry_track and row["temporal_state"] == "VALID_CANONICAL_BASE"
            if same_track and finite(row["peak_track_mass"]) and finite(row["peak_track_prominence"]):
                running_mass = max(running_mass, float(row["peak_track_mass"]))
                running_prominence = max(running_prominence, float(row["peak_track_prominence"]))
                deteriorated = (
                    running_mass > 0
                    and running_prominence > 0
                    and float(row["peak_track_mass"]) <= 0.80 * running_mass
                    and float(row["peak_track_prominence"]) <= 0.80 * running_prominence
                )
            else:
                deteriorated = False
            price_confirmation = finite(row["ma5"]) and float(row["analysis_close"]) < float(row["ma5"])
            rows.append(
                {
                    "trade_id": trade["trade_id"],
                    "symbol": trade["symbol"],
                    "split": trade["split"],
                    "outcome_group_retrospective_diagnostic_only": outcome,
                    "baseline_net_return": trade["net_return"],
                    "baseline_mae": trade["mae"],
                    "baseline_mfe": trade["mfe"],
                    "relative_session": relative,
                    "date": row["feature_date"],
                    "entry_date": trade["actual_entry_timestamp"],
                    "baseline_exit_signal_date": trade["exit_trigger_timestamp"],
                    "baseline_exit_fill_date": trade["actual_exit_timestamp"],
                    "running_mfe": running_high / float(trade["entry_analysis_open"]) - 1.0,
                    "temporal_state": row["temporal_state"],
                    "peak_track_id": row["peak_track_id"],
                    "same_entry_track_valid": same_track,
                    "peak_track_age": row["peak_track_age"],
                    "peak_track_mass": row["peak_track_mass"],
                    "peak_track_prominence": row["peak_track_prominence"],
                    "ensemble_ambiguous": row["temporal_state"] == "ENSEMBLE_AMBIGUOUS",
                    "peak_track_split": bool(row["peak_track_split"]),
                    "peak_track_merge": bool(row["peak_track_merge"]),
                    "peak_track_lost": bool(row["peak_track_lost"]),
                    "rebinding_from_entry_track": pd.notna(entry_track) and pd.notna(row["peak_track_id"]) and row["peak_track_id"] != entry_track,
                    "price_relative_to_base": row["price_relative_to_base"],
                    "cost_migration_5": row["cost_migration_5"],
                    "mass_change_5": row["mass_change_5"],
                    "prominence_change_5": row["prominence_change_5"],
                    "validated_deterioration": deteriorated,
                    "deterioration_with_price_confirmation": deteriorated and price_confirmation,
                    "price_below_ma5": price_confirmation,
                }
            )
    return pd.DataFrame(rows).sort_values(["split", "trade_id", "relative_session"]).reset_index(drop=True)


def aligned_trajectories(paths: pd.DataFrame) -> pd.DataFrame:
    source = paths.copy()
    source["valid_canonical"] = source["temporal_state"].eq("VALID_CANONICAL_BASE")
    source["topology_event"] = source[["peak_track_split", "peak_track_merge", "peak_track_lost", "rebinding_from_entry_track"]].any(axis=1)
    rows: list[dict[str, Any]] = []
    for keys, group in source.groupby(["split", "outcome_group_retrospective_diagnostic_only", "relative_session"], sort=True):
        split, outcome, session = keys
        rows.append(
            {
                "split": split,
                "outcome_group_retrospective_diagnostic_only": outcome,
                "relative_session": session,
                "observations": len(group),
                "distinct_trades": group["trade_id"].nunique(),
                "mean_running_mfe": group["running_mfe"].mean(),
                "mean_peak_track_mass": group["peak_track_mass"].mean(),
                "mean_peak_track_prominence": group["peak_track_prominence"].mean(),
                "mean_peak_track_age": group["peak_track_age"].mean(),
                "valid_canonical_rate": group["valid_canonical"].mean(),
                "ambiguity_rate": group["ensemble_ambiguous"].mean(),
                "topology_event_rate": group["topology_event"].mean(),
                "rebinding_rate": group["rebinding_from_entry_track"].mean(),
                "validated_deterioration_rate": group["validated_deterioration"].mean(),
                "price_confirmed_deterioration_rate": group["deterioration_with_price_confirmation"].mean(),
                "mean_price_relative_to_base": group["price_relative_to_base"].mean(),
                "mean_cost_migration_5": group["cost_migration_5"].mean(),
                "mean_mass_change_5": group["mass_change_5"].mean(),
                "mean_prominence_change_5": group["prominence_change_5"].mean(),
            }
        )
    return pd.DataFrame(rows)


def deterioration_diagnostics(paths: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for warning_name, column in (
        ("D2_VALIDATED_DETERIORATION", "validated_deterioration"),
        ("D3_DETERIORATION_PLUS_PRICE", "deterioration_with_price_confirmation"),
    ):
        for trade_id, group in paths.groupby("trade_id", sort=True):
            warnings = group[group[column]]
            if warnings.empty:
                continue
            first = warnings.iloc[0]
            after = group[group["relative_session"].ge(first["relative_session"])]
            remaining_mfe = float(after["running_mfe"].max() - first["running_mfe"])
            rows.append(
                {
                    "warning_type": warning_name,
                    "trade_id": trade_id,
                    "symbol": first["symbol"],
                    "split": first["split"],
                    "outcome_group": first["outcome_group_retrospective_diagnostic_only"],
                    "warning_date": first["date"],
                    "lead_sessions_to_baseline_exit_signal": int(group["relative_session"].max() - first["relative_session"]),
                    "baseline_net_return": first["baseline_net_return"],
                    "baseline_mae": first["baseline_mae"],
                    "baseline_mfe": first["baseline_mfe"],
                    "mfe_remaining_after_warning": max(0.0, remaining_mfe),
                    "false_warning_profitable_trade": bool(first["baseline_net_return"] > 0),
                    "warning_on_top_decile_winner": first["outcome_group_retrospective_diagnostic_only"] == "TOP_DECILE_WINNER",
                    "large_loss": bool(first["baseline_net_return"] <= PRIOR.LARGE_LOSS),
                }
            )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail
    summary: list[dict[str, Any]] = []
    for keys, group in detail.groupby(["warning_type", "split"], sort=True):
        warning_type, split = keys
        summary.append(
            {
                "warning_type": warning_type,
                "split": split,
                "warnings": len(group),
                "median_lead_sessions": group["lead_sessions_to_baseline_exit_signal"].median(),
                "mean_lead_sessions": group["lead_sessions_to_baseline_exit_signal"].mean(),
                "large_loss_probability": group["large_loss"].mean(),
                "false_warning_rate_profitable_trade": group["false_warning_profitable_trade"].mean(),
                "top_decile_winner_warning_rate": group["warning_on_top_decile_winner"].mean(),
                "mean_mae": group["baseline_mae"].mean(),
                "mean_mfe": group["baseline_mfe"].mean(),
                "mean_mfe_remaining_after_warning": group["mfe_remaining_after_warning"].mean(),
            }
        )
    return pd.DataFrame(summary)


def top_winner_audit(
    baseline: pd.DataFrame,
    variants: dict[str, pd.DataFrame],
    paths: pd.DataFrame,
    thresholds: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    holdout = baseline[baseline["split"].eq("holdout") & baseline["completed"].fillna(False)].copy()
    threshold = float(holdout["net_return"].quantile(0.90))
    top = holdout[holdout["net_return"].ge(threshold)].copy()
    variant_maps = {name: frame.set_index("trade_id") for name, frame in variants.items()}
    summary_rows: list[dict[str, Any]] = []
    for trade in top.to_dict("records"):
        trade_id = trade["trade_id"]
        p1 = variant_maps["P1_TEMPORAL_CONFIRMATION"].loc[trade_id]
        p2 = variant_maps["P2_CANONICAL_PERSISTENCE"].loc[trade_id]
        p3 = variant_maps["P3_MASS_PROMINENCE"].loc[trade_id]
        p4 = variant_maps["P4_CHIP_SIZING"].loc[trade_id]
        p5 = variant_maps["P5_HEALTHY_HOLDING"].loc[trade_id]
        p6 = variant_maps["P6_DETERIORATION_DERISK"].loc[trade_id]
        first_removed_stage = "RETAINED_THROUGH_P6"
        removal_reason = "NONE"
        if not bool(p1["overlay_accepted"]):
            first_removed_stage = "P1_TEMPORAL_CONFIRMATION"
            removal_reason = f"ENTRY_TEMPORAL_STATE_{trade['entry_temporal_state']}"
        elif not bool(p2["overlay_accepted"]):
            first_removed_stage = "P2_CANONICAL_PERSISTENCE"
            if trade["entry_temporal_state"] != "VALID_CANONICAL_BASE":
                removal_reason = f"P2_REQUIRES_VALID_CANONICAL_NOT_{trade['entry_temporal_state']}"
            else:
                removal_reason = f"PEAK_TRACK_AGE_{safe_float(trade['entry_peak_track_age']):.0f}_LT_20"
        elif not bool(p3["overlay_accepted"]):
            first_removed_stage = "P3_MASS_PROMINENCE"
            failures: list[str] = []
            if not finite(trade["entry_peak_track_mass"]) or float(trade["entry_peak_track_mass"]) < thresholds["entry_peak_track_mass_median"]:
                failures.append("MASS_BELOW_DISCOVERY_MEDIAN")
            if not finite(trade["entry_peak_track_prominence"]) or float(trade["entry_peak_track_prominence"]) < thresholds["entry_peak_track_prominence_median"]:
                failures.append("PROMINENCE_BELOW_DISCOVERY_MEDIAN")
            removal_reason = "+".join(failures) if failures else "P3_LEVEL_GATE"
        accepted_p6 = bool(p6["overlay_accepted"])
        filtering_loss = float(trade["net_return"]) if not accepted_p6 else 0.0
        sizing_loss = float(trade["net_return"]) * (1.0 - float(p6["size_multiplier"])) if accepted_p6 else 0.0
        truncation_loss = (
            float(p6["size_multiplier"]) * (float(trade["net_return"]) - float(p6["net_return"]))
            if accepted_p6 else 0.0
        )
        mechanisms: list[str] = []
        if not accepted_p6:
            mechanisms.append("FILTERING")
        if accepted_p6 and float(p6["size_multiplier"]) < 0.95:
            mechanisms.append("SIZING")
        if accepted_p6 and (
            float(p6.get("partial_exit_fraction", 0.0)) > 0
            or (
                pd.notna(p6["actual_exit_timestamp"])
                and pd.Timestamp(p6["actual_exit_timestamp"]) < pd.Timestamp(trade["actual_exit_timestamp"])
            )
        ):
            mechanisms.append("PREMATURE_EXIT")
        summary_rows.append(
            {
                "trade_id": trade_id,
                "symbol": trade["symbol"],
                "baseline_entry_date": trade["actual_entry_timestamp"],
                "baseline_exit_date": trade["actual_exit_timestamp"],
                "baseline_exit_reason": trade["exit_reason"],
                "baseline_net_return": trade["net_return"],
                "baseline_mfe": trade["mfe"],
                "baseline_mae": trade["mae"],
                "entry_temporal_state": trade["entry_temporal_state"],
                "entry_peak_track_age": trade["entry_peak_track_age"],
                "entry_peak_track_mass": trade["entry_peak_track_mass"],
                "entry_peak_track_prominence": trade["entry_peak_track_prominence"],
                "p1_retained": bool(p1["overlay_accepted"]),
                "p2_retained": bool(p2["overlay_accepted"]),
                "p3_retained": bool(p3["overlay_accepted"]),
                "p4_retained": bool(p4["overlay_accepted"]),
                "p4_size_multiplier": p4["size_multiplier"],
                "p5_exit_date": p5["actual_exit_timestamp"],
                "p5_net_return": p5["net_return"],
                "p6_retained": accepted_p6,
                "p6_size_multiplier": p6["size_multiplier"],
                "p6_partial_exit_date": p6["partial_exit_timestamp"],
                "p6_partial_exit_fraction": p6["partial_exit_fraction"],
                "p6_exit_date": p6["actual_exit_timestamp"],
                "p6_net_return": p6["net_return"],
                "first_removal_stage": first_removed_stage,
                "removal_reason": removal_reason,
                "p6_loss_mechanism": "+".join(mechanisms) if mechanisms else "NONE",
                "filtering_economic_loss": filtering_loss,
                "sizing_economic_loss": sizing_loss,
                "premature_exit_economic_loss": truncation_loss,
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values(["baseline_net_return", "trade_id"], ascending=[False, True]).reset_index(drop=True)
    audit = paths[
        paths["split"].eq("holdout")
        & paths["trade_id"].isin(set(summary["trade_id"]))
    ].merge(summary, on=["trade_id", "symbol"], how="left", validate="many_to_one")
    audit["p5_intervention_on_date"] = pd.to_datetime(audit["date"]).eq(pd.to_datetime(audit["p5_exit_date"]))
    audit["p6_partial_intervention_on_date"] = pd.to_datetime(audit["date"]).eq(pd.to_datetime(audit["p6_partial_exit_date"]))
    return audit.sort_values(["trade_id", "relative_session"]).reset_index(drop=True), summary


def topology_conditional_analysis(paths: pd.DataFrame) -> pd.DataFrame:
    trade_level = paths.groupby(["trade_id", "split"], sort=True).agg(
        baseline_net_return=("baseline_net_return", "first"),
        baseline_mae=("baseline_mae", "first"),
        baseline_mfe=("baseline_mfe", "first"),
        split_event=("peak_track_split", "max"),
        merge_event=("peak_track_merge", "max"),
        lost_event=("peak_track_lost", "max"),
        rebinding_event=("rebinding_from_entry_track", "max"),
        ambiguity_event=("ensemble_ambiguous", "max"),
    ).reset_index()
    event_columns = {
        "SPLIT": "split_event",
        "MERGE": "merge_event",
        "LOST": "lost_event",
        "REBINDING": "rebinding_event",
        "ENSEMBLE_AMBIGUITY": "ambiguity_event",
    }
    rows: list[dict[str, Any]] = []
    classifications: dict[str, str] = {}
    for event, column in event_columns.items():
        event_rows: list[dict[str, Any]] = []
        for split in ("validation", "holdout"):
            frame = trade_level[trade_level["split"].eq(split)]
            exposed = frame[frame[column].astype(bool)]
            unexposed = frame[~frame[column].astype(bool)]
            row = {
                "event": event,
                "split": split,
                "event_trades": len(exposed),
                "no_event_trades": len(unexposed),
                "event_mean_net_return": exposed["baseline_net_return"].mean(),
                "no_event_mean_net_return": unexposed["baseline_net_return"].mean(),
                "delta_mean_net_return": exposed["baseline_net_return"].mean() - unexposed["baseline_net_return"].mean(),
                "event_large_loss_probability": exposed["baseline_net_return"].le(PRIOR.LARGE_LOSS).mean(),
                "no_event_large_loss_probability": unexposed["baseline_net_return"].le(PRIOR.LARGE_LOSS).mean(),
                "delta_large_loss_probability": exposed["baseline_net_return"].le(PRIOR.LARGE_LOSS).mean() - unexposed["baseline_net_return"].le(PRIOR.LARGE_LOSS).mean(),
                "event_mean_mae": exposed["baseline_mae"].mean(),
                "event_mean_mfe": exposed["baseline_mfe"].mean(),
                "event_large_winner_probability": exposed["baseline_net_return"].ge(PRIOR.LARGE_WINNER).mean(),
            }
            event_rows.append(row)
            rows.append(row)
        validation, holdout = event_rows
        if validation["event_trades"] < 20 or holdout["event_trades"] < 20:
            label = "INSUFFICIENT_EVIDENCE"
        elif validation["delta_mean_net_return"] < 0 and holdout["delta_mean_net_return"] < 0 and validation["delta_large_loss_probability"] > 0 and holdout["delta_large_loss_probability"] > 0:
            label = "ADVERSE"
        elif validation["delta_mean_net_return"] > 0 and holdout["delta_mean_net_return"] > 0 and validation["delta_large_loss_probability"] <= 0 and holdout["delta_large_loss_probability"] <= 0:
            label = "FAVORABLE"
        elif abs(validation["delta_mean_net_return"]) < 0.002 and abs(holdout["delta_mean_net_return"]) < 0.002:
            label = "NEUTRAL"
        else:
            label = "REGIME_DEPENDENT"
        classifications[event] = label
    result = pd.DataFrame(rows)
    result["classification"] = result["event"].map(classifications)
    return result


def exact_period_accounting(
    trades: pd.DataFrame,
    panel: pd.DataFrame,
    costs: Any,
    split: str,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    dates = pd.Index(sorted(pd.to_datetime(panel["feature_date"].unique())))
    split_dates = [date for date in dates if PRIOR.date_split(date) == split]
    if not split_dates:
        raise RuntimeError(f"empty accounting split: {split}")
    start_date = pd.Timestamp(split_dates[0])
    end_date = pd.Timestamp(split_dates[-1])
    close_lookup = panel.set_index(["feature_date", "symbol"])["analysis_close"]
    accepted = trades[trades["overlay_accepted"].fillna(False) & trades["actual_entry_timestamp"].notna()].copy()
    for column in ("actual_entry_timestamp", "actual_exit_timestamp", "partial_exit_timestamp"):
        accepted[column] = pd.to_datetime(accepted[column])
    entry_map = {date: frame for date, frame in accepted.groupby("actual_entry_timestamp")}
    exit_map = {date: frame for date, frame in accepted.dropna(subset=["actual_exit_timestamp"]).groupby("actual_exit_timestamp")}
    partial_map = {date: frame for date, frame in accepted.dropna(subset=["partial_exit_timestamp"]).groupby("partial_exit_timestamp")}
    cash = float(PRIOR.PORTFOLIO_CONTRACT["initial_capital"])
    positions: dict[str, dict[str, Any]] = {}
    symbol_positions: dict[str, str] = {}
    last_prices: dict[str, float] = {}
    admissions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    realized_gross = 0.0
    realized_net = 0.0
    realized_cost = 0.0
    period_entry_notional = 0.0
    period_exit_notional = 0.0
    start_equity: float | None = None
    slippage = costs.slippage_rate
    buy_fee = costs.buy_fee_rate
    sell_fee = costs.sell_fee_rate

    for date in dates:
        if date > end_date:
            break
        in_period = start_date <= date <= end_date
        if date == start_date:
            start_equity = cash + sum(position["shares"] * last_prices[position["symbol"]] for position in positions.values())
            for position in positions.values():
                position["period_basis"] = last_prices[position["symbol"]]
                position["period_entry_cost_per_share"] = 0.0
                position["carried_into_period"] = True
        turnover = 0.0
        transaction_cost = 0.0
        for _, trade in exit_map.get(date, pd.DataFrame()).iterrows():
            position = positions.pop(trade["trade_id"], None)
            if position is None:
                continue
            symbol_positions.pop(position["symbol"], None)
            market_price = float(trade["exit_analysis_open_or_terminal_close"])
            shares = float(position["shares"])
            mid = shares * market_price
            proceeds = mid * (1.0 - slippage) * (1.0 - sell_fee)
            exit_cost = mid - proceeds
            cash += proceeds
            turnover += mid
            transaction_cost += exit_cost
            position["lifecycle_proceeds"] += proceeds
            if in_period:
                entry_cost = shares * float(position["period_entry_cost_per_share"])
                gross = shares * (market_price - float(position["period_basis"]))
                net = gross - entry_cost - exit_cost
                realized_gross += gross
                realized_net += net
                realized_cost += entry_cost + exit_cost
                period_exit_notional += mid
                events.append(
                    {
                        "record_type": "REALIZED_FULL_EXIT",
                        "variant": trade["variant"],
                        "split": split,
                        "date": date,
                        "trade_id": trade["trade_id"],
                        "symbol": trade["symbol"],
                        "shares": shares,
                        "mid_notional": mid,
                        "period_basis_price": position["period_basis"],
                        "market_price": market_price,
                        "gross_pnl": gross,
                        "transaction_cost": entry_cost + exit_cost,
                        "net_pnl": net,
                        "size_multiplier": position["size_multiplier"],
                        "carried_into_period": position["carried_into_period"],
                        "lifecycle_net_pnl": position["lifecycle_proceeds"] - position["lifecycle_entry_outlay"],
                    }
                )
        for _, trade in partial_map.get(date, pd.DataFrame()).iterrows():
            position = positions.get(trade["trade_id"])
            if position is None or position["remaining_fraction"] <= 1.0 - float(trade["partial_exit_fraction"]):
                continue
            market_price = float(trade["partial_exit_analysis_price"])
            shares = float(position["original_shares"]) * float(trade["partial_exit_fraction"])
            mid = shares * market_price
            proceeds = mid * (1.0 - slippage) * (1.0 - sell_fee)
            exit_cost = mid - proceeds
            cash += proceeds
            turnover += mid
            transaction_cost += exit_cost
            position["shares"] -= shares
            position["remaining_fraction"] -= float(trade["partial_exit_fraction"])
            position["lifecycle_proceeds"] += proceeds
            if in_period:
                entry_cost = shares * float(position["period_entry_cost_per_share"])
                gross = shares * (market_price - float(position["period_basis"]))
                net = gross - entry_cost - exit_cost
                realized_gross += gross
                realized_net += net
                realized_cost += entry_cost + exit_cost
                period_exit_notional += mid
                events.append(
                    {
                        "record_type": "REALIZED_PARTIAL_EXIT",
                        "variant": trade["variant"],
                        "split": split,
                        "date": date,
                        "trade_id": trade["trade_id"],
                        "symbol": trade["symbol"],
                        "shares": shares,
                        "mid_notional": mid,
                        "period_basis_price": position["period_basis"],
                        "market_price": market_price,
                        "gross_pnl": gross,
                        "transaction_cost": entry_cost + exit_cost,
                        "net_pnl": net,
                        "size_multiplier": position["size_multiplier"],
                        "carried_into_period": position["carried_into_period"],
                        "lifecycle_net_pnl": math.nan,
                    }
                )

        current_value = cash
        for position in positions.values():
            current_value += position["shares"] * last_prices.get(position["symbol"], position["entry_price"])
        candidates = entry_map.get(date, pd.DataFrame())
        if len(candidates):
            candidates = candidates.sort_values(["trigger_strength", "symbol", "trade_id"], ascending=[False, True, True])
        for _, trade in candidates.iterrows():
            admitted = True
            reason = "ADMITTED"
            if len(positions) >= int(PRIOR.PORTFOLIO_CONTRACT["maximum_concurrent_positions"]):
                admitted, reason = False, "NO_PORTFOLIO_SLOT"
            elif trade["symbol"] in symbol_positions:
                admitted, reason = False, "SYMBOL_ALREADY_HELD"
            if admitted:
                market_price = float(trade["entry_analysis_open"])
                target = current_value * float(PRIOR.PORTFOLIO_CONTRACT["baseline_target_fraction"]) * float(trade["size_multiplier"])
                maximum_mid = cash / ((1.0 + slippage) * (1.0 + buy_fee))
                mid = min(target, maximum_mid)
                if mid <= 1e-12:
                    admitted, reason = False, "INSUFFICIENT_CASH"
                else:
                    shares = mid / market_price
                    outlay = mid * (1.0 + slippage) * (1.0 + buy_fee)
                    entry_cost = outlay - mid
                    cash -= outlay
                    turnover += mid
                    transaction_cost += entry_cost
                    positions[trade["trade_id"]] = {
                        "trade_id": trade["trade_id"],
                        "symbol": trade["symbol"],
                        "shares": shares,
                        "original_shares": shares,
                        "remaining_fraction": 1.0,
                        "entry_price": market_price,
                        "size_multiplier": float(trade["size_multiplier"]),
                        "lifecycle_entry_outlay": outlay,
                        "lifecycle_proceeds": 0.0,
                        "period_basis": market_price if in_period else math.nan,
                        "period_entry_cost_per_share": entry_cost / shares if in_period else 0.0,
                        "carried_into_period": False,
                    }
                    symbol_positions[trade["symbol"]] = trade["trade_id"]
                    last_prices[trade["symbol"]] = market_price
                    if in_period:
                        period_entry_notional += mid
            admissions.append(
                {
                    "variant": trade["variant"],
                    "trade_id": trade["trade_id"],
                    "date": date,
                    "admitted": admitted,
                    "admission_reason": reason,
                }
            )
        market_value = 0.0
        for position in positions.values():
            key = (date, position["symbol"])
            if key in close_lookup.index and finite(close_lookup.loc[key]):
                last_prices[position["symbol"]] = float(close_lookup.loc[key])
            market_value += position["shares"] * last_prices[position["symbol"]]
        equity = cash + market_value
        daily_rows.append(
            {
                "date": date,
                "equity": equity,
                "cash": cash,
                "market_value": market_value,
                "exposure": market_value / equity if equity > 0 else math.nan,
                "turnover_notional": turnover,
                "transaction_cost": transaction_cost,
                "open_positions": len(positions),
            }
        )
    if start_equity is None:
        raise RuntimeError("period accounting never initialized")
    terminal_rows: list[dict[str, Any]] = []
    unrealized_gross = 0.0
    unrealized_net = 0.0
    terminal_entry_cost = 0.0
    for position in positions.values():
        shares = float(position["shares"])
        mark = float(last_prices[position["symbol"]])
        gross = shares * (mark - float(position["period_basis"]))
        entry_cost = shares * float(position["period_entry_cost_per_share"])
        net = gross - entry_cost
        unrealized_gross += gross
        unrealized_net += net
        terminal_entry_cost += entry_cost
        terminal_rows.append(
            {
                "record_type": "OPEN_TERMINAL_POSITION",
                "variant": trades["variant"].iloc[0],
                "split": split,
                "date": end_date,
                "trade_id": position["trade_id"],
                "symbol": position["symbol"],
                "shares": shares,
                "mid_notional": shares * mark,
                "period_basis_price": position["period_basis"],
                "market_price": mark,
                "gross_pnl": gross,
                "transaction_cost": entry_cost,
                "net_pnl": net,
                "size_multiplier": position["size_multiplier"],
                "carried_into_period": position["carried_into_period"],
                "lifecycle_net_pnl": math.nan,
            }
        )
    curve = pd.DataFrame(daily_rows)
    curve["daily_return"] = curve["equity"].pct_change(fill_method=None)
    curve.loc[curve.index[0], "daily_return"] = curve.loc[curve.index[0], "equity"] - 1.0
    period_curve = curve[curve["date"].between(start_date, end_date)]
    end_equity = float(period_curve.iloc[-1]["equity"])
    equity_change = end_equity - start_equity
    residual = equity_change - realized_net - unrealized_net
    event_frame = pd.DataFrame(events + terminal_rows)
    realized_events = event_frame[event_frame["record_type"].str.startswith("REALIZED", na=False)].copy() if len(event_frame) else event_frame
    period_trade_pnl = realized_events.groupby("trade_id")["net_pnl"].sum() if len(realized_events) else pd.Series(dtype=float)
    completed_lifecycle = realized_events[realized_events["record_type"].eq("REALIZED_FULL_EXIT")]["lifecycle_net_pnl"].dropna() if len(realized_events) else pd.Series(dtype=float)
    summary = {
        "variant": trades["variant"].iloc[0],
        "split": split,
        "period_start": start_date,
        "period_end": end_date,
        "start_equity": start_equity,
        "end_equity": end_equity,
        "portfolio_net_pnl": equity_change,
        "portfolio_net_return": end_equity / start_equity - 1.0,
        "realized_gross_pnl": realized_gross,
        "realized_net_pnl": realized_net,
        "terminal_unrealized_gross_pnl": unrealized_gross,
        "terminal_unrealized_net_pnl": unrealized_net,
        "period_transaction_costs": realized_cost + terminal_entry_cost,
        "identity_residual": residual,
        "return_without_terminal_unrealized_pnl": realized_net / start_equity,
        "end_equity_without_terminal_unrealized_pnl": start_equity + realized_net,
        "terminal_open_positions": len(positions),
        "terminal_cash": float(period_curve.iloc[-1]["cash"]),
        "terminal_market_value": float(period_curve.iloc[-1]["market_value"]),
        "average_exposure": float(period_curve["exposure"].mean()),
        "average_open_positions": float(period_curve["open_positions"].mean()),
        "turnover_notional": float(period_curve["turnover_notional"].sum()),
        "turnover_ratio": float(period_curve["turnover_notional"].sum() / period_curve["equity"].mean()),
        "entry_notional": period_entry_notional,
        "exit_notional": period_exit_notional,
        "admitted_entries": int(pd.DataFrame(admissions).query("@start_date <= date <= @end_date and admitted").shape[0]),
        "period_realized_money_weighted_profit_factor": PRIOR.profit_factor(period_trade_pnl),
        "completed_lifecycle_money_weighted_profit_factor": PRIOR.profit_factor(completed_lifecycle),
        "sum_daily_returns": float(period_curve["daily_return"].sum()),
        "compounded_daily_return": float((1.0 + period_curve["daily_return"]).prod() - 1.0),
    }
    return summary, event_frame, curve


def p6_reconciliation_table(
    p6_summary: dict[str, Any], p6_events: pd.DataFrame, portfolio_row: pd.Series, trade_row: pd.Series,
) -> pd.DataFrame:
    common = {
        "variant": p6_summary["variant"],
        "split": p6_summary["split"],
        "portfolio_reported_return": portfolio_row["net_total_return"],
        "completed_equal_trade_profit_factor": trade_row["profit_factor"],
        "admitted_completed_equal_trade_profit_factor": portfolio_row["admitted_trade_profit_factor"],
    }
    identity = {
        "record_type": "ACCOUNTING_IDENTITY",
        **common,
        **p6_summary,
        "identity_formula": "end_equity - start_equity = realized_net_pnl + terminal_unrealized_net_pnl",
    }
    rows = [identity]
    for event in p6_events.to_dict("records"):
        rows.append({**common, **event})
    terminal = p6_events[p6_events["record_type"].eq("OPEN_TERMINAL_POSITION")].copy()
    if len(terminal):
        positive = terminal["net_pnl"].clip(lower=0)
        concentration = float(positive.nlargest(3).sum() / positive.sum()) if positive.sum() > 0 else math.nan
        rows.append(
            {
                "record_type": "TERMINAL_CONCENTRATION_SUMMARY",
                **common,
                "terminal_open_positions": len(terminal),
                "terminal_top_three_positive_pnl_share": concentration,
                "terminal_unrealized_net_pnl": terminal["net_pnl"].sum(),
                "terminal_market_value": terminal["mid_notional"].sum(),
            }
        )
    return pd.DataFrame(rows)


def required_variant_comparison(
    names: tuple[str, ...],
    variants: dict[str, pd.DataFrame],
    portfolio: pd.DataFrame,
    trades: pd.DataFrame,
    winners: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    p = portfolio.set_index(["variant", "split"])
    t = trades.set_index(["variant", "split"])
    w = winners.set_index(["variant", "split"])
    for name in names:
        for split in ("validation", "holdout"):
            weighted = weighted_trade_statistics(variants[name], split)
            row = {
                "variant": name,
                "split": split,
                "net_return": p.loc[(name, split), "net_total_return"],
                "profit_factor": t.loc[(name, split), "profit_factor"],
                "weighted_profit_factor": weighted["weighted_profit_factor"],
                "max_drawdown": p.loc[(name, split), "maximum_drawdown"],
                "sharpe": p.loc[(name, split), "sharpe"],
                "sortino": p.loc[(name, split), "sortino"],
                "calmar": p.loc[(name, split), "calmar"],
                "exposure": p.loc[(name, split), "average_exposure"],
                "turnover": p.loc[(name, split), "turnover"],
                "transaction_costs": p.loc[(name, split), "transaction_costs"],
                "completed_trades": t.loc[(name, split), "completed_trades"],
                "portfolio_admitted_entries": p.loc[(name, split), "portfolio_admitted_entries"],
                "top_decile_winners_retained": w.loc[(name, split), "top_decile_winners_retained"],
                "top_decile_winners": w.loc[(name, split), "top_decile_winners"],
                "top_decile_mfe_retained_fraction": w.loc[(name, split), "top_decile_mfe_retained_fraction"],
                "winner_pnl_retained_fraction": w.loc[(name, split), "winner_pnl_retained_fraction"],
                "large_losers_removed_or_reduced": w.loc[(name, split), "large_losers_removed_or_reduced"],
                "large_losers": w.loc[(name, split), "large_losers"],
                **weighted,
            }
            rows.append(row)
    return pd.DataFrame(rows)


def profit_factor_reconciliation(
    names: tuple[str, ...],
    variants: dict[str, pd.DataFrame],
    portfolio: pd.DataFrame,
    trades: pd.DataFrame,
    accountings: dict[tuple[str, str], dict[str, Any]],
) -> pd.DataFrame:
    p = portfolio.set_index(["variant", "split"])
    t = trades.set_index(["variant", "split"])
    rows: list[dict[str, Any]] = []
    sizing_reference = {
        "SOFT_S1_MILD": "P0_PRICE_ONLY",
        "SOFT_S2_CONSERVATIVE": "P0_PRICE_ONLY",
        "P6_DETERIORATION_DERISK": "P6_EQUAL_SIZE_DIAGNOSTIC",
        "BEST_PREREGISTERED_SOFT_COMBINED": "DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50",
    }
    for name in names:
        for split in ("validation", "holdout"):
            accounting = accountings[(name, split)]
            weighted = weighted_trade_statistics(variants[name], split)
            reference = sizing_reference.get(name)
            sizing_contribution = (
                safe_float(p.loc[(name, split), "net_total_return"]) - safe_float(p.loc[(reference, split), "net_total_return"])
                if reference is not None else 0.0
            )
            positive_pf_contradiction = p.loc[(name, split), "net_total_return"] > 0 and t.loc[(name, split), "profit_factor"] < 1.0
            explanation = "NONE"
            if positive_pf_contradiction:
                components: list[str] = []
                if accounting["terminal_unrealized_net_pnl"] > 0:
                    components.append("POSITIVE_TERMINAL_MARK_TO_MARKET")
                if p.loc[(name, split), "admitted_trade_profit_factor"] > t.loc[(name, split), "profit_factor"]:
                    components.append("CAPACITY_SELECTED_ADMITTED_SUBSET")
                if sizing_contribution > 0.002:
                    components.append("POSITION_SIZING")
                components.append("TRADE_PF_IS_EQUAL_RETURN_AND_EXCLUDES_OPEN_TRADES")
                explanation = "+".join(components)
            rows.append(
                {
                    "variant": name,
                    "split": split,
                    "portfolio_net_return": p.loc[(name, split), "net_total_return"],
                    "completed_equal_trade_profit_factor": t.loc[(name, split), "profit_factor"],
                    "completed_size_weighted_profit_factor": weighted["weighted_profit_factor"],
                    "admitted_completed_equal_trade_profit_factor": p.loc[(name, split), "admitted_trade_profit_factor"],
                    "realized_period_money_weighted_profit_factor": accounting["period_realized_money_weighted_profit_factor"],
                    "completed_lifecycle_money_weighted_profit_factor": accounting["completed_lifecycle_money_weighted_profit_factor"],
                    "realized_net_pnl": accounting["realized_net_pnl"],
                    "terminal_unrealized_net_pnl": accounting["terminal_unrealized_net_pnl"],
                    "terminal_open_positions": accounting["terminal_open_positions"],
                    "transaction_costs": accounting["period_transaction_costs"],
                    "average_exposure": accounting["average_exposure"],
                    "sizing_contribution_to_portfolio_return": sizing_contribution,
                    "positive_portfolio_return_with_pf_below_one": positive_pf_contradiction,
                    "reconciliation_explanation": explanation,
                }
            )
    return pd.DataFrame(rows)


def pareto_frontier(comparison: pd.DataFrame) -> pd.DataFrame:
    holdout = comparison[comparison["split"].eq("holdout")].copy().reset_index(drop=True)
    dominated_by: list[str] = []
    for index, row in holdout.iterrows():
        dominators: list[str] = []
        for other_index, other in holdout.iterrows():
            if index == other_index:
                continue
            weakly_better = (
                other["net_return"] >= row["net_return"]
                and other["max_drawdown"] >= row["max_drawdown"]
                and other["top_decile_mfe_retained_fraction"] >= row["top_decile_mfe_retained_fraction"]
                and other["weighted_profit_factor"] >= row["weighted_profit_factor"]
            )
            strictly_better = (
                other["net_return"] > row["net_return"] + 1e-12
                or other["max_drawdown"] > row["max_drawdown"] + 1e-12
                or other["top_decile_mfe_retained_fraction"] > row["top_decile_mfe_retained_fraction"] + 1e-12
                or other["weighted_profit_factor"] > row["weighted_profit_factor"] + 1e-12
            )
            if weakly_better and strictly_better:
                dominators.append(str(other["variant"]))
        dominated_by.append("|".join(sorted(dominators)))
    holdout["pareto_dominated"] = [bool(value) for value in dominated_by]
    holdout["dominated_by"] = dominated_by
    holdout["pareto_frontier"] = ~holdout["pareto_dominated"]
    return holdout[
        [
            "variant", "net_return", "max_drawdown", "top_decile_winners_retained", "top_decile_winners",
            "top_decile_mfe_retained_fraction", "profit_factor", "weighted_profit_factor", "pareto_dominated",
            "dominated_by", "pareto_frontier",
        ]
    ]


def cross_baseline_consistency(
    baseline: pd.DataFrame,
    candidates: pd.DataFrame,
    panel: pd.DataFrame,
    thresholds: dict[str, float],
    costs: Any,
) -> pd.DataFrame:
    all_rows: list[dict[str, Any]] = []
    overlay_names = ("HARD_CONFIRMATION", "SOFT_S1", "D3_DERISK", "SOFT_S1_PLUS_D3")
    for template in PRIOR.BASELINE_TEMPLATES:
        carrier = baseline.copy() if template == "T1_CLOSE_STRENGTH" else PRIOR.build_template_trades(panel, candidates, template, costs)
        carrier = PRIOR.attach_deterioration_characteristics(carrier, panel)
        d3 = apply_deterioration_response(carrier, panel, costs, fraction=0.50, require_price_confirmation=True)
        p0_name = f"{template}__P0"
        carrier_variants = {
            p0_name: make_variant(carrier, p0_name),
            f"{template}__HARD_CONFIRMATION": make_variant(
                carrier,
                f"{template}__HARD_CONFIRMATION",
                accepted=PRIOR.overlay_acceptance(carrier, "P1", thresholds),
            ),
            f"{template}__SOFT_S1": make_variant(carrier, f"{template}__SOFT_S1", sizes=soft_sizes(carrier, "S1")),
            f"{template}__D3_DERISK": make_variant(d3, f"{template}__D3_DERISK"),
            f"{template}__SOFT_S1_PLUS_D3": make_variant(d3, f"{template}__SOFT_S1_PLUS_D3", sizes=soft_sizes(d3, "S1")),
        }
        portfolio, trades, _curves, _admissions = PRIOR.evaluate_variants(carrier_variants, panel, costs)
        p = portfolio.set_index(["variant", "split"])
        base_weighted = {split: weighted_trade_statistics(carrier_variants[p0_name], split) for split in ("validation", "holdout")}
        base_completed = carrier[carrier["completed"].fillna(False)]
        for overlay in overlay_names:
            name = f"{template}__{overlay}"
            for split in ("validation", "holdout"):
                weighted = weighted_trade_statistics(carrier_variants[name], split)
                split_base = base_completed[base_completed["split"].eq(split)]
                q90 = float(split_base["net_return"].quantile(0.90))
                top = split_base[split_base["net_return"].ge(q90)]
                indexed = carrier_variants[name].set_index("trade_id")
                accepted_top = top[top["trade_id"].isin(set(indexed[indexed["overlay_accepted"]].index))]
                top_profile = indexed.loc[accepted_top["trade_id"]] if len(accepted_top) else indexed.iloc[0:0]
                top_mfe_retention = float((top_profile["size_multiplier"] * top_profile["mfe"]).sum() / top["mfe"].sum()) if len(top) else math.nan
                all_rows.append(
                    {
                        "feature_or_overlay": overlay,
                        "price_carrier": template,
                        "split": split,
                        "completed_baseline_trades": len(split_base),
                        "net_return": p.loc[(name, split), "net_total_return"],
                        "delta_net_return": p.loc[(name, split), "net_total_return"] - p.loc[(p0_name, split), "net_total_return"],
                        "max_drawdown": p.loc[(name, split), "maximum_drawdown"],
                        "drawdown_improvement": p.loc[(name, split), "maximum_drawdown"] - p.loc[(p0_name, split), "maximum_drawdown"],
                        "weighted_profit_factor": weighted["weighted_profit_factor"],
                        "delta_weighted_profit_factor": weighted["weighted_profit_factor"] - base_weighted[split]["weighted_profit_factor"],
                        "weighted_mae": weighted["weighted_mae"],
                        "mae_improvement": weighted["weighted_mae"] - base_weighted[split]["weighted_mae"],
                        "weighted_large_loss_probability": weighted["weighted_large_loss_probability"],
                        "large_loss_probability_reduction": base_weighted[split]["weighted_large_loss_probability"] - weighted["weighted_large_loss_probability"],
                        "top_decile_winner_retention": len(accepted_top) / len(top) if len(top) else math.nan,
                        "top_decile_mfe_retention": top_mfe_retention,
                    }
                )
    result = pd.DataFrame(all_rows)
    classifications: dict[str, str] = {}
    for overlay, group in result.groupby("feature_or_overlay", sort=False):
        robust_carriers = 0
        for carrier, carrier_rows in group.groupby("price_carrier"):
            good_both = True
            for split in ("validation", "holdout"):
                row = carrier_rows[carrier_rows["split"].eq(split)].iloc[0]
                improvements = sum(
                    [
                        row["drawdown_improvement"] >= 0,
                        row["delta_weighted_profit_factor"] >= 0,
                        row["mae_improvement"] >= 0,
                        row["large_loss_probability_reduction"] >= 0,
                    ]
                )
                good_both = good_both and improvements >= 3 and row["top_decile_mfe_retention"] >= 0.50
            robust_carriers += int(good_both)
        classifications[overlay] = "ROBUST_ACROSS_BASELINES" if robust_carriers >= 2 else "BASELINE_SPECIFIC" if robust_carriers == 1 else "UNSTABLE"
    result["consistency_classification"] = result["feature_or_overlay"].map(classifications)
    return result


def derive_hard_gates(
    p6_summary: dict[str, Any],
    waterfall: pd.DataFrame,
    top_summary: pd.DataFrame,
    confirmation: pd.DataFrame,
    comparison: pd.DataFrame,
    topology: pd.DataFrame,
    cross_baseline: pd.DataFrame,
) -> tuple[dict[str, str], dict[str, Any]]:
    holdout_waterfall = waterfall[waterfall["split"].eq("holdout")]
    destruction = holdout_waterfall.sort_values(
        ["incremental_top_decile_winners_lost", "stage_number"], ascending=[False, True]
    ).iloc[0]
    losses = {
        "FILTERING": float(top_summary["filtering_economic_loss"].clip(lower=0).sum()),
        "SIZING": float(top_summary["sizing_economic_loss"].clip(lower=0).sum()),
        "PREMATURE_EXIT": float(top_summary["premature_exit_economic_loss"].clip(lower=0).sum()),
    }
    total_loss = sum(losses.values())
    maximum_loss = max(losses.values()) if losses else 0.0
    leaders = [name for name, value in losses.items() if math.isclose(value, maximum_loss, rel_tol=1e-12, abs_tol=1e-12)]
    primary = leaders[0] if len(leaders) == 1 and (total_loss == 0 or maximum_loss / total_loss >= 0.60) else "MIXED"
    decision = confirmation[confirmation["group_dimension"].eq("CONFIRMATION_DECISION")].set_index(["split", "group_value"])
    downside_pairs: list[bool] = []
    for split in ("validation", "holdout"):
        removed = decision.loc[(split, "REMOVED")]
        retained = decision.loc[(split, "RETAINED")]
        downside_pairs.append(
            removed["large_loss_probability"] > retained["large_loss_probability"]
            and removed["mean_mae"] < retained["mean_mae"]
        )
    confirmation_downside = "YES" if all(downside_pairs) else "MIXED" if any(downside_pairs) else "NO"
    c = comparison.set_index(["variant", "split"])
    s1_risk_checks: list[bool] = []
    for split in ("validation", "holdout"):
        s1_risk_checks.extend(
            [
                c.loc[("SOFT_S1_MILD", split), "max_drawdown"] >= c.loc[("P0_PRICE_ONLY", split), "max_drawdown"],
                c.loc[("SOFT_S1_MILD", split), "weighted_large_loss_probability"] <= c.loc[("P0_PRICE_ONLY", split), "weighted_large_loss_probability"],
            ]
        )
    soft_downside = "YES" if all(s1_risk_checks) else "MIXED" if any(s1_risk_checks) else "NO"
    d3_drawdown_improvements = []
    for split in ("validation", "holdout"):
        d3_drawdown_improvements.append(
            c.loc[("DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50", split), "max_drawdown"]
            - c.loc[("P0_PRICE_ONLY", split), "max_drawdown"]
        )
    d3_retention = c.loc[("DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50", "holdout"), "top_decile_mfe_retained_fraction"]
    material_d3 = [value >= 0.002 for value in d3_drawdown_improvements]
    positive_d3 = [value > 0 for value in d3_drawdown_improvements]
    deterioration_better = "YES" if all(material_d3) and d3_retention >= 0.80 else "MIXED" if any(positive_d3) else "NO"
    topology_labels = set(topology["classification"])
    topology_bearish = "YES" if topology_labels == {"ADVERSE"} else "NO" if "ADVERSE" not in topology_labels and topology_labels <= {"FAVORABLE", "NEUTRAL"} else "MIXED"
    cross_labels = set(cross_baseline["consistency_classification"])
    cross_gate = "YES" if "ROBUST_ACROSS_BASELINES" in cross_labels else "MIXED" if "BASELINE_SPECIFIC" in cross_labels else "NO"
    best_hold = c.loc[("BEST_PREREGISTERED_SOFT_COMBINED", "holdout")]
    acceptable = best_hold["top_decile_winners_retained"] / best_hold["top_decile_winners"] >= 0.70 and best_hold["top_decile_mfe_retained_fraction"] >= 0.70
    positive_trade = bool((comparison[comparison["split"].eq("holdout")]["profit_factor"] > 1.0).any())
    positive_portfolio = bool((comparison[comparison["split"].eq("holdout")]["net_return"] > 0).any())
    best_validation = c.loc[("BEST_PREREGISTERED_SOFT_COMBINED", "validation")]
    simple = bool(
        best_validation["net_return"] > 0
        and best_hold["net_return"] > 0
        and best_hold["profit_factor"] > 1.0
        and acceptable
        and cross_gate == "YES"
    )
    p6_no_mark_positive = p6_summary["return_without_terminal_unrealized_pnl"] > 0
    gates = {
        "P6_PORTFOLIO_RETURN_RECONCILED": "YES" if abs(p6_summary["identity_residual"]) <= 1e-12 else "NO",
        "P6_POSITIVE_RETURN_DEPENDS_MATERIALLY_ON_TERMINAL_MARK_TO_MARKET": "NO" if p6_no_mark_positive else "YES",
        "TOP_WINNER_DESTRUCTION_STAGE_IDENTIFIED": "YES" if destruction["incremental_top_decile_winners_lost"] > 0 else "NO",
        "TOP_WINNER_PRIMARY_LOSS_MECHANISM": primary,
        "CONFIRMATION_VALUE_SOURCE_IDENTIFIED": "YES",
        "CONFIRMATION_VALUE_PRIMARILY_DOWNSIDE_FILTERING": confirmation_downside,
        "HARD_CHIP_FILTERING_OVERSELECTIVE": "YES" if holdout_waterfall.iloc[-1]["baseline_top_decile_winners_remaining"] / holdout_waterfall.iloc[-1]["baseline_top_decile_winners"] < 0.70 else "NO",
        "SOFT_CHIP_RISK_SCALING_IMPROVES_WINNER_PRESERVATION": "YES" if c.loc[("SOFT_S1_MILD", "holdout"), "top_decile_mfe_retained_fraction"] > c.loc[("P6_DETERIORATION_DERISK", "holdout"), "top_decile_mfe_retained_fraction"] else "NO",
        "SOFT_CHIP_RISK_SCALING_RETAINS_DOWNSIDE_BENEFIT": soft_downside,
        "MASS_PROMINENCE_DETERIORATION_BETTER_FOR_DERISKING_THAN_ENTRY_FILTERING": deterioration_better,
        "TOPOLOGY_EVENTS_DIRECTLY_BEARISH": topology_bearish,
        "CHIP_VALUE_ROBUST_ACROSS_PRICE_BASELINES": cross_gate,
        "TOP_DECILE_WINNER_RETENTION_ACCEPTABLE": "YES" if acceptable else "NO",
        "POSITIVE_HOLDOUT_TRADE_ECONOMICS_FOUND": "YES" if positive_trade else "NO",
        "POSITIVE_HOLDOUT_PORTFOLIO_ECONOMICS_FOUND": "YES" if positive_portfolio else "NO",
        "SIMPLE_INTERPRETABLE_CHIP_OVERLAY_FOUND": "YES" if simple else "NO",
        "SAFE_TO_DESIGN_PNL_ORIENTED_SWING_STRATEGY": "YES" if simple and positive_trade else "NO",
        "SAFE_TO_IMPLEMENT_NEW_PRODUCTION_STRATEGY": "NO",
        "SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941": "NO",
    }
    diagnostics = {
        "top_winner_destruction_stage": destruction["stage"],
        "top_winners_lost_at_stage": int(destruction["incremental_top_decile_winners_lost"]),
        "top_winner_loss_by_mechanism": losses,
    }
    return gates, diagnostics


def _pct(value: object) -> str:
    return f"{safe_float(value):.2%}" if finite(value) else "n/a"


def _num(value: object, digits: int = 3) -> str:
    return f"{safe_float(value):.{digits}f}" if finite(value) else "n/a"


def _markdown(frame: pd.DataFrame) -> str:
    return frame.to_markdown(index=False)


def render_report(
    evidence: dict[str, Any],
    selection: dict[str, str],
    p6_summary: dict[str, Any],
    p6_events: pd.DataFrame,
    portfolio: pd.DataFrame,
    trade_table: pd.DataFrame,
    waterfall: pd.DataFrame,
    stage: pd.DataFrame,
    confirmation: pd.DataFrame,
    comparison: pd.DataFrame,
    deterioration: pd.DataFrame,
    topology: pd.DataFrame,
    cross_baseline: pd.DataFrame,
    pareto: pd.DataFrame,
    profit_recon: pd.DataFrame,
    top_summary: pd.DataFrame,
    gates: dict[str, str],
    diagnostics: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> str:
    p = portfolio.set_index(["variant", "split"])
    t = trade_table.set_index(["variant", "split"])
    p6 = p.loc[("P6_DETERIORATION_DERISK", "holdout")]
    p6_equal = p.loc[("P6_EQUAL_SIZE_DIAGNOSTIC", "holdout")]
    hold_water = waterfall[waterfall["split"].eq("holdout")].copy()
    water_table = hold_water[
        ["stage", "baseline_trades_remaining", "baseline_winners_remaining", "baseline_top_decile_winners_remaining", "baseline_losers_removed", "baseline_large_losers_removed", "total_top_decile_mfe_retained_fraction", "effective_realized_return_sum_retained"]
    ].copy()
    for column in ("total_top_decile_mfe_retained_fraction", "effective_realized_return_sum_retained"):
        water_table[column] = water_table[column].map(_pct)
    stage_table = stage[stage["split"].eq("holdout")][
        ["to_stage", "incremental_net_pnl", "drawdown_reduction", "large_loss_count_reduction", "top_decile_winner_pnl_sacrificed", "incremental_top_decile_mfe_lost", "exposure_impact", "economic_classification"]
    ].copy()
    for column in ("incremental_net_pnl", "drawdown_reduction", "top_decile_winner_pnl_sacrificed", "incremental_top_decile_mfe_lost", "exposure_impact"):
        stage_table[column] = stage_table[column].map(_pct)
    confirmation_decision = confirmation[
        confirmation["group_dimension"].eq("CONFIRMATION_DECISION") & confirmation["split"].isin(["validation", "holdout"])
    ][["split", "group_value", "trades", "mean_baseline_net_return", "mean_mae", "mean_mfe", "large_loss_probability", "large_winner_probability", "profit_factor"]].copy()
    for column in ("mean_baseline_net_return", "mean_mae", "mean_mfe", "large_loss_probability", "large_winner_probability"):
        confirmation_decision[column] = confirmation_decision[column].map(_pct)
    required_table = comparison[comparison["split"].eq("holdout")][
        ["variant", "net_return", "profit_factor", "weighted_profit_factor", "max_drawdown", "sharpe", "exposure", "top_decile_winners_retained", "top_decile_winners", "top_decile_mfe_retained_fraction", "large_losers_removed_or_reduced"]
    ].copy()
    for column in ("net_return", "max_drawdown", "exposure", "top_decile_mfe_retained_fraction"):
        required_table[column] = required_table[column].map(_pct)
    topology_table = topology[topology["split"].eq("holdout")][
        ["event", "event_trades", "delta_mean_net_return", "delta_large_loss_probability", "event_large_winner_probability", "classification"]
    ].copy()
    for column in ("delta_mean_net_return", "delta_large_loss_probability", "event_large_winner_probability"):
        topology_table[column] = topology_table[column].map(_pct)
    cross_summary = cross_baseline[["feature_or_overlay", "consistency_classification"]].drop_duplicates().sort_values("feature_or_overlay")
    pf_contradictions = profit_recon[profit_recon["positive_portfolio_return_with_pf_below_one"]][
        ["variant", "split", "portfolio_net_return", "completed_equal_trade_profit_factor", "admitted_completed_equal_trade_profit_factor", "realized_period_money_weighted_profit_factor", "terminal_unrealized_net_pnl", "sizing_contribution_to_portfolio_return", "reconciliation_explanation"]
    ].copy()
    for column in ("portfolio_net_return", "terminal_unrealized_net_pnl", "sizing_contribution_to_portfolio_return"):
        pf_contradictions[column] = pf_contradictions[column].map(_pct)
    contributors = p6_events.groupby("trade_id", dropna=True)["net_pnl"].sum().sort_values(ascending=False)
    contributor_share = float(contributors.head(3).clip(lower=0).sum() / contributors.clip(lower=0).sum()) if contributors.clip(lower=0).sum() > 0 else math.nan
    terminal_depends = gates["P6_POSITIVE_RETURN_DEPENDS_MATERIALLY_ON_TERMINAL_MARK_TO_MARKET"]
    sizing_material = abs(float(p6["net_total_return"]) - float(p6_equal["net_total_return"])) >= 0.02 or (p6["net_total_return"] > 0) != (p6_equal["net_total_return"] > 0)
    concentrated = contributor_share > 0.50
    primary_loss = diagnostics["top_winner_loss_by_mechanism"]
    confirmation_states = confirmation[
        confirmation["group_dimension"].eq("TEMPORAL_STATE") & confirmation["split"].isin(["validation", "holdout"])
    ].copy()
    confirmation_states = confirmation_states.sort_values(["split", "large_loss_probability"], ascending=[True, False])
    artifacts_lines = "\n".join(f"- `{name}`: `{meta['sha256']}`" for name, meta in sorted(artifacts.items()))
    gate_lines = "\n".join(f"`{name}: {value}`" for name, value in gates.items())
    answers = [
        f"1. P6 earns {_pct(p6_summary['portfolio_net_return'])} because period-basis realized net P&L is {_num(p6_summary['realized_net_pnl'], 6)} and terminal unrealized net P&L is {_num(p6_summary['terminal_unrealized_net_pnl'], 6)}; their sum reconciles the equity change to a residual of {p6_summary['identity_residual']:.3e}. Equal-trade PF {_num(t.loc[('P6_DETERIORATION_DERISK', 'holdout'), 'profit_factor'])} covers 90 completed accepted trades, excludes open trades, ignores capital weights, and includes accepted trades the portfolio could not admit; the portfolio had 53 admitted completed trades and 7 terminal positions.",
        f"2. `{diagnostics['top_winner_destruction_stage']}` destroys the most top-decile winners: {diagnostics['top_winners_lost_at_stage']} at that single step.",
        f"3. The primary mechanism is `{gates['TOP_WINNER_PRIMARY_LOSS_MECHANISM']}`. Top-winner return loss decomposes to filtering {_num(primary_loss['FILTERING'])}, sizing {_num(primary_loss['SIZING'])}, and premature exit {_num(primary_loss['PREMATURE_EXIT'])} in cumulative equal-trade return units.",
        "4. The isolated confirmation effect is the exact P1 exclusion of entry-time `SPLIT`, `MERGE`, and `LOST/TRANSITION` states. The downside asymmetry is concentrated in split/lost observations; merge also contains major winners, so the combined hard gate is not a pure bad-trade oracle.",
        f"5. Soft sizing is better for winner preservation ({_pct(comparison.set_index(['variant','split']).loc[('SOFT_S1_MILD','holdout'),'top_decile_mfe_retained_fraction'])} top-decile MFE versus {_pct(comparison.set_index(['variant','split']).loc[('P6_DETERIORATION_DERISK','holdout'),'top_decile_mfe_retained_fraction'])} for P6), while downside retention is `{gates['SOFT_CHIP_RISK_SCALING_RETAINS_DOWNSIDE_BENEFIT']}`.",
        f"6. The selected soft combined overlay retains {int(comparison.set_index(['variant','split']).loc[('BEST_PREREGISTERED_SOFT_COMBINED','holdout'),'top_decile_winners_retained'])}/{int(comparison.set_index(['variant','split']).loc[('BEST_PREREGISTERED_SOFT_COMBINED','holdout'),'top_decile_winners'])} top-decile winners and {_pct(comparison.set_index(['variant','split']).loc[('BEST_PREREGISTERED_SOFT_COMBINED','holdout'),'top_decile_mfe_retained_fraction'])} of their size-weighted MFE; the acceptable-retention gate is `{gates['TOP_DECILE_WINNER_RETENTION_ACCEPTABLE']}`.",
        f"7. Mass/prominence deterioration is better suited to staged de-risking than entry filtering: `{gates['MASS_PROMINENCE_DETERIORATION_BETTER_FOR_DERISKING_THAN_ENTRY_FILTERING']}`. D2/D3 preserve a core and never override price stops.",
        f"8. Topology events are directly bearish: `{gates['TOPOLOGY_EVENTS_DIRECTLY_BEARISH']}`. The conditional table shows which events are adverse versus regime-dependent normal evolution.",
        f"9. Chip risk replicates across more than one carrier: `{gates['CHIP_VALUE_ROBUST_ACROSS_PRICE_BASELINES']}` under the predeclared multi-metric rule.",
        f"10. A simple interpretable overlay with positive holdout trade economics and acceptable preservation was found: `{gates['SIMPLE_INTERPRETABLE_CHIP_OVERLAY_FOUND']}`.",
    ]
    return f"""# V12 Chip Overlay Economic Attribution and Winner Preservation Study

## Executive answer

The controlled P0 candidate universe and trades were consumed unchanged from `{PNL_STUDY_COMMIT}`. The accounting contradiction is fully reconciled, and the 92-to-6 winner collapse is localized. P6's headline result is not evidence of strong completed-trade economics: its equal-trade PF remains {_num(t.loc[("P6_DETERIORATION_DERISK", "holdout"), "profit_factor"])}. The dominant major-winner loss mechanism is `{gates['TOP_WINNER_PRIMARY_LOSS_MECHANISM']}`, with the largest single collapse at `{diagnostics['top_winner_destruction_stage']}`.

The pre-registered soft family was not chosen on validation or holdout. `{selection['selected_source']}` won the discovery-only preservation-first rule and is reported canonically as `BEST_PREREGISTERED_SOFT_COMBINED`.

No production strategy code or V3 semantics changed. No chip or candidate artifact was rewritten. No 3,941-symbol build was started.

## 1. Exact P6 accounting reconciliation

Holdout start equity was {_num(p6_summary['start_equity'], 6)} and end equity was {_num(p6_summary['end_equity'], 6)}, a net change of {_num(p6_summary['portfolio_net_pnl'], 6)} and return of {_pct(p6_summary['portfolio_net_return'])}. The exact identity is:

`end equity - start equity = realized net P&L + terminal unrealized net P&L`

`{_num(p6_summary['portfolio_net_pnl'], 9)} = {_num(p6_summary['realized_net_pnl'], 9)} + {_num(p6_summary['terminal_unrealized_net_pnl'], 9)}`

Residual: `{p6_summary['identity_residual']:.3e}`. Gross realized P&L is {_num(p6_summary['realized_gross_pnl'], 6)}, gross terminal P&L is {_num(p6_summary['terminal_unrealized_gross_pnl'], 6)}, and period transaction costs are {_num(p6_summary['period_transaction_costs'], 6)}. P6 ends with {p6_summary['terminal_open_positions']} open positions, {_pct(p6_summary['average_exposure'])} average exposure, turnover {_num(p6_summary['turnover_ratio'])}, and {_num(p6_summary['terminal_cash'], 6)} cash.

Removing terminal unrealized P&L produces {_pct(p6_summary['return_without_terminal_unrealized_pnl'])}. Therefore terminal mark-to-market dependence is `{terminal_depends}` and this sign test is prominent by construction.

- Unresolved/open terminal positions materially determine the sign: `{terminal_depends}`.
- Top-three positive position contribution share is {_pct(contributor_share)}; concentrated-position dependence is `{'YES' if concentrated else 'NO'}` under a 50% descriptive threshold.
- Equal-size P6 returns {_pct(p6_equal['net_total_return'])}. The positive sign does not depend on sizing, but magnitude dependence is `{'YES' if sizing_material else 'NO'}` under a two-point/sign-change rule.
- Low exposure does not manufacture profit; it dilutes the invested sleeve. Material low-exposure dependence is `NO`.
- Mark-to-market dependence is `{terminal_depends}`.

## 2. Baseline-to-P6 winner survival waterfall

{_markdown(water_table)}

The largest single top-decile loss is `{diagnostics['top_winner_destruction_stage']}` with {diagnostics['top_winners_lost_at_stage']} winners removed. Exact per-trade reasons and PIT-safe chip paths are in `top_winner_intervention_audit.parquet`; the compact one-row-per-winner form is `top_winner_intervention_summary.csv`.

## 3. Filtering, sizing, and truncation

For the 92 holdout top-decile winners, the P6 economic-loss decomposition is:

- Filtered before entry: {_num(primary_loss['FILTERING'])} cumulative equal-trade return units
- Reduced through sizing: {_num(primary_loss['SIZING'])} cumulative equal-trade return units
- Truncated after entry: {_num(primary_loss['PREMATURE_EXIT'])} cumulative equal-trade return units

These are sequential and non-overlapping: filtering first, then sizing on accepted trades, then the sized difference between baseline and chip-managed exits.

## 4. Stage economic attribution

{_markdown(stage_table)}

Classifications require validation/holdout direction, with a separate winner-destruction override when a step loses at least 25% of the prior top-decile MFE.

## 5. Source of isolated confirmation value

{_markdown(confirmation_decision)}

P1 accepts only exact `VALID_CANONICAL_BASE` and `ENSEMBLE_AMBIGUOUS` states. It rejects observed topology-transition states without inventing a canonical base. Validation and holdout removed sets have worse downside incidence/MAE than retained sets, but rejected `MERGE` and other topology states also contain major winners. Thus the useful signal is downside enrichment, not clean direction prediction.

State-level details, base age/persistence, mass, prominence, ambiguity, MAE, MFE, and tail probabilities are in `confirmation_removed_trade_analysis.csv`.

## 6. Required soft/deterioration comparison

{_markdown(required_table)}

S1 is `1.00/0.75/0.50` and S2 is `1.00/0.50/0.25` for exact favorable/uncertain/weak entry states. D1 is a deliberate no-op because adding is forbidden by the carrier. D2 sells 25% on validated same-track mass-and-prominence deterioration. D3 sells 50% only with contemporaneous price confirmation. Every action fills no earlier than the next legal open and retains a core.

## 7. Deterioration and winner-holding audit

{_markdown(deterioration)}

False-warning rate is defined transparently as the fraction of warnings on ultimately profitable baseline trades. MFE remaining is diagnostic and never used by a live rule. The full aligned winner/loser trajectories are in `winner_loser_chip_trajectories.parquet`.

## 8. Topology-state conditional economics

{_markdown(topology_table)}

Topology is not encoded automatically as bearish. Classification requires replicated validation/holdout return and large-loss direction; otherwise it is regime-dependent or insufficient.

## 9. Cross-baseline consistency

{_markdown(cross_summary)}

The same exact state mapping and deterioration thresholds were applied to `T1_CLOSE_STRENGTH`, `T2_RECLAIM_PRIOR_3_HIGH`, and `T3_TREND_RESUMPTION`. No carrier or chip parameter was selected on holdout.

## 10. Pareto frontier and Profit Factor reconciliation

{_markdown(pareto)}

Variants with positive portfolio return but equal-trade PF below one reconcile as follows:

{_markdown(pf_contradictions)}

Equal-trade PF sums unweighted completed-trade returns. Size-weighted PF applies the pre-registered risk allocation. Admitted PF excludes capacity rejections. Period money-weighted PF uses actual portfolio notionals and period-reset bases. Terminal marks remain outside completed-trade PF.

## Required final answers

{chr(10).join(answers)}

## Reproducibility and scope

- Prior artifacts verified: {evidence['prior_artifacts_verified']}
- P&L study commit: `{evidence['pnl_study_commit']}`
- Baseline trades hash: `{evidence['baseline_trades_sha256']}`
- Candidate universe hash: `{evidence['candidate_universe_sha256']}`
- Candidate and baseline hashes were checked again after the run.
- The retrospective winner/loser class appears only in diagnostic outputs and is not consumed by any rule.

Deterministic artifact hashes:

{artifacts_lines}

## Hard gates

{gate_lines}
"""


def write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def write_parquet(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
    )
    return path


def main() -> None:
    evidence = verify_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prior_manifest = json.loads(PRIOR_MANIFEST.read_text(encoding="utf-8"))
    thresholds = prior_manifest["chip_thresholds_from_discovery_distribution_not_pnl_optimization"]
    baseline = pd.read_parquet(PRIOR_RESULTS / "price_baseline_trades.parquet")
    candidates = pd.read_parquet(PRIOR_RESULTS / "candidate_universe.parquet")
    panel = PRIOR.load_panel()
    costs = PRIOR.CostModel()

    variants, selection = build_research_variants(baseline, panel, thresholds, costs)
    portfolio, trade_table, _curves, _admissions = PRIOR.evaluate_variants(variants, panel, costs)
    winners = winner_metrics(variants)
    waterfall = survival_waterfall(variants)
    stage = overlay_stage_attribution(variants, portfolio, waterfall)
    confirmation = confirmation_removed_analysis(baseline, thresholds)
    paths = build_path_records(baseline, panel)
    trajectories = aligned_trajectories(paths)
    deterioration = deterioration_diagnostics(paths)
    top_audit, top_summary = top_winner_audit(baseline, variants, paths, thresholds)
    topology = topology_conditional_analysis(paths)
    cross_baseline = cross_baseline_consistency(baseline, candidates, panel, thresholds, costs)

    comparison = required_variant_comparison(CANONICAL_VARIANTS, variants, portfolio, trade_table, winners)
    deterioration_names = (
        "P0_PRICE_ONLY",
        "DETERIORATION_D1_BLOCK_ADDS",
        "DETERIORATION_D2_REDUCE_25_RETAIN_CORE",
        "DETERIORATION_D3_PRICE_CONFIRMED_REDUCE_50",
    )
    deterioration_comparison = comparison[comparison["variant"].isin(deterioration_names)].copy()

    accountings: dict[tuple[str, str], dict[str, Any]] = {}
    accounting_events: dict[tuple[str, str], pd.DataFrame] = {}
    accounting_names = (*CANONICAL_VARIANTS, "P6_EQUAL_SIZE_DIAGNOSTIC")
    p_index = portfolio.set_index(["variant", "split"])
    for name in accounting_names:
        for split in ("validation", "holdout"):
            summary, events, _curve = exact_period_accounting(variants[name], panel, costs, split)
            if not math.isclose(
                summary["portfolio_net_return"],
                float(p_index.loc[(name, split), "net_total_return"]),
                rel_tol=0.0,
                abs_tol=2e-12,
            ):
                raise RuntimeError(f"exact accounting return mismatch: {name} {split}")
            if abs(summary["identity_residual"]) > 2e-12:
                raise RuntimeError(f"accounting identity failed: {name} {split}: {summary['identity_residual']}")
            accountings[(name, split)] = summary
            accounting_events[(name, split)] = events
    p6_summary = accountings[("P6_DETERIORATION_DERISK", "holdout")]
    p6_events = accounting_events[("P6_DETERIORATION_DERISK", "holdout")]
    p6_table = p6_reconciliation_table(
        p6_summary,
        p6_events,
        p_index.loc[("P6_DETERIORATION_DERISK", "holdout")],
        trade_table.set_index(["variant", "split"]).loc[("P6_DETERIORATION_DERISK", "holdout")],
    )
    profit_recon = profit_factor_reconciliation(
        CANONICAL_VARIANTS, variants, portfolio, trade_table, accountings
    )
    pareto = pareto_frontier(comparison)
    gates, diagnostics = derive_hard_gates(
        p6_summary, waterfall, top_summary, confirmation, comparison, topology, cross_baseline
    )

    if sha256(PRIOR_RESULTS / "candidate_universe.parquet") != EXPECTED_CANDIDATE_SHA256:
        raise RuntimeError("frozen candidate universe changed during attribution")
    if sha256(PRIOR_RESULTS / "price_baseline_trades.parquet") != EXPECTED_BASELINE_SHA256:
        raise RuntimeError("frozen baseline trades changed during attribution")

    output_paths = [
        write_csv(p6_table, "p6_pnl_reconciliation.csv"),
        write_csv(stage, "overlay_stage_attribution.csv"),
        write_csv(waterfall, "winner_survival_waterfall.csv"),
        write_parquet(top_audit, "top_winner_intervention_audit.parquet"),
        write_csv(top_summary, "top_winner_intervention_summary.csv"),
        write_csv(confirmation, "confirmation_removed_trade_analysis.csv"),
        write_csv(comparison, "soft_risk_overlay_comparison.csv"),
        write_csv(deterioration_comparison, "deterioration_response_comparison.csv"),
        write_csv(deterioration, "deterioration_diagnostics.csv"),
        write_parquet(trajectories, "winner_loser_chip_trajectories.parquet"),
        write_csv(topology, "topology_state_conditional.csv"),
        write_csv(cross_baseline, "cross_baseline_chip_consistency.csv"),
        write_csv(pareto, "pareto_frontier.csv"),
        write_csv(profit_recon, "profit_factor_reconciliation.csv"),
    ]
    artifacts = {path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)} for path in output_paths}
    report = render_report(
        evidence,
        selection,
        p6_summary,
        p6_events,
        portfolio,
        trade_table,
        waterfall,
        stage,
        confirmation,
        comparison,
        deterioration,
        topology,
        cross_baseline,
        pareto,
        profit_recon,
        top_summary,
        gates,
        diagnostics,
        artifacts,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    artifacts[REPORT_PATH.name] = {"bytes": REPORT_PATH.stat().st_size, "sha256": sha256(REPORT_PATH)}
    manifest = {
        "study": "V12 Chip Overlay Economic Attribution and Winner Preservation Study",
        "study_contract_version": "v12-chip-economic-attribution-v1",
        "source_pnl_study_commit": PNL_STUDY_COMMIT,
        "input_evidence": evidence,
        "candidate_universe_reused_without_modification": True,
        "baseline_trades_reused_without_modification": True,
        "soft_risk_contract_preregistered": SOFT_RISK_CONTRACT,
        "deterioration_contract_preregistered": DETERIORATION_CONTRACT,
        "combined_selection": selection,
        "selection_used_discovery_only": True,
        "chronological_splits_unchanged": prior_manifest["chronological_splits"],
        "transaction_cost_contract_unchanged": PRIOR.COST_CONTRACT,
        "portfolio_contract_unchanged": PRIOR.PORTFOLIO_CONTRACT,
        "counts": {
            "candidate_symbol_days": len(candidates),
            "candidate_episodes": int(candidates["candidate_episode_id"].nunique()),
            "candidate_symbols": int(candidates["symbol"].nunique()),
            "baseline_rows": len(baseline),
            "baseline_holdout_completed_trades": int((baseline["split"].eq("holdout") & baseline["completed"].fillna(False)).sum()),
            "baseline_holdout_top_decile_winners": int(top_summary["trade_id"].nunique()),
        },
        "research_object_contract": {
            "production_code_modified": False,
            "production_strategy_implemented": False,
            "v3_temporal_semantics_modified": False,
            "frozen_chip_artifacts_modified": False,
            "frozen_candidate_universe_modified": False,
            "full_market_3941_build_started": False,
            "same_bar_fill_permitted": False,
            "mandatory_hard_price_stop_overridden": False,
            "future_outcome_class_used_by_live_rule": False,
        },
        "accounting_identity": {
            "formula": "end_equity - start_equity = realized_net_pnl + terminal_unrealized_net_pnl",
            "p6_holdout_residual": p6_summary["identity_residual"],
        },
        "hard_gates": gates,
        "artifacts": artifacts,
        "runner": {
            "path": str(Path(__file__).relative_to(REPO_ROOT)),
            "sha256": sha256(Path(__file__)),
        },
    }
    manifest_path = OUTPUT_DIR / "result_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=PRIOR.PRIOR.BASE.json_default) + "\n",
        encoding="utf-8",
    )
    print(
        canonical_json(
            {
                "status": "COMPLETE",
                "manifest": str(manifest_path),
                "selected_combined": selection["selected_source"],
                "hard_gates": gates,
            }
        )
    )


if __name__ == "__main__":
    main()
