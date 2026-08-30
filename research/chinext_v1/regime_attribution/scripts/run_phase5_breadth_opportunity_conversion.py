#!/usr/bin/env python3
"""Execute EXP-P5-001 breadth opportunity, conversion, path, and exit attribution."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
SPEC = WORK / "experiments/EXP-P5-001_spec.json"
FEATURES = WORK / "artifacts/daily_regime_features.parquet"
TRADES = WORK / "artifacts/yearly_trades.csv"
BASELINE = WORK / "artifacts/baseline_manifest.json"
P4_SPEC = WORK / "experiments/EXP-P4-002_spec.json"
P4_RESULT = WORK / "artifacts/breadth_incrementality.json"
OUTPUT_TRADES = WORK / "artifacts/trade_mechanism_attribution.csv"
OUTPUT_COHORTS = WORK / "artifacts/entry_cohort_attribution.csv"
OUTPUT_JSON = WORK / "artifacts/breadth_opportunity_conversion.json"
REPORT = WORK / "reports/phase5_breadth_opportunity_conversion.md"

EXPECTED_SPEC = "25806c3528fa6bf9c5657218fa26054a9ef86df24b5344602136812d644300b7"
EXPECTED = {
    FEATURES: "5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6",
    TRADES: "77f28da56a3e36801373b0b356a6e36236095b17dbdb3183a8b1b0a4c8ab3deb",
    BASELINE: "682b45455442f00e15e6273622ab6566d1c5c1d94069efc5fbbd40cb17f0977b",
    P4_SPEC: "f2416ab0f902ec458f01f5bb0caf0460f0a978a4658ba5a0d03ae81800c3041e",
    P4_RESULT: "0c8a4daa293db99e173b642976b11def80f5f50b30eca2d5f061f8efdd388b4f",
}
COMPONENTS = [
    "breadth_above_ma20",
    "breadth_positive_return20",
    "breadth_above_ma20_change20",
]
MIN_CORRELATION_SAMPLE = 20


class MechanismError(RuntimeError):
    """Raised when the frozen mechanism attribution contract fails."""


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


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite_or_none(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def safe_spearman(
    feature: Iterable[Any], outcome: Iterable[Any], minimum: int = MIN_CORRELATION_SAMPLE
) -> dict[str, Any]:
    data = pd.DataFrame({"feature": feature, "outcome": outcome}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    result = {"n": int(len(data)), "rho": None, "p_value": None}
    if len(data) < minimum or data.feature.nunique() < 2 or data.outcome.nunique() < 2:
        return result
    estimate = spearmanr(data.feature.astype(float), data.outcome.astype(float))
    result["rho"] = finite_or_none(estimate.statistic)
    result["p_value"] = finite_or_none(estimate.pvalue)
    return result


def same_sign_count(full: float | None, estimates: dict[str, float | None]) -> int:
    if full is None or full == 0:
        return 0
    return sum(value is not None and value * full > 0 for value in estimates.values())


def add_breadth_composite(frame: pd.DataFrame, minimum: int = 300) -> pd.DataFrame:
    out = frame.copy()
    ranks: list[str] = []
    for component in COMPONENTS:
        rank_name = f"{component}_within_year_rank"
        out[rank_name] = out.groupby("entry_year", sort=False)[component].rank(
            method="average", pct=True
        )
        ranks.append(rank_name)
    out["breadth_composite"] = out[ranks].mean(axis=1, skipna=False)
    valid = out.breadth_composite.dropna()
    if len(valid) < minimum:
        raise MechanismError("breadth composite has insufficient complete coverage")
    bins = pd.qcut(valid, 3, labels=["LOW", "MIDDLE", "HIGH"], duplicates="raise")
    out["breadth_tercile"] = pd.Series(index=out.index, dtype="object")
    out.loc[valid.index, "breadth_tercile"] = bins.astype(str)
    if set(out.breadth_tercile.dropna()) != {"LOW", "MIDDLE", "HIGH"}:
        raise MechanismError("breadth composite did not form three feature-only bins")
    return out


def add_fixed_outcomes(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["opportunity20"] = out.mfe >= 0.20
    out["opportunity50"] = out.mfe >= 0.50
    out["converted20"] = out.round_trip_return >= 0.20
    out["converted50"] = out.round_trip_return >= 0.50
    out["severe_loss"] = out.round_trip_return <= -0.10
    out["extreme_loss"] = out.round_trip_return <= -0.20
    out["false_breakout"] = (out.mfe < 0.10) & (out.round_trip_return <= 0)
    out["capture_ratio_opportunity20"] = np.where(
        out.opportunity20, out.round_trip_return / out.mfe, np.nan
    )
    out["conversion20_within_opportunity"] = np.where(
        out.opportunity20, out.converted20.astype(float), np.nan
    )
    out["conversion50_within_opportunity"] = np.where(
        out.opportunity50, out.converted50.astype(float), np.nan
    )
    return out


def validate_and_join() -> tuple[dict[str, Any], pd.DataFrame, dict[str, Any]]:
    if sha256_file(SPEC) != EXPECTED_SPEC:
        raise MechanismError("EXP-P5-001 spec hash mismatch")
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_MECHANISM_RESULT":
        raise MechanismError("EXP-P5-001 is not frozen before results")
    actual = {str(path): sha256_file(path) for path in EXPECTED}
    mismatch = {
        str(path): {"expected": expected, "actual": actual[str(path)]}
        for path, expected in EXPECTED.items()
        if actual[str(path)] != expected
    }
    if mismatch:
        raise MechanismError(f"mechanism input identity mismatch: {mismatch}")
    trades = pd.read_csv(TRADES)
    features = pd.read_parquet(FEATURES)
    features["trade_date"] = pd.to_datetime(features.trade_date)
    trades["entry_signal_date"] = pd.to_datetime(trades.entry_signal_date)
    trades["entry_execution_date"] = pd.to_datetime(trades.entry_execution_date)
    trades["exit_signal_date"] = pd.to_datetime(trades.exit_signal_date)
    trades["exit_execution_date"] = pd.to_datetime(trades.exit_execution_date)
    joined = trades.merge(
        features[
            [
                "baseline_block",
                "trade_date",
                "first_applicable_trade_date",
                *COMPONENTS,
            ]
        ],
        left_on=["baseline_block", "entry_signal_date"],
        right_on=["baseline_block", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    joined["first_applicable_trade_date"] = pd.to_datetime(
        joined.first_applicable_trade_date
    )
    if len(joined) != 399 or joined.trade_date.isna().any():
        raise MechanismError("entry feature join did not reconcile 399 cycles")
    causal = (
        (joined.trade_date == joined.entry_signal_date)
        & (joined.first_applicable_trade_date > joined.entry_signal_date)
        & (joined.first_applicable_trade_date <= joined.entry_execution_date)
    )
    if not causal.all():
        raise MechanismError(f"causal entry join failure: {joined.loc[~causal].iloc[0].trade_id}")
    joined["entry_year"] = joined.entry_signal_date.dt.year
    joined["entry_quarter"] = joined.entry_signal_date.dt.to_period("Q").astype(str)
    joined = add_fixed_outcomes(add_breadth_composite(joined))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    execution_hash = {
        block: details["execution_ledger_sha256"]
        for block, details in baseline["blocks"].items()
    }
    joined["source_execution_ledger_sha256"] = joined.baseline_block.map(execution_hash)
    joined["strategy_sha256"] = baseline["strategy"]["sha256"]
    joined["feature_artifact_sha256"] = EXPECTED[FEATURES]
    if joined.source_execution_ledger_sha256.isna().any():
        raise MechanismError("source execution-ledger lineage is incomplete")
    return spec, joined, actual


ENDPOINTS = {
    "mfe": {"sample": "all", "direction": 1},
    "opportunity20": {"sample": "all", "direction": 1},
    "opportunity50": {"sample": "all", "direction": 1},
    "round_trip_return": {"sample": "all", "direction": 1},
    "mae": {"sample": "all", "direction": 1},
    "false_breakout": {"sample": "all", "direction": -1},
    "severe_loss": {"sample": "all", "direction": -1},
    "extreme_loss": {"sample": "all", "direction": -1},
    "return_5d": {"sample": "all", "direction": 1},
    "return_10d": {"sample": "all", "direction": 1},
    "return_20d": {"sample": "all", "direction": 1},
    "conversion20_within_opportunity": {"sample": "opportunity20", "direction": 1},
    "capture_ratio_opportunity20": {"sample": "opportunity20", "direction": 1},
    "giveback_from_peak": {"sample": "opportunity20", "direction": -1},
    "conversion50_within_opportunity": {"sample": "opportunity50", "direction": 1},
}


def endpoint_attribution(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for endpoint, definition in ENDPOINTS.items():
        sample = frame
        if definition["sample"] == "opportunity20":
            sample = frame[frame.opportunity20]
        elif definition["sample"] == "opportunity50":
            sample = frame[frame.opportunity50]
        estimate = safe_spearman(sample.breadth_composite, sample[endpoint])
        loyo: dict[str, float | None] = {}
        for year in range(2018, 2026):
            subset = sample[sample.entry_year != year]
            loyo[str(year)] = safe_spearman(
                subset.breadth_composite, subset[endpoint]
            )["rho"]
        result[endpoint] = {
            **estimate,
            "expected_direction": definition["direction"],
            "sample": definition["sample"],
            "loyo": loyo,
            "loyo_same_sign_count": same_sign_count(estimate["rho"], loyo),
        }
    return result


def summarize_group(rows: pd.DataFrame) -> dict[str, Any]:
    def mean(column: str) -> float | None:
        values = rows[column].dropna().astype(float)
        return float(values.mean()) if len(values) else None

    def median(column: str) -> float | None:
        values = rows[column].dropna().astype(float)
        return float(values.median()) if len(values) else None

    return {
        "count": int(len(rows)),
        "breadth_composite_median": median("breadth_composite"),
        "mfe_mean": mean("mfe"),
        "mfe_median": median("mfe"),
        "mae_mean": mean("mae"),
        "round_trip_return_mean": mean("round_trip_return"),
        "round_trip_return_median": median("round_trip_return"),
        "opportunity20_rate": mean("opportunity20"),
        "opportunity50_rate": mean("opportunity50"),
        "converted20_rate": mean("converted20"),
        "converted50_rate": mean("converted50"),
        "severe_loss_rate": mean("severe_loss"),
        "extreme_loss_rate": mean("extreme_loss"),
        "false_breakout_rate": mean("false_breakout"),
        "return_5d_mean": mean("return_5d"),
        "return_5d_observed": int(rows.return_5d.notna().sum()),
        "return_10d_mean": mean("return_10d"),
        "return_10d_observed": int(rows.return_10d.notna().sum()),
        "return_20d_mean": mean("return_20d"),
        "return_20d_observed": int(rows.return_20d.notna().sum()),
    }


def opportunity_conversion_summary(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for threshold in (20, 50):
        opportunity = frame[frame[f"opportunity{threshold}"]]
        result[str(threshold)] = {
            "opportunity_count": int(len(opportunity)),
            "converted_count": int(opportunity[f"converted{threshold}"].sum()),
            "conversion_rate": float(opportunity[f"converted{threshold}"].mean())
            if len(opportunity)
            else None,
            "by_breadth_tercile": {
                str(tercile): {
                    "opportunity_count": int(len(rows)),
                    "converted_count": int(rows[f"converted{threshold}"].sum()),
                    "conversion_rate": float(rows[f"converted{threshold}"].mean()),
                    "median_giveback": float(rows.giveback_from_peak.median()),
                    "median_capture_ratio": (
                        float(rows.capture_ratio_opportunity20.median())
                        if threshold == 20 and rows.capture_ratio_opportunity20.notna().any()
                        else None
                    ),
                }
                for tercile, rows in opportunity.groupby("breadth_tercile", sort=True)
            },
        }
    return result


def exit_lineage_summary(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for reason, rows in frame.groupby("canonical_exit_reason", sort=True):
        opportunity = rows[rows.opportunity20]
        result[str(reason)] = {
            "count": int(len(rows)),
            "opportunity20_count": int(len(opportunity)),
            "opportunity20_rate": float(rows.opportunity20.mean()),
            "converted20_count": int(rows.converted20.sum()),
            "converted20_within_opportunity_rate": (
                float(opportunity.converted20.mean()) if len(opportunity) else None
            ),
            "median_mfe": float(rows.mfe.median()),
            "median_return": float(rows.round_trip_return.median()),
            "median_giveback": float(rows.giveback_from_peak.median()),
            "median_capture_ratio_opportunity20": (
                float(opportunity.capture_ratio_opportunity20.median())
                if len(opportunity)
                else None
            ),
            "by_breadth_tercile": {
                str(tercile): {
                    "count": int(len(group)),
                    "median_mfe": float(group.mfe.median()),
                    "median_return": float(group.round_trip_return.median()),
                    "median_giveback": float(group.giveback_from_peak.median()),
                }
                for tercile, group in rows.groupby("breadth_tercile", sort=True)
            },
        }
    return result


def cohort_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for cohort_type, column in (("ENTRY_YEAR", "entry_year"), ("ENTRY_QUARTER", "entry_quarter")):
        for cohort, rows in frame.groupby(column, sort=True):
            summary = summarize_group(rows)
            output.append(
                {
                    "cohort_type": cohort_type,
                    "cohort": str(cohort),
                    "baseline_blocks": "|".join(sorted(rows.baseline_block.unique())),
                    **summary,
                }
            )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise MechanismError(f"empty CSV output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(clean_json(rows))
    temporary.replace(path)


def trade_output_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        "baseline_block",
        "source_execution_ledger_sha256",
        "strategy_sha256",
        "feature_artifact_sha256",
        "trade_id",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "exit_signal_date",
        "exit_execution_date",
        "entry_year",
        "entry_quarter",
        "canonical_exit_reason",
        *COMPONENTS,
        *[f"{component}_within_year_rank" for component in COMPONENTS],
        "breadth_composite",
        "breadth_tercile",
        "holding_trading_days",
        "mfe",
        "mae",
        "days_to_mfe",
        "days_to_mae",
        "return_5d",
        "return_10d",
        "return_20d",
        "round_trip_return",
        "realized_pnl",
        "giveback_from_peak",
        "opportunity20",
        "opportunity50",
        "converted20",
        "converted50",
        "conversion20_within_opportunity",
        "conversion50_within_opportunity",
        "capture_ratio_opportunity20",
        "false_breakout",
        "severe_loss",
        "extreme_loss",
    ]
    output = frame[columns].copy()
    for column in (
        "entry_signal_date",
        "entry_execution_date",
        "exit_signal_date",
        "exit_execution_date",
    ):
        output[column] = pd.to_datetime(output[column]).dt.strftime("%Y-%m-%d")
    return output.to_dict("records")


def mechanism_verdict(endpoints: dict[str, Any]) -> dict[str, Any]:
    opportunity_candidates = [endpoints["mfe"], endpoints["opportunity20"]]
    entry_support = any(
        row["rho"] is not None
        and row["rho"] >= 0.10
        and row["loyo_same_sign_count"] >= 7
        for row in opportunity_candidates
    )
    conversion_candidates = [
        endpoints["conversion20_within_opportunity"],
        endpoints["capture_ratio_opportunity20"],
        endpoints["giveback_from_peak"],
    ]
    conversion_support = any(
        row["rho"] is not None
        and abs(row["rho"]) >= 0.10
        and row["loyo_same_sign_count"] >= 7
        for row in conversion_candidates
    )
    if entry_support and not conversion_support:
        h8 = "SUPPORTED_ENTRY_OPPORTUNITY_PRIMARY_WITH_QUALIFICATION"
    elif entry_support and conversion_support:
        h8 = "AMBIGUOUS_BOTH_OPPORTUNITY_AND_CONVERSION_ASSOCIATED"
    else:
        h8 = "REJECTED_NO_STABLE_ENTRY_OPPORTUNITY_SUPPORT"
    return {
        "entry_opportunity_support": entry_support,
        "conversion_support": conversion_support,
        "h8_verdict": h8,
        "exit_secondary_claim": "DESCRIPTIVE_ONLY_NO_COUNTERFACTUAL_POST_EXIT_PATH",
    }


def render_report(payload: dict[str, Any]) -> str:
    endpoints = payload["endpoint_attribution"]
    terciles = payload["breadth_terciles"]
    conversion = payload["opportunity_conversion"]
    verdict = payload["mechanism_verdict"]
    fmt = lambda value: "NA" if value is None else f"{value:.3f}"
    lines = [
        "# Phase 5 — breadth opportunity, conversion, path, and exit attribution",
        "",
        "EXP-P5-001 uses the 399 frozen completed cycles and entry-close PIT features only. It does not replay V1, use post-exit prices, choose a breadth threshold, or simulate an overlay.",
        "",
        "## Mechanism verdict",
        "",
        f"`{verdict['h8_verdict']}`. Breadth entry-opportunity support is `{verdict['entry_opportunity_support']}`; breadth conversion support within MFE>=20% opportunities is `{verdict['conversion_support']}`. Exit-lineage comparisons remain descriptive because no counterfactual post-exit path is available.",
        "",
        "## Continuous/LOYO attribution",
        "",
        "| Endpoint | Sample | N | Breadth rho | LOYO same sign |",
        "|---|---|---:|---:|---:|",
    ]
    for endpoint in ENDPOINTS:
        result = endpoints[endpoint]
        lines.append(
            f"| {endpoint} | {result['sample']} | {result['n']} | {fmt(result['rho'])} | {result['loyo_same_sign_count']}/8 |"
        )
    lines += [
        "",
        "## Coarse feature-only breadth terciles",
        "",
        "| Breadth | N | MFE mean | Return mean | Opportunity20 | Converted20 | False breakout | Severe loss |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for tercile in ("LOW", "MIDDLE", "HIGH"):
        row = terciles[tercile]
        lines.append(
            f"| {tercile} | {row['count']} | {fmt(row['mfe_mean'])} | {fmt(row['round_trip_return_mean'])} | "
            f"{fmt(row['opportunity20_rate'])} | {fmt(row['converted20_rate'])} | "
            f"{fmt(row['false_breakout_rate'])} | {fmt(row['severe_loss_rate'])} |"
        )
    lines += [
        "",
        "## Opportunity conversion",
        "",
        "| Opportunity | Count | Converted | Conversion rate |",
        "|---|---:|---:|---:|",
    ]
    for threshold in ("20", "50"):
        row = conversion[threshold]
        lines.append(
            f"| MFE>={threshold}% | {row['opportunity_count']} | {row['converted_count']} | {fmt(row['conversion_rate'])} |"
        )
    lines += [
        "",
        "The conversion denominator is fixed by MFE, not selected from breadth. `capture_ratio` is reported only for MFE>=20% cycles and is never clipped. Early 5/10/20-session returns remain missing when the actual frozen holding path ended earlier.",
        "",
        "## Exit lineage",
        "",
        "| Exit reason | N | Opportunity20 | Converted20 within opportunity | Median MFE | Median return | Median giveback |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for reason, row in payload["exit_lineage"].items():
        lines.append(
            f"| {reason} | {row['count']} | {row['opportunity20_count']} | "
            f"{fmt(row['converted20_within_opportunity_rate'])} | {fmt(row['median_mfe'])} | "
            f"{fmt(row['median_return'])} | {fmt(row['median_giveback'])} |"
        )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "Breadth can be called an entry-opportunity descriptor only if its MFE/opportunity association survives the frozen LOYO gate. Conversion and exit results say whether that opportunity is harvested; they do not prove an exit caused the observed return. Calendar cohorts are descriptive diagnostics, never year/quarter parameters.",
        "",
        "## Strategy candidate",
        "",
        "None in Phase 5. This mechanism experiment does not authorize a gate, exposure overlay, or exit adaptation.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    spec, frame, identities = validate_and_join()
    endpoints = endpoint_attribution(frame)
    verdict = mechanism_verdict(endpoints)
    breadth_terciles = {
        str(tercile): summarize_group(rows)
        for tercile, rows in frame.groupby("breadth_tercile", sort=True)
    }
    conversion = opportunity_conversion_summary(frame)
    exits = exit_lineage_summary(frame)
    trade_rows = trade_output_rows(frame)
    cohorts = cohort_rows(frame)
    write_csv(OUTPUT_TRADES, trade_rows)
    write_csv(OUTPUT_COHORTS, cohorts)
    payload = {
        "experiment_id": "EXP-P5-001",
        "result": "PASS",
        "evidence_grade": spec["evidence_grade"],
        "spec_sha256": EXPECTED_SPEC,
        "input_hashes": identities,
        "sample_cycles": int(len(frame)),
        "complete_breadth_composite_cycles": int(frame.breadth_composite.notna().sum()),
        "breadth_components": COMPONENTS,
        "breadth_terciles": breadth_terciles,
        "endpoint_attribution": endpoints,
        "opportunity_conversion": conversion,
        "exit_lineage": exits,
        "entry_year_summary": {
            str(year): summarize_group(rows)
            for year, rows in frame.groupby("entry_year", sort=True)
        },
        "entry_quarter_count": int(frame.entry_quarter.nunique()),
        "mechanism_verdict": verdict,
        "formal_strategy_replays": 0,
        "post_exit_price_rows_read": 0,
        "thresholds_optimized": 0,
        "overlay_simulations": 0,
        "output_hashes": {
            "trade_mechanism_attribution_csv": sha256_file(OUTPUT_TRADES),
            "entry_cohort_attribution_csv": sha256_file(OUTPUT_COHORTS),
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(clean_json(payload), indent=2, sort_keys=True) + "\n")
    atomic_write(REPORT, render_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
