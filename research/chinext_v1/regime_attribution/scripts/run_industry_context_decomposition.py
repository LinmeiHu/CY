#!/usr/bin/env python3
"""Execute preregistered industry-versus-stock right-tail attribution."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_phase2_feature_library as phase2  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-ICD-001_spec.json"
TRANSITIONS = WORK / "artifacts/pre_entry_transitions.csv"
DAILY_REGIME = WORK / "artifacts/daily_regime_features.parquet"
OUTPUT_TABLE = WORK / "artifacts/industry_context_decomposition.csv"
OUTPUT_JSON = WORK / "artifacts/industry_context_attribution.json"
REPORT = WORK / "reports/industry_context_attribution.md"

PRIMARY = ("industry_market_relative20", "stock_industry_residual20")
COMPANION = {
    "industry_market_relative20": "stock_industry_residual20",
    "stock_industry_residual20": "industry_market_relative20",
}
MEAN_MEDIAN_NEIGHBOR = {
    "industry_market_relative20": "industry_market_relative20_median",
    "stock_industry_residual20": "stock_industry_residual20_median",
}
HORIZON_NEIGHBOR = {
    "industry_market_relative20": "industry_market_relative60",
    "stock_industry_residual20": "stock_industry_residual60",
}
BASE_CONTROLS = (
    "entry_rs_score",
    "entry_mom20",
    "entry_box_width",
    "entry_minvol_location",
    "entry_breakout_volume_ratio",
    "index_return_20d",
    "index_realized_vol20",
    "breadth_composite",
    "entry_beta60",
    "entry_log_amount20",
    "log_peer_count",
)
SECONDARY_ENDPOINTS = (
    "winner20",
    "false_breakout",
    "severe_loss",
    "mfe",
    "round_trip_return",
)


class IndustryContextError(RuntimeError):
    """Raised when an identity, PIT, sample, or model invariant fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-ICD-001":
        raise IndustryContextError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_INDUSTRY_OUTCOME_JOIN":
        raise IndustryContextError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatch: dict[str, Any] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise IndustryContextError(f"missing bound input: {name}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatch[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatch:
        raise IndustryContextError(f"frozen input mismatch: {mismatch}")
    phase2.validate_inputs()
    return spec, identities


def load_base() -> pd.DataFrame:
    frame = pd.read_csv(TRANSITIONS)
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise IndustryContextError("transition input is not 399 unique cycles")
    for column in ("entry_signal_date", "entry_execution_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise")
    if not (frame.entry_signal_date < frame.entry_execution_date).all():
        raise IndustryContextError("entry signal/execution order is invalid")
    required = [
        "round_trip_return",
        "realized_pnl",
        "mfe",
        "entry_year",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "holding_trading_days",
        "canonical_exit_reason",
        *BASE_CONTROLS[:-1],
    ]
    if frame[required].replace([np.inf, -np.inf], np.nan).dropna(
        subset=[column for column in required if column != "breadth_composite"]
    ).shape[0] != 399:
        raise IndustryContextError("required accepted trade values are missing")
    for column in ("extreme_winner", "winner20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)

    daily = pd.read_parquet(
        DAILY_REGIME,
        columns=[
            "baseline_block",
            "trade_date",
            "feature_available_at",
            "first_applicable_trade_date",
            "index_return_60d",
        ],
    )
    for column in ("trade_date", "feature_available_at", "first_applicable_trade_date"):
        daily[column] = pd.to_datetime(daily[column])
    frame = frame.merge(
        daily,
        left_on=["baseline_block", "entry_signal_date"],
        right_on=["baseline_block", "trade_date"],
        validate="many_to_one",
        how="left",
    )
    causal = (
        frame.trade_date.notna()
        & (frame.feature_available_at.dt.date == frame.entry_signal_date.dt.date)
        & (frame.first_applicable_trade_date > frame.entry_signal_date)
        & (frame.first_applicable_trade_date <= frame.entry_execution_date)
    )
    if not causal.all():
        raise IndustryContextError("index60 control has invalid applicability")
    return frame


def construct_industry_decomposition(
    base: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="chinext_v1_icd001_") as temporary:
        transient_root = Path(temporary)
        manifest = phase2.extended.materialize_transient_inputs(transient_root)
        expected = spec["transient_contract"]
        if manifest["canonical_sha256"] != expected["canonical_sha256"]:
            raise IndustryContextError("extended transient canonical identity changed")
        if manifest["membership"]["sha256"] != expected["membership_sha256"]:
            raise IndustryContextError("extended transient membership identity changed")
        connection = phase2.duckdb.connect()
        connection.execute("SET threads=1")
        phase2.create_membership_tables(connection, transient_root / "daily_membership.parquet")
        panel_counts = phase2.create_panel_tables(connection, transient_root)
        phase2.create_stock_features(connection)
        identities = base[
            ["baseline_block", "trade_id", "symbol", "entry_signal_date"]
        ].copy()
        connection.register("trade_identity", identities)
        decomposition = connection.execute(
            """
            WITH own AS (
              SELECT t.*,e.industry,e.ret20 AS stock_ret20,e.ret60 AS stock_ret60,
                (SELECT count(*) FROM eligible_features a
                 WHERE a.baseline_block=t.baseline_block
                   AND a.trade_date=CAST(t.entry_signal_date AS DATE)) AS eligible_count,
                (SELECT count(*) FROM eligible_features a
                 WHERE a.baseline_block=t.baseline_block
                   AND a.trade_date=CAST(t.entry_signal_date AS DATE)
                   AND a.industry IS NOT NULL) AS mapped_count
              FROM trade_identity t
              LEFT JOIN eligible_features e
                ON e.baseline_block=t.baseline_block
               AND e.trade_date=CAST(t.entry_signal_date AS DATE)
               AND e.symbol=t.symbol
            )
            SELECT o.*,
              count(p.symbol) FILTER (WHERE p.symbol<>o.symbol AND p.ret20 IS NOT NULL)
                AS peer20_count,
              count(p.symbol) FILTER (WHERE p.symbol<>o.symbol AND p.ret60 IS NOT NULL)
                AS peer60_count,
              avg(p.ret20) FILTER (WHERE p.symbol<>o.symbol AND p.ret20 IS NOT NULL)
                AS peer20_mean,
              median(p.ret20) FILTER (WHERE p.symbol<>o.symbol AND p.ret20 IS NOT NULL)
                AS peer20_median,
              avg(p.ret60) FILTER (WHERE p.symbol<>o.symbol AND p.ret60 IS NOT NULL)
                AS peer60_mean,
              median(p.ret60) FILTER (WHERE p.symbol<>o.symbol AND p.ret60 IS NOT NULL)
                AS peer60_median
            FROM own o
            LEFT JOIN eligible_features p
              ON p.baseline_block=o.baseline_block
             AND p.trade_date=CAST(o.entry_signal_date AS DATE)
             AND p.industry=o.industry
            GROUP BY ALL
            ORDER BY o.trade_id
            """
        ).fetchdf()
        connection.close()

    if len(decomposition) != 399 or decomposition.trade_id.nunique() != 399:
        raise IndustryContextError("industry audit did not return 399 unique entries")
    if decomposition.industry.isna().any():
        raise IndustryContextError("an entry lacks a PIT-valid industry label")
    if not (decomposition.mapped_count == decomposition.eligible_count).all():
        raise IndustryContextError("industry mapping coverage is not complete")
    eligible = decomposition[
        (decomposition.peer20_count >= spec["sample"]["minimum_peer_count"])
        & (decomposition.peer60_count >= spec["sample"]["minimum_peer_count"])
    ].copy()
    if len(eligible) != spec["sample"]["expected_eligible_cycles"]:
        raise IndustryContextError(
            f"eligible sample changed: {len(eligible)} != {spec['sample']['expected_eligible_cycles']}"
        )
    if eligible[
        [
            "stock_ret20",
            "stock_ret60",
            "peer20_mean",
            "peer20_median",
            "peer60_mean",
            "peer60_median",
        ]
    ].isna().any().any():
        raise IndustryContextError("eligible industry decomposition has missing returns")
    frame = base.merge(eligible, on=["baseline_block", "trade_id", "symbol", "entry_signal_date"])
    if len(frame) != len(eligible):
        raise IndustryContextError("industry sample merge changed cardinality")
    if int(frame.extreme_winner.sum()) < spec["sample"]["minimum_extreme_winners"]:
        raise IndustryContextError("eligible extreme-winner count is below frozen minimum")

    frame["industry_market_relative20"] = frame.peer20_mean - frame.index_return_20d
    frame["stock_industry_residual20"] = frame.stock_ret20 - frame.peer20_mean
    frame["industry_market_relative20_median"] = (
        frame.peer20_median - frame.index_return_20d
    )
    frame["stock_industry_residual20_median"] = frame.stock_ret20 - frame.peer20_median
    frame["industry_market_relative60"] = frame.peer60_mean - frame.index_return_60d
    frame["stock_industry_residual60"] = frame.stock_ret60 - frame.peer60_mean
    frame["log_peer_count"] = np.log(frame.peer20_count.astype(float))
    audit = {
        "panel_counts": panel_counts,
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
        "all_entries": 399,
        "eligible_cycles": int(len(frame)),
        "eligible_extreme_winners": int(frame.extreme_winner.sum()),
        "eligible_winner20": int(frame.winner20.sum()),
        "industry_labels": int(frame.industry.nunique()),
        "minimum_peer_count": int(frame.peer20_count.min()),
        "median_peer_count": float(frame.peer20_count.median()),
        "mapping_coverage_failures": 0,
        "pit_or_causal_failures": 0,
        "strategy_replays": 0,
        "post_entry_price_rows_read": 0,
    }
    return frame, audit


def partial_rank(
    frame: pd.DataFrame,
    feature: str,
    endpoint: str,
    *,
    extra_controls: tuple[str, ...] = (),
    category_controls: tuple[str, ...] = ("entry_year",),
) -> dict[str, Any]:
    controls = [*BASE_CONTROLS, COMPANION[feature], *extra_controls]
    columns = [feature, endpoint, *controls, *category_controls]
    data = frame[columns].replace([np.inf, -np.inf], np.nan).dropna().copy()
    result = {"n": int(len(data)), "partial_rank_rho": None, "p_value": None}
    if len(data) < 200 or data[feature].nunique() < 2 or data[endpoint].nunique() < 2:
        return result
    predictor = data[feature].rank(pct=True, method="average").to_numpy(float)
    if pd.api.types.is_bool_dtype(data[endpoint]) or set(data[endpoint].unique()).issubset(
        {0, 1, False, True}
    ):
        outcome = data[endpoint].astype(float).to_numpy()
    else:
        outcome = data[endpoint].rank(pct=True, method="average").to_numpy(float)
    ranked = pd.DataFrame(index=data.index)
    for control in controls:
        ranked[control] = data[control].rank(pct=True, method="average")
    design_parts = [np.ones((len(data), 1)), ranked.to_numpy(float)]
    for category in category_controls:
        dummies = pd.get_dummies(
            data[category].fillna("MISSING").astype(str),
            prefix=category,
            drop_first=True,
            dtype=float,
        )
        if len(dummies.columns):
            design_parts.append(dummies.to_numpy(float))
    design = np.column_stack(design_parts)
    x_residual = predictor - design @ np.linalg.lstsq(design, predictor, rcond=None)[0]
    y_residual = outcome - design @ np.linalg.lstsq(design, outcome, rcond=None)[0]
    if np.std(x_residual) == 0 or np.std(y_residual) == 0:
        return result
    estimate = pearsonr(x_residual, y_residual)
    result["partial_rank_rho"] = wla.finite_or_none(estimate.statistic)
    result["p_value"] = wla.finite_or_none(estimate.pvalue)
    return result


def controlled_loyo(frame: pd.DataFrame, feature: str, endpoint: str) -> dict[str, Any]:
    full = partial_rank(frame, feature, endpoint)
    loyo = {
        str(year): partial_rank(frame[frame.entry_year != year], feature, endpoint)
        for year in range(2018, 2026)
    }
    positive = sum(
        item["partial_rank_rho"] is not None and item["partial_rank_rho"] > 0
        for item in loyo.values()
    )
    return {**full, "loyo": loyo, "loyo_positive_count": int(positive)}


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    raw = {feature: wla.rank_association(frame, feature, "extreme_winner") for feature in PRIMARY}
    q_values = wla.bh_adjust({feature: raw[feature]["p_value"] for feature in PRIMARY})
    top4 = wla.deterministic_top_flag(frame, 4)
    extreme_symbols = sorted(frame.loc[frame.extreme_winner, "symbol"].astype(str).unique())
    result: dict[str, Any] = {}
    passing: list[str] = []
    raw_passing: list[str] = []
    for feature in PRIMARY:
        controlled = controlled_loyo(frame, feature, "extreme_winner")
        median_neighbor = wla.rank_association(
            frame, MEAN_MEDIAN_NEIGHBOR[feature], "extreme_winner"
        )
        horizon_neighbor = wla.rank_association(
            frame, HORIZON_NEIGHBOR[feature], "extreme_winner"
        )
        ex_top4 = wla.rank_association(frame.loc[~top4], feature, "extreme_winner")
        holding_exit = partial_rank(
            frame,
            feature,
            "extreme_winner",
            extra_controls=("holding_trading_days",),
            category_controls=("entry_year", "canonical_exit_reason"),
        )
        security = wla.omit_group_sensitivity(
            frame, feature, "extreme_winner", "symbol", extreme_symbols
        )
        industry = wla.omit_group_sensitivity(
            frame, feature, "extreme_winner", "industry"
        )
        peer10 = wla.rank_association(frame[frame.peer20_count >= 10], feature, "extreme_winner")
        blocks = {
            str(name): wla.safe_spearman(rows[feature], rows.extreme_winner)
            for name, rows in frame.groupby("baseline_block", sort=True)
        }
        raw_gate = bool(
            raw[feature]["rho"] is not None
            and raw[feature]["rho"] >= 0.10
            and q_values[feature] is not None
            and q_values[feature] <= 0.10
            and raw[feature]["within_year_rank_rho"] is not None
            and raw[feature]["within_year_rank_rho"] > 0
            and raw[feature]["loyo_positive_count"] >= 7
        )
        neighbor_gate = bool(
            median_neighbor["rho"] is not None
            and median_neighbor["rho"] > 0
            and median_neighbor["loyo_positive_count"] >= 6
            and horizon_neighbor["rho"] is not None
            and horizon_neighbor["rho"] > 0
            and horizon_neighbor["loyo_positive_count"] >= 6
        )
        controlled_gate = bool(
            controlled["partial_rank_rho"] is not None
            and controlled["partial_rank_rho"] >= 0.10
            and controlled["loyo_positive_count"] >= 7
        )
        falsification_gate = bool(
            ex_top4["rho"] is not None
            and ex_top4["rho"] > 0
            and holding_exit["partial_rank_rho"] is not None
            and holding_exit["partial_rank_rho"] > 0
            and security["positive_fraction"] is not None
            and security["positive_fraction"] >= 0.80
            and industry["positive_fraction"] is not None
            and industry["positive_fraction"] >= 0.80
            and (peer10["rho"] is None or peer10["rho"] > 0)
        )
        passes = raw_gate and neighbor_gate and controlled_gate and falsification_gate
        if raw_gate:
            raw_passing.append(feature)
        if passes:
            passing.append(feature)
        result[feature] = {
            "raw": raw[feature],
            "bh_q_value": q_values[feature],
            "controlled": controlled,
            "median_neighbor": median_neighbor,
            "horizon60_neighbor": horizon_neighbor,
            "ex_global_top1pct_pnl": ex_top4,
            "holding_duration_exit_reason_control": holding_exit,
            "leave_one_extreme_security_out": security,
            "leave_one_industry_out": industry,
            "peer_count_ge10": peer10,
            "baseline_block": blocks,
            "raw_gate": raw_gate,
            "neighbor_gate": neighbor_gate,
            "controlled_gate": controlled_gate,
            "falsification_gate": falsification_gate,
            "passes": passes,
        }
    secondary = {
        feature: {
            endpoint: wla.rank_association(frame, feature, endpoint)
            for endpoint in SECONDARY_ENDPOINTS
        }
        for feature in PRIMARY
    }
    industry_pass = "industry_market_relative20" in passing
    stock_pass = "stock_industry_residual20" in passing
    if industry_pass and not stock_pass:
        decision = "DEEPEN"
        mechanism = "INDUSTRY_WIDE_PRIMARY"
    elif stock_pass and not industry_pass:
        decision = "PIVOT"
        mechanism = "STOCK_SPECIFIC_PRIMARY"
    elif industry_pass and stock_pass:
        decision = "REFINE"
        mechanism = "BOTH_COMPONENTS_SURVIVE"
    elif raw_passing:
        decision = "PIVOT"
        mechanism = "RAW_ASSOCIATION_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        mechanism = "NEITHER_COMPONENT_SURVIVES"
    return {
        "experiment_id": "EXP-ICD-001",
        "decision": decision,
        "mechanism_verdict": mechanism,
        "raw_passing_components": raw_passing,
        "passing_components": passing,
        "primary": result,
        "secondary": secondary,
        "controls": [*BASE_CONTROLS, "companion_component", "entry_year"],
        "strategy_modification": "NONE",
    }


def fmt(value: Any, digits: int = 3) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.{digits}f}"


def build_report(frame: pd.DataFrame, audit: dict[str, Any], result: dict[str, Any]) -> str:
    lines = [
        "# Industry context decomposition of CHINEXT V1 right-tail entries",
        "",
        "EXP-ICD-001 separates same-industry peer strength from stock-specific residual strength at the completed-close entry signal. It is exploratory mechanism evidence over consumed outcomes, not a filter or strategy experiment.",
        "",
        "## PIT and sample audit",
        "",
        f"- All entries: `{audit['all_entries']}`; fixed >=5-peer sample: `{audit['eligible_cycles']}`; extreme winners: `{audit['eligible_extreme_winners']}`; winner20: `{audit['eligible_winner20']}`.",
        f"- PIT-valid industry labels in the fixed sample: `{audit['industry_labels']}`; peer count minimum/median: `{audit['minimum_peer_count']}` / `{audit['median_peer_count']:.1f}`.",
        f"- Mapping/PIT failures: `{audit['mapping_coverage_failures']}` / `{audit['pit_or_causal_failures']}`; strategy replays: `{audit['strategy_replays']}`; post-entry prices: `{audit['post_entry_price_rows_read']}`.",
        "- Peers are contemporaneously basic-eligible, share the entry security's source-notice-valid industry label, and exclude the entry security itself.",
        "",
        "## Competing primary mechanisms",
        "",
        "| Component | Raw rho | BH q | Within-year rho | LOYO + | Controlled rho | Controlled LOYO + | Median neighbor | 60d neighbor | Pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for feature in PRIMARY:
        item = result["primary"][feature]
        lines.append(
            f"| {feature} | {fmt(item['raw']['rho'])} | {fmt(item['bh_q_value'])} | "
            f"{fmt(item['raw']['within_year_rank_rho'])} | {item['raw']['loyo_positive_count']}/8 | "
            f"{fmt(item['controlled']['partial_rank_rho'])} | {item['controlled']['loyo_positive_count']}/8 | "
            f"{fmt(item['median_neighbor']['rho'])} | {fmt(item['horizon60_neighbor']['rho'])} | "
            f"{'YES' if item['passes'] else 'NO'} |"
        )
    lines += [
        "",
        "The fixed residual design controls the competing component, V1 entry RS/momentum/box/minimum-volume/breakout-volume state, market return/volatility, frozen breadth, trailing beta, traded-amount liquidity, peer count, and entry year.",
        "",
        "## Active falsification",
        "",
        "| Component | Ex-top-1% rho | Holding/exit rho | Security omission + | Industry omission + | >=10-peer rho | Falsification pass |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for feature in PRIMARY:
        item = result["primary"][feature]
        lines.append(
            f"| {feature} | {fmt(item['ex_global_top1pct_pnl']['rho'])} | "
            f"{fmt(item['holding_duration_exit_reason_control']['partial_rank_rho'])} | "
            f"{fmt(item['leave_one_extreme_security_out']['positive_fraction'])} | "
            f"{fmt(item['leave_one_industry_out']['positive_fraction'])} | "
            f"{fmt(item['peer_count_ge10']['rho'])} | "
            f"{'YES' if item['falsification_gate'] else 'NO'} |"
        )
    lines += [
        "",
        "## Fixed outcome-class medians",
        "",
        "| Outcome class | N | Industry-market relative20 | Stock-industry residual20 |",
        "|---|---:|---:|---:|",
    ]
    for outcome_class, rows in frame.groupby("outcome_class", sort=True):
        lines.append(
            f"| {outcome_class} | {len(rows)} | {fmt(rows.industry_market_relative20.median())} | "
            f"{fmt(rows.stock_industry_residual20.median())} |"
        )
    lines += [
        "",
        "## Scientific decision",
        "",
        f"`{result['decision']}` / `{result['mechanism_verdict']}`. Passing components: `{', '.join(result['passing_components']) or 'none'}`.",
        "",
        "No observed historical relationship is a threshold, filter, ranking change, or deployable rule. Industry labels are bounded PIT-B and all outcomes are consumed.",
        "",
        "## Strategy candidate",
        "",
        "None. EXP-ICD-001 authorizes no V1 modification.",
        "",
    ]
    return "\n".join(lines)


def clean_json(value: Any) -> Any:
    return wla.clean_json(value)


def main() -> int:
    spec, identities = validate_spec()
    base = load_base()
    frame, audit = construct_industry_decomposition(base, spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_MECHANISM_EVIDENCE",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "industry",
        "peer20_count",
        "peer60_count",
        "stock_ret20",
        "stock_ret60",
        "peer20_mean",
        "peer20_median",
        "peer60_mean",
        "peer60_median",
        "industry_market_relative20",
        "stock_industry_residual20",
        "industry_market_relative20_median",
        "stock_industry_residual20_median",
        "industry_market_relative60",
        "stock_industry_residual60",
        "outcome_class",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
        "realized_pnl",
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(OUTPUT_JSON, json.dumps(clean_json(result), indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, build_report(frame, audit, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
