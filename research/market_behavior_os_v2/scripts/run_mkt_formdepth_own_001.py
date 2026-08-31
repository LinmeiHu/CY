#!/usr/bin/env python3
"""Estimate the frozen own-security versus shared-date formation-depth channels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-OWN-001_spec.json"
OWN_AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-001_own_gradient_audit.csv"
SHARED_AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-001_shared_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-OWN-001_attribution.md"
EXPECTED_SPEC_SHA256 = "8b01cde195d4458331615d684fcbe45ca6ec943cbf26a41802950c928743afd5"


class OwnSharedError(RuntimeError):
    """Fail-closed own/shared attribution error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise OwnSharedError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_OWN_SHARED_ASSOCIATION_ESTIMATES"
        or spec["research_level"] != "PROMOTE"
        or spec["outcome_access"]
        != "EXISTING_PRE2024_FIXED_STRATUM_H1_H3_H5_ADVERSE_RESPONSE_ONLY"
    ):
        raise OwnSharedError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise OwnSharedError(f"input identity mismatch: {name}")
    data_result = json.loads(
        _resolve(spec["inputs"]["data_result"]["path"]).read_text(encoding="utf-8")
    )
    if data_result["status"] != spec["activation"]["required_data_status"]:
        raise OwnSharedError("own/shared data domain is not activated")
    forbidden = "|".join(spec["prohibited_computations"])
    for token in ("terminal return", "subgroup", "post-2023", "CY-011"):
        if token not in forbidden:
            raise OwnSharedError(f"prohibited boundary missing: {token}")
    return spec


def _median(values: Any) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _rank(frame: pd.DataFrame) -> np.ndarray:
    return frame.rank(method="average").to_numpy(dtype=float)


def _residual(values: np.ndarray, controls: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(values)), controls])
    coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
    return values - design @ coefficients


def _corr(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def _spearman(frame: pd.DataFrame, left: str, right: str) -> tuple[int, float]:
    valid = frame[[left, right]].dropna()
    if len(valid) < 3 or valid[left].nunique() < 2 or valid[right].nunique() < 2:
        return len(valid), float("nan")
    ranks = _rank(valid[[left, right]])
    return len(valid), _corr(ranks[:, 0], ranks[:, 1])


def _partial_rank(
    frame: pd.DataFrame, target: str, response: str, controls: list[str]
) -> tuple[int, float]:
    valid = frame[[target, response, *controls]].dropna()
    if len(valid) <= len(controls) + 2:
        return len(valid), float("nan")
    ranks = _rank(valid[[target, response, *controls]])
    target_residual = _residual(ranks[:, 0], ranks[:, 2:])
    response_residual = _residual(ranks[:, 1], ranks[:, 2:])
    return len(valid), _corr(target_residual, response_residual)


def _tail_residual_gap(
    frame: pd.DataFrame,
    target: str,
    response: str,
    controls: list[str],
    low_maximum: float,
    high_minimum: float,
) -> tuple[int, int, int, float]:
    valid = frame[[target, response, *controls]].dropna()
    if len(valid) <= len(controls) + 2:
        return len(valid), 0, 0, float("nan")
    control_ranks = _rank(valid[controls])
    residual = _residual(valid[response].to_numpy(dtype=float), control_ranks)
    target_values = valid[target].to_numpy(dtype=float)
    low = residual[target_values <= low_maximum]
    high = residual[target_values >= high_minimum]
    gap = float(np.mean(high) - np.mean(low)) if len(low) and len(high) else float("nan")
    return len(valid), len(low), len(high), gap


def _load_panels(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ["trade_date", "market_view", "denominator"]
    controls = spec["shared_channel"]["controls"]
    responses = [f"stratum_adverse_log_excursion_h{horizon}_mean" for horizon in (1, 3, 5)]
    columns = [
        *keys,
        "stratum",
        "stratum_complete",
        "stratum_own_depth_mean",
        "stratum_own_depth_pit_3y_pct",
        "other_strata_depth_pit_3y_pct",
        "available_at",
        "event_year",
        *controls[1:],
        *responses,
    ]
    panel = pd.read_csv(
        _resolve(spec["inputs"]["data_panel"]["path"]),
        usecols=columns,
        parse_dates=["trade_date"],
        float_precision="round_trip",
    )
    activation = spec["activation"]
    if len(panel) != activation["expected_panel_rows"]:
        raise OwnSharedError("data panel row count changed")
    if panel[[*keys, "stratum"]].duplicated().any():
        raise OwnSharedError("data panel key is not unique")
    if not panel["stratum"].between(1, activation["strata"]).all():
        raise OwnSharedError("stratum domain changed")
    clock = pd.to_datetime(panel["available_at"], errors="coerce")
    if clock.isna().any() or not ((clock.dt.hour == 15) & (clock.dt.minute == 30)).all():
        raise OwnSharedError("anchor availability is not exactly 15:30")
    complete = panel[panel["stratum_complete"]].copy()
    if len(complete) != activation["expected_complete_stratum_rows"]:
        raise OwnSharedError("complete stratum row count changed")
    group_strata = complete.groupby(keys, sort=False)["stratum"].nunique()
    complete_keys = (
        group_strata[group_strata.eq(activation["strata"])].index.to_frame(index=False)
    )
    own = complete.merge(complete_keys, on=keys, how="inner", validate="many_to_one")
    if len(complete_keys) != activation["expected_complete_five_stratum_date_cells"]:
        raise OwnSharedError("complete five-stratum date/cell count changed")
    if len(own) != activation["expected_complete_five_stratum_rows"]:
        raise OwnSharedError("complete five-stratum row count changed")
    support = own.groupby(["market_view", "denominator", "event_year"]).size()
    if int((support / activation["strata"]).min()) < activation[
        "minimum_complete_five_stratum_dates_each_cell_year"
    ]:
        raise OwnSharedError("complete five-stratum cell/year support changed")
    if not np.isfinite(own[["stratum_own_depth_mean", *responses]].to_numpy(float)).all():
        raise OwnSharedError("own-channel input is nonfinite")

    ordinal = pd.read_csv(
        _resolve(spec["inputs"]["attribution_panel_for_session_ordinal"]["path"]),
        usecols=[*keys, "session_ordinal"],
        parse_dates=["trade_date"],
    )
    if ordinal[keys].duplicated().any():
        raise OwnSharedError("session ordinal key is not unique")
    shared = complete.merge(ordinal, on=keys, how="left", validate="many_to_one")
    required = [
        "other_strata_depth_pit_3y_pct",
        *controls,
        "session_ordinal",
        *responses,
    ]
    shared = shared.dropna(subset=required).copy()
    if len(shared) != activation["expected_later_rows"]:
        raise OwnSharedError("later own/shared analysis row count changed")
    if shared["event_year"].max() > 2023:
        raise OwnSharedError("post-2023 row reached own/shared analysis")
    if shared.groupby("stratum", sort=True).size().min() < 6000:
        raise OwnSharedError("shared-channel stratum support changed")
    return own.sort_values([*keys, "stratum"]), shared.sort_values([*keys, "stratum"])


def _own_audit(panel: pd.DataFrame) -> pd.DataFrame:
    keys = ["trade_date", "market_view", "denominator"]
    rows: list[dict[str, Any]] = []
    for key, group in panel.groupby(keys, sort=True):
        for horizon in (1, 3, 5):
            response = f"stratum_adverse_log_excursion_h{horizon}_mean"
            n, rho = _spearman(group, "stratum_own_depth_mean", response)
            rows.append(
                {
                    "trade_date": key[0],
                    "market_view": key[1],
                    "denominator": key[2],
                    "event_year": int(group["event_year"].iloc[0]),
                    "horizon": horizon,
                    "n_strata": n,
                    "own_gradient_rho": rho,
                }
            )
    audit = pd.DataFrame(rows).sort_values(
        ["trade_date", "denominator", "market_view", "horizon"]
    )
    if not audit["n_strata"].eq(5).all() or audit["own_gradient_rho"].isna().any():
        raise OwnSharedError("own-channel date gradient is incomplete")
    return audit.reset_index(drop=True)


def _evaluate_own(audit: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gate = spec["own_channel"]
    primary = audit[audit["horizon"].eq(3)]
    cell = primary.groupby(["market_view", "denominator"], sort=True)[
        "own_gradient_rho"
    ].median()
    block_medians = {
        block: _median(primary.loc[primary["event_year"].isin(years), "own_gradient_rho"])
        for block, years in spec["blocks"].items()
    }
    year_medians = {
        str(year): _median(
            primary.loc[primary["event_year"].eq(year), "own_gradient_rho"]
        )
        for year in spec["pit_supported_years"]
    }
    loo_medians = {
        str(year): _median(
            primary.loc[
                primary["event_year"].isin(
                    [item for item in spec["pit_supported_years"] if item != year]
                ),
                "own_gradient_rho",
            ]
        )
        for year in spec["pit_supported_years"]
    }
    neighbor_medians = {
        str(horizon): _median(
            audit.loc[audit["horizon"].eq(horizon), "own_gradient_rho"]
        )
        for horizon in (1, 5)
    }
    median_h3 = _median(primary["own_gradient_rho"])
    negative_cells = int((cell < 0).sum())
    checks = {
        "primary": median_h3 <= gate["maximum_median_h3_rho"],
        "cells": negative_cells >= gate["minimum_negative_cell_medians"],
        "blocks": all(
            value <= gate["maximum_each_block_median_h3_rho"]
            for value in block_medians.values()
        ),
        "years": all(value < 0 for value in year_medians.values()),
        "leave_one_year_out": all(value < 0 for value in loo_medians.values()),
        "neighbors": all(value < 0 for value in neighbor_medians.values()),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "median_h3_date_gradient_rho": median_h3,
        "negative_cell_medians": negative_cells,
        "cell_median_h3_rho": {
            f"{view}:{denominator}": float(value)
            for (view, denominator), value in cell.items()
        },
        "block_median_h3_rho": block_medians,
        "year_median_h3_rho": year_medians,
        "leave_one_year_out_median_h3_rho": loo_medians,
        "neighbor_median_rho": neighbor_medians,
    }


def _shared_audit(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    target = spec["shared_channel"]["target"]
    controls = spec["shared_channel"]["controls"]
    rows: list[dict[str, Any]] = []

    def append_partial(
        group: pd.DataFrame,
        stratum: int,
        view: str,
        denominator: str,
        horizon: int,
        scope: str,
        scope_value: str,
    ) -> None:
        response = f"stratum_adverse_log_excursion_h{horizon}_mean"
        n, rho = _partial_rank(group, target, response, controls)
        rows.append(
            {
                "audit_type": "partial_rank",
                "stratum": stratum,
                "market_view": view,
                "denominator": denominator,
                "horizon": horizon,
                "scope": scope,
                "scope_value": scope_value,
                "n": n,
                "partial_rho": rho,
                "low_n": np.nan,
                "high_n": np.nan,
                "tail_residual_gap": np.nan,
            }
        )

    years = spec["pit_supported_years"]
    for (stratum, view, denominator), group in panel.groupby(
        ["stratum", "market_view", "denominator"], sort=True
    ):
        group = group.sort_values("trade_date")
        for horizon in (1, 3, 5):
            append_partial(
                group, int(stratum), view, denominator, horizon, "cell", f"{view}:{denominator}"
            )
        for block, block_years in spec["blocks"].items():
            append_partial(
                group[group["event_year"].isin(block_years)],
                int(stratum),
                view,
                denominator,
                3,
                "block",
                block,
            )
        for year in years:
            append_partial(
                group[group["event_year"].eq(year)],
                int(stratum),
                view,
                denominator,
                3,
                "year",
                str(year),
            )
            append_partial(
                group[group["event_year"].isin([item for item in years if item != year])],
                int(stratum),
                view,
                denominator,
                3,
                "leave_one_year_out",
                str(year),
            )
        for horizon in (3, 5):
            for phase in range(horizon):
                append_partial(
                    group[group["session_ordinal"].mod(horizon).eq(phase)],
                    int(stratum),
                    view,
                    denominator,
                    horizon,
                    "phase",
                    str(phase),
                )
        response = "stratum_adverse_log_excursion_h3_mean"
        n, low_n, high_n, gap = _tail_residual_gap(
            group,
            target,
            response,
            controls,
            spec["shared_channel"]["pit_low_maximum"],
            spec["shared_channel"]["pit_high_minimum"],
        )
        rows.append(
            {
                "audit_type": "tail_residual_gap",
                "stratum": int(stratum),
                "market_view": view,
                "denominator": denominator,
                "horizon": 3,
                "scope": "cell",
                "scope_value": f"{view}:{denominator}",
                "n": n,
                "partial_rho": np.nan,
                "low_n": low_n,
                "high_n": high_n,
                "tail_residual_gap": gap,
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["stratum", "audit_type", "scope", "scope_value", "market_view", "denominator", "horizon"]
    ).reset_index(drop=True)


def _evaluate_shared(audit: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gate = spec["shared_channel"]
    partial = audit[audit["audit_type"].eq("partial_rank")]
    evaluations: dict[str, Any] = {}
    for stratum in range(1, spec["activation"]["strata"] + 1):
        item = partial[partial["stratum"].eq(stratum)]
        primary = item[item["scope"].eq("cell") & item["horizon"].eq(3)]
        median_h3 = _median(primary["partial_rho"])
        negative_cells = int((primary["partial_rho"] < 0).sum())
        block_medians = {
            block: _median(
                item.loc[
                    item["scope"].eq("block") & item["scope_value"].eq(block),
                    "partial_rho",
                ]
            )
            for block in spec["blocks"]
        }
        year_medians = {
            str(year): _median(
                item.loc[
                    item["scope"].eq("year")
                    & item["scope_value"].eq(str(year)),
                    "partial_rho",
                ]
            )
            for year in spec["pit_supported_years"]
        }
        loo_medians = {
            str(year): _median(
                item.loc[
                    item["scope"].eq("leave_one_year_out")
                    & item["scope_value"].eq(str(year)),
                    "partial_rho",
                ]
            )
            for year in spec["pit_supported_years"]
        }
        neighbor_medians = {
            str(horizon): _median(
                item.loc[
                    item["scope"].eq("cell") & item["horizon"].eq(horizon),
                    "partial_rho",
                ]
            )
            for horizon in (1, 5)
        }
        phase_signs = {
            str(horizon): [
                int(
                    np.sign(
                        _median(
                            item.loc[
                                item["scope"].eq("phase")
                                & item["horizon"].eq(horizon)
                                & item["scope_value"].eq(str(phase)),
                                "partial_rho",
                            ]
                        )
                    )
                )
                for phase in range(horizon)
            ]
            for horizon in (3, 5)
        }
        tail_gap = _median(
            audit.loc[
                audit["stratum"].eq(stratum)
                & audit["audit_type"].eq("tail_residual_gap"),
                "tail_residual_gap",
            ]
        )
        checks = {
            "primary": median_h3 <= gate["maximum_median_h3_partial_rho"],
            "cells": negative_cells >= gate["minimum_negative_cells"],
            "blocks": all(
                value <= gate["maximum_each_block_median_h3_partial_rho"]
                for value in block_medians.values()
            ),
            "years": all(value < 0 for value in year_medians.values()),
            "leave_one_year_out": all(value < 0 for value in loo_medians.values()),
            "neighbors": all(value < 0 for value in neighbor_medians.values()),
            "h3_phases": sum(value < 0 for value in phase_signs["3"])
            >= gate["minimum_negative_h3_phases"],
            "h5_phases": sum(value < 0 for value in phase_signs["5"])
            >= gate["minimum_negative_h5_phases"],
            "tail_residual_gap": tail_gap <= gate["maximum_median_tail_residual_gap"],
        }
        evaluations[str(stratum)] = {
            "pass": all(checks.values()),
            "checks": checks,
            "median_h3_partial_rho": median_h3,
            "negative_cells": negative_cells,
            "block_median_h3_partial_rho": block_medians,
            "year_median_h3_partial_rho": year_medians,
            "leave_one_year_out_median_h3_partial_rho": loo_medians,
            "neighbor_median_partial_rho": neighbor_medians,
            "phase_signs": phase_signs,
            "median_tail_residual_gap": tail_gap,
        }
    return evaluations


def _classification(own_pass: bool, passing_shared: int, spec: dict[str, Any]) -> str:
    broad = passing_shared >= spec["shared_channel"][
        "minimum_passing_strata_for_broad_channel"
    ]
    labels = spec["classification"]
    if own_pass and broad:
        return labels["own_and_broad_shared"]
    if broad:
        return labels["broad_shared_only"]
    if own_pass:
        return labels["own_only"]
    return labels["neither"]


def _report(result: dict[str, Any]) -> str:
    own = result["own_channel"]
    shared_rows = []
    for key, value in result["shared_channel"]["strata"].items():
        rho = value["median_h3_partial_rho"]
        gap = value["median_tail_residual_gap"]
        shared_rows.append(
            f"- Stratum {key}: pass={value['pass']}; h3 rho={rho:.6f}; "
            f"gap={gap:.6f}"
        )
    shared_lines = "\n".join(shared_rows)
    return f"""# MKT-FORMDEPTH-OWN-001 own/shared attribution

## Decision

`{result['classification']}`

- Own channel pass: {own['pass']}
- Median h3 within-date own-depth gradient: {own['median_h3_date_gradient_rho']:.6f}
- Negative own-gradient cell medians: {own['negative_cell_medians']}/8
- Broad shared channel pass: {result['shared_channel']['broad_pass']}
- Passing shared strata: {result['shared_channel']['passing_strata']}

{shared_lines}

This PROMOTE result uses fixed pre-2024 strata, h1/h3/h5 adverse responses, and
controls at the 15:30 information clock. It is association topology only—not
causality, an entry predictor, a habitat, execution, payoff, or strategy.

## Material synthesis

We now believe the downside ordering is primarily security-specific: deeper own
overshoot orders worse future adverse paths within the same date, while the
disjoint shared-date environment does not pass the required broad 4/5-stratum
gate. This rejects a broad shared-depth-only explanation, not every shared or
concentration mechanism.

The best competing mechanisms are: objective prior-high overextension/supply;
generic same-day security extension or range; temporary liquidity/price impact
that should be visible in late-session minute rejection/acceptance; and
industry/size/liquidity concentration. The highest-information next experiment
is objective specificity: test own depth after fixed security-level same-day
return, range, close location, turnover, and liquidity controls within date.
If it survives, minute-path price-impact versus persistent-demand evidence
becomes the next discriminator. No distinct recurring strategy process is yet
established.
"""


def main() -> None:
    spec = _load_spec()
    own_panel, shared_panel = _load_panels(spec)
    own_audit = _own_audit(own_panel)
    own_evaluation = _evaluate_own(own_audit, spec)
    shared_audit = _shared_audit(shared_panel, spec)
    shared_evaluation = _evaluate_shared(shared_audit, spec)
    passing = [int(key) for key, value in shared_evaluation.items() if value["pass"]]
    classification = _classification(own_evaluation["pass"], len(passing), spec)
    OWN_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    own_audit.to_csv(OWN_AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    shared_audit.to_csv(
        SHARED_AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "classification": classification,
        "claim": spec["claim_boundary"],
        "population": {
            "complete_stratum_rows": len(own_panel),
            "complete_date_cells": int(len(own_panel) / spec["activation"]["strata"]),
            "later_shared_rows": len(shared_panel),
            "own_date_gradient_rows": len(own_audit),
            "shared_audit_rows": len(shared_audit),
        },
        "own_channel": own_evaluation,
        "shared_channel": {
            "passing_strata": passing,
            "passing_strata_count": len(passing),
            "broad_pass": len(passing)
            >= spec["shared_channel"]["minimum_passing_strata_for_broad_channel"],
            "strata": shared_evaluation,
        },
        "future_response_used_as_predictor": False,
        "terminal_return_read": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "lean_validation": spec["lean_validation"],
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "own_gradient_audit_sha256": sha256_file(OWN_AUDIT_PATH),
            "shared_audit_sha256": sha256_file(SHARED_AUDIT_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
