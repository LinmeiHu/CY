#!/usr/bin/env python3
"""Execute the frozen repeated-event objective-breakout dynamics experiment."""

from __future__ import annotations

import hashlib
import json
import time
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-001_trajectory_panel.csv"
STABILITY_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-001_stability_audit.csv"
COUPLING_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-001_coupling_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "09f29ecff92864cae4242bdad64632314298d690f5b09644f606d6b605df69eb"
RUNNER_DEPENDENCIES: dict[str, str] = {}


class BreakoutDynamicsError(RuntimeError):
    """Fail-closed MKT-BREAKOUT-DYN-001 error."""


def _sha256_file(path: Path) -> str:
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
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise BreakoutDynamicsError("temporal spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_ROLE_SPECIFIC_TRAJECTORY_COUNTS_OR_ESTIMATES":
        raise BreakoutDynamicsError("temporal activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or _sha256_file(path) != binding["sha256"]:
            raise BreakoutDynamicsError(f"bound input identity mismatch: {name}")
    parent = json.loads(_resolve(spec["inputs"]["parent_result"]["path"]).read_text())
    expected_roles = list(spec["roles"])
    if (
        parent["status"] != "COMPLETE_REPRESENTATION_PASS"
        or parent["representation_summary"]["minimal_roles"] != expected_roles
        or parent["future_fields_read"]
        or parent["strategy_or_outcome_fields_read"]
        or parent["post_2023_data_read"]
        or parent["cy011_read"]
    ):
        raise BreakoutDynamicsError("parent evidence activation changed")
    return spec, parent


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if time.monotonic() - started > budget["wall_seconds"]:
        raise BreakoutDynamicsError("wall-clock ceiling breached")
    rss = psutil.Process().memory_info().rss
    if rss > budget["peak_rss_bytes"]:
        raise BreakoutDynamicsError("RSS ceiling breached")


def _as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    mapped = series.astype(str).str.lower().map({"true": True, "false": False})
    if mapped.isna().any():
        raise BreakoutDynamicsError("domain flag is not exact boolean")
    return mapped.astype(bool)


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _spearman(left: pd.Series, right: pd.Series) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return np.nan
    return float(frame["left"].rank(method="average").corr(frame["right"].rank(method="average")))


def _sign_agreement(left: pd.Series, right: pd.Series) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if frame.empty:
        return np.nan
    return float(np.mean(np.sign(frame["left"]) == np.sign(frame["right"])))


def _operators(ranks: np.ndarray, values: np.ndarray) -> dict[str, float]:
    x = np.asarray(ranks, dtype=float)
    y = np.asarray(values, dtype=float)
    if (
        len(x) < 2
        or len(x) != len(y)
        or not np.isfinite(x).all()
        or not np.isfinite(y).all()
        or not np.all(np.diff(x) > 0)
    ):
        return {"endpoint_rate": np.nan, "ols_slope": np.nan, "theil_sen_slope": np.nan}
    endpoint = float((y[-1] - y[0]) / (x[-1] - x[0]))
    if len(x) < 3:
        return {"endpoint_rate": endpoint, "ols_slope": np.nan, "theil_sen_slope": np.nan}
    centered = x - x.mean()
    denominator = float(np.dot(centered, centered))
    ols = float(np.dot(centered, y - y.mean()) / denominator)
    slopes = [
        float((y[j] - y[i]) / (x[j] - x[i]))
        for i in range(len(x) - 1)
        for j in range(i + 1, len(x))
    ]
    return {
        "endpoint_rate": endpoint,
        "ols_slope": ols,
        "theil_sen_slope": float(np.median(slopes)),
    }


def _rank_adjusted_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    complete = frame[[target, *controls]].dropna()
    n = len(complete)
    p = len(controls)
    if n <= p + 1 or complete[target].nunique() < 2:
        return np.nan
    ranked = complete.rank(method="average")
    y = ranked[target].to_numpy(dtype=float)
    x = np.column_stack([np.ones(n), *(ranked[field].to_numpy(dtype=float) for field in controls)])
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    sst = float(np.square(y - y.mean()).sum())
    if sst == 0:
        return np.nan
    r2 = 1.0 - float(np.square(y - fitted).sum()) / sst
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _rank_residuals(frame: pd.DataFrame, target: str, controls: list[str]) -> pd.Series:
    complete = frame[["sequence_id", target, *controls]].dropna().copy()
    if len(complete) <= len(controls) + 1:
        return pd.Series(dtype=float)
    ranked = complete[[target, *controls]].rank(method="average")
    y = ranked[target].to_numpy(dtype=float)
    x = np.column_stack(
        [
            np.ones(len(complete)),
            *(ranked[field].to_numpy(dtype=float) for field in controls),
        ]
    )
    residual = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
    return pd.Series(residual, index=complete["sequence_id"].astype(str), dtype=float)


def _load_parent_panel(spec: dict[str, Any], parent: dict[str, Any]) -> pd.DataFrame:
    roles = spec["roles"]
    usecols = {
        "audit_id",
        "sequence_id",
        "market_view",
        "symbol",
        "trade_date",
        "target_year",
        "block_id",
        "market_sequence_rank",
        "relative_day",
        "definition",
        "temporal_block",
        *(item for role in roles for item in [role, roles[role]["domain_flag"]]),
        *(control for role in roles.values() for control in role["controls"]),
    }
    source = _resolve(spec["inputs"]["session_panel"]["path"])
    header = set(pd.read_csv(source, nrows=0).columns)
    missing = sorted(usecols - header)
    if missing:
        raise BreakoutDynamicsError(f"required parent columns missing: {missing}")
    frame = pd.read_csv(
        source,
        usecols=sorted(usecols),
        dtype={"symbol": str},
        float_precision="round_trip",
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    for flag in {role["domain_flag"] for role in roles.values()}:
        frame[flag] = _as_bool(frame[flag])
    population = parent["population"]
    if (
        len(frame) != population["panel_rows"]
        or frame.loc[frame["definition"].eq("L20_CONTINUOUS"), "audit_id"].nunique()
        != population["primary_crossings"]
        or frame["target_year"].min() < 2018
        or frame["target_year"].max() > 2023
        or frame.duplicated(["sequence_id", "definition", "trade_date"]).any()
    ):
        raise BreakoutDynamicsError("parent panel population changed")
    expected_definitions = {
        spec["population"]["primary_definition"],
        *spec["population"]["level_challenges"],
        spec["population"]["clock_challenge"],
    }
    if set(frame["definition"]) != expected_definitions:
        raise BreakoutDynamicsError("definition set changed")
    return frame.sort_values(["sequence_id", "definition", "trade_date"]).reset_index(drop=True)


def _build_trajectories(spec: dict[str, Any], source: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for role, role_spec in spec["roles"].items():
        flag = role_spec["domain_flag"]
        for definition, defined in source.groupby("definition", sort=True):
            eligible = defined.loc[
                defined[flag] & pd.to_numeric(defined[role], errors="coerce").notna()
            ]
            for sequence_id, rows in eligible.groupby("sequence_id", sort=True):
                rows = rows.sort_values("market_sequence_rank")
                if len(rows) < 2:
                    continue
                ranks = rows["market_sequence_rank"].to_numpy(dtype=float)
                if len(np.unique(ranks)) != len(ranks):
                    raise BreakoutDynamicsError(f"duplicate event rank: {sequence_id}:{definition}")
                target = _operators(ranks, rows[role].to_numpy(dtype=float))
                first = rows.iloc[0]
                last = rows.iloc[-1]
                record: dict[str, Any] = {
                    "trajectory_id": hashlib.sha256(
                        f"MKT-BREAKOUT-DYN-001|{sequence_id}|{role}|{definition}".encode()
                    ).hexdigest(),
                    "sequence_id": str(sequence_id),
                    "target_year": int(first["target_year"]),
                    "temporal_block": str(first["temporal_block"]),
                    "market_view": str(first["market_view"]),
                    "symbol": str(first["symbol"]),
                    "role": role,
                    "definition": str(definition),
                    "event_days": len(rows),
                    "rank_span": int(ranks[-1] - ranks[0]),
                    "first_rank": int(ranks[0]),
                    "last_rank": int(ranks[-1]),
                    "first_trade_date": first["trade_date"].date().isoformat(),
                    "last_trade_date": last["trade_date"].date().isoformat(),
                    "available_at": f"{last['trade_date'].date().isoformat()}T15:30:00+08:00",
                    "first_value": float(first[role]),
                    "last_value": float(last[role]),
                    **target,
                }
                for control in role_spec["controls"]:
                    values = pd.to_numeric(rows[control], errors="coerce").to_numpy(dtype=float)
                    record[f"control__{control}__endpoint_rate"] = (
                        _operators(ranks, values)["endpoint_rate"]
                        if np.isfinite(values).all()
                        else np.nan
                    )
                records.append(record)
    trajectory = pd.DataFrame(records)
    if trajectory.empty:
        raise BreakoutDynamicsError("no repeated-event trajectories")
    return trajectory.sort_values(["role", "definition", "sequence_id"]).reset_index(drop=True)


def _scope(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    return frame if scope == "GLOBAL" else frame.loc[frame["temporal_block"].eq(scope)]


def _audit_row(
    rows: list[dict[str, Any]],
    role: str,
    challenge: str,
    scope: str,
    n: int,
    value: float,
    threshold: str,
    passed: bool,
) -> None:
    rows.append(
        {
            "role": role,
            "challenge": challenge,
            "scope": scope,
            "n": int(n),
            "value": float(value),
            "threshold": threshold,
            "pass": bool(passed),
        }
    )


def _count_support(
    spec: dict[str, Any],
    frame: pd.DataFrame,
    role: str,
    kind: str,
    audit: list[dict[str, Any]],
) -> bool:
    gate = spec["support_gates"][kind]
    checks: list[bool] = []
    checks.append(len(frame) >= gate["total"])
    _audit_row(
        audit,
        role,
        f"{kind}_count",
        "GLOBAL",
        len(frame),
        len(frame),
        f">={gate['total']}",
        checks[-1],
    )
    for block in ["A", "B"]:
        count = int(frame["temporal_block"].eq(block).sum())
        checks.append(count >= gate["each_block"])
        _audit_row(
            audit, role, f"{kind}_count", block, count, count, f">={gate['each_block']}", checks[-1]
        )
    for year in spec["population"]["years"]:
        count = int(frame["target_year"].eq(year).sum())
        checks.append(count >= gate["each_year"])
        _audit_row(
            audit,
            role,
            f"{kind}_count",
            str(year),
            count,
            count,
            f">={gate['each_year']}",
            checks[-1],
        )
    if "each_view" in gate:
        for view in spec["population"]["views"]:
            count = int(frame["market_view"].eq(view).sum())
            checks.append(count >= gate["each_view"])
            _audit_row(
                audit,
                role,
                f"{kind}_count",
                view,
                count,
                count,
                f">={gate['each_view']}",
                checks[-1],
            )
    return all(checks)


def _pair_stats(left: pd.Series, right: pd.Series) -> dict[str, float | int]:
    joint = pd.DataFrame({"left": left, "right": right}).dropna()
    return {
        "n": len(joint),
        "spearman": _spearman(joint["left"], joint["right"]),
        "sign_agreement": _sign_agreement(joint["left"], joint["right"]),
    }


def _merged_definition(primary: pd.DataFrame, neighbor: pd.DataFrame) -> pd.DataFrame:
    return primary[["sequence_id", "temporal_block", "endpoint_rate"]].merge(
        neighbor[["sequence_id", "endpoint_rate"]],
        on="sequence_id",
        how="inner",
        suffixes=("_primary", "_neighbor"),
        validate="one_to_one",
    )


def _bootstrap_interval(
    values: np.ndarray, role: str, block: str, draws: int
) -> tuple[float, float]:
    payload = f"MKT-BREAKOUT-DYN-001|{role}|{block}".encode()
    seed = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 2**32
    rng = np.random.default_rng(seed)
    medians = np.median(rng.choice(values, size=(draws, len(values)), replace=True), axis=1)
    low, high = np.quantile(medians, [0.025, 0.975])
    return float(low), float(high)


def _evaluate_role(
    spec: dict[str, Any], trajectory: pd.DataFrame, role: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    role_spec = spec["roles"][role]
    audit: list[dict[str, Any]] = []
    primary = trajectory.loc[
        trajectory["role"].eq(role)
        & trajectory["definition"].eq(spec["population"]["primary_definition"])
    ].copy()
    reacquisition = role == "reacquisition_bars"
    endpoint_kind = "reacquisition_endpoint" if reacquisition else "main_endpoint"
    shape_kind = "reacquisition_shape" if reacquisition else "main_shape"
    endpoint_support = _count_support(spec, primary, role, endpoint_kind, audit)
    shape = primary.loc[primary["event_days"].ge(3)].copy()
    shape_support = _count_support(spec, shape, role, shape_kind, audit)

    nondeg = spec["representation_gates"]["endpoint_nondegeneracy"]
    nondeg_checks: list[bool] = []
    for scope in ["GLOBAL", "A", "B"]:
        scoped = _scope(primary, scope)
        minimum = (
            nondeg["minimum_unique_global"]
            if scope == "GLOBAL"
            else nondeg["minimum_unique_each_block"]
        )
        unique = int(scoped["endpoint_rate"].nunique())
        passed = unique >= minimum
        nondeg_checks.append(passed)
        _audit_row(
            audit,
            role,
            "endpoint_nondegeneracy",
            scope,
            len(scoped),
            unique,
            f">={minimum}",
            passed,
        )
    for year in spec["population"]["years"]:
        scoped = primary.loc[primary["target_year"].eq(year)]
        unique = int(scoped["endpoint_rate"].nunique())
        passed = unique >= nondeg["minimum_unique_each_year"]
        nondeg_checks.append(passed)
        _audit_row(
            audit,
            role,
            "endpoint_nondegeneracy",
            str(year),
            len(scoped),
            unique,
            f">={nondeg['minimum_unique_each_year']}",
            passed,
        )

    shape_gate = spec["representation_gates"]["shape_agreement"]
    shape_checks: list[bool] = []
    shape_summary: dict[str, Any] = {}
    for field in ["ols_slope", "theil_sen_slope"]:
        field_summary: dict[str, Any] = {}
        for scope in ["GLOBAL", "A", "B"]:
            scoped = _scope(shape, scope)
            stats = _pair_stats(scoped["endpoint_rate"], scoped[field])
            rho_min = (
                shape_gate["minimum_global_spearman"]
                if scope == "GLOBAL"
                else shape_gate["minimum_each_block_spearman"]
            )
            sign_min = (
                shape_gate["minimum_global_sign_agreement"]
                if scope == "GLOBAL"
                else shape_gate["minimum_each_block_sign_agreement"]
            )
            passed = bool(stats["spearman"] >= rho_min and stats["sign_agreement"] >= sign_min)
            shape_checks.append(passed)
            field_summary[scope] = {**stats, "pass": passed}
            _audit_row(
                audit,
                role,
                f"shape_{field}_spearman",
                scope,
                int(stats["n"]),
                float(stats["spearman"]),
                f">={rho_min}",
                stats["spearman"] >= rho_min,
            )
            _audit_row(
                audit,
                role,
                f"shape_{field}_sign",
                scope,
                int(stats["n"]),
                float(stats["sign_agreement"]),
                f">={sign_min}",
                stats["sign_agreement"] >= sign_min,
            )
        shape_summary[field] = field_summary

    definition_summary: dict[str, Any] = {}
    definition_checks: list[bool] = []
    intersection_kind = (
        "definition_intersection_reacquisition" if reacquisition else "definition_intersection_main"
    )
    intersection_gate = spec["support_gates"][intersection_kind]
    for definition in [
        *spec["population"]["level_challenges"],
        spec["population"]["clock_challenge"],
    ]:
        neighbor = trajectory.loc[
            trajectory["role"].eq(role) & trajectory["definition"].eq(definition)
        ]
        merged = _merged_definition(primary, neighbor)
        clock = definition == spec["population"]["clock_challenge"]
        gate = spec["representation_gates"]["auction_clock" if clock else "level_definition"]
        scopes: dict[str, Any] = {}
        for scope in ["GLOBAL", "A", "B"]:
            scoped = _scope(merged, scope)
            stats = _pair_stats(scoped["endpoint_rate_primary"], scoped["endpoint_rate_neighbor"])
            n_min = (
                intersection_gate["global"]
                if scope == "GLOBAL"
                else intersection_gate["each_block"]
            )
            rho_min = (
                gate["minimum_global_spearman"]
                if scope == "GLOBAL"
                else gate["minimum_each_block_spearman"]
            )
            sign_min = (
                gate["minimum_global_sign_agreement"]
                if scope == "GLOBAL"
                else gate["minimum_each_block_sign_agreement"]
            )
            passed = bool(
                stats["n"] >= n_min
                and stats["spearman"] >= rho_min
                and stats["sign_agreement"] >= sign_min
            )
            definition_checks.append(passed)
            scopes[scope] = {**stats, "pass": passed}
            _audit_row(
                audit,
                role,
                f"definition_{definition}_spearman",
                scope,
                int(stats["n"]),
                float(stats["spearman"]),
                f"n>={n_min};rho>={rho_min}",
                stats["n"] >= n_min and stats["spearman"] >= rho_min,
            )
            _audit_row(
                audit,
                role,
                f"definition_{definition}_sign",
                scope,
                int(stats["n"]),
                float(stats["sign_agreement"]),
                f">={sign_min}",
                stats["sign_agreement"] >= sign_min,
            )
        definition_summary[definition] = scopes

    controls = [f"control__{field}__endpoint_rate" for field in role_spec["controls"]]
    complete = primary.dropna(subset=["endpoint_rate", *controls])
    external_kind = "external_complete_reacquisition" if reacquisition else "external_complete_main"
    external_gate = spec["support_gates"][external_kind]
    external_checks: list[bool] = []
    external_summary: dict[str, Any] = {"pairwise": {}, "joint": {}}
    for scope in ["GLOBAL", "A", "B"]:
        scoped = _scope(complete, scope)
        n_min = external_gate["global"] if scope == "GLOBAL" else external_gate["each_block"]
        support_pass = len(scoped) >= n_min
        external_checks.append(support_pass)
        _audit_row(
            audit,
            role,
            "external_complete_count",
            scope,
            len(scoped),
            len(scoped),
            f">={n_min}",
            support_pass,
        )
        joint = _rank_adjusted_r2(scoped, "endpoint_rate", controls)
        joint_max = (
            spec["representation_gates"]["external_joint_rank_adjusted_r2_global_maximum"]
            if scope == "GLOBAL"
            else spec["representation_gates"]["external_joint_rank_adjusted_r2_each_block_maximum"]
        )
        joint_pass = bool(np.isfinite(joint) and joint < joint_max)
        external_checks.append(joint_pass)
        external_summary["joint"][scope] = {
            "n": len(scoped),
            "adjusted_r2": joint,
            "pass": joint_pass,
        }
        _audit_row(
            audit,
            role,
            "external_joint_adjusted_r2",
            scope,
            len(scoped),
            joint,
            f"<{joint_max}",
            joint_pass,
        )
        for control in controls:
            rho = _spearman(scoped["endpoint_rate"], scoped[control])
            maximum = spec["representation_gates"]["external_pairwise_absolute_spearman_maximum"]
            pair_pass = bool(np.isfinite(rho) and abs(rho) < maximum)
            external_checks.append(pair_pass)
            external_summary["pairwise"][f"{scope}|{control}"] = {
                "n": len(scoped),
                "spearman": rho,
                "pass": pair_pass,
            }
            _audit_row(
                audit,
                role,
                f"external_pairwise_{control}",
                scope,
                len(scoped),
                rho,
                f"abs<{maximum}",
                pair_pass,
            )

    representation_pass = all(
        [
            endpoint_support,
            shape_support,
            *nondeg_checks,
            *shape_checks,
            *definition_checks,
            *external_checks,
        ]
    )
    direction: dict[str, Any] = {"pass": False, "sign": 0, "blocks": {}, "annual_medians": {}}
    if representation_pass:
        block_signs: list[int] = []
        for block in ["A", "B"]:
            values = _scope(primary, block)["endpoint_rate"].to_numpy(dtype=float)
            median = float(np.median(values))
            sign = _sign(median)
            low, high = _bootstrap_interval(
                values, role, block, spec["common_direction_gate"]["bootstrap_resamples"]
            )
            direction["blocks"][block] = {
                "n": len(values),
                "median": median,
                "bootstrap_95": [low, high],
                "sign": sign,
            }
            block_signs.append(sign)
        common_sign = block_signs[0] if block_signs[0] == block_signs[1] else 0
        fractions: list[float] = []
        intervals_exclude: list[bool] = []
        for block in ["A", "B"]:
            values = _scope(primary, block)["endpoint_rate"].to_numpy(dtype=float)
            fractions.append(float(np.mean(np.sign(values) == common_sign)) if common_sign else 0.0)
            low, high = direction["blocks"][block]["bootstrap_95"]
            intervals_exclude.append(
                (low > 0 and high > 0)
                if common_sign > 0
                else (low < 0 and high < 0)
                if common_sign < 0
                else False
            )
            direction["blocks"][block]["same_sign_fraction"] = fractions[-1]
        year_signs: list[int] = []
        for year in spec["population"]["years"]:
            median = float(primary.loc[primary["target_year"].eq(year), "endpoint_rate"].median())
            direction["annual_medians"][str(year)] = median
            year_signs.append(_sign(median))
        direction_pass = bool(
            common_sign
            and all(intervals_exclude)
            and all(
                value >= spec["common_direction_gate"]["minimum_nonzero_sign_fraction_each_block"]
                for value in fractions
            )
            and sum(value == common_sign for value in year_signs)
            >= spec["common_direction_gate"]["minimum_year_medians_same_sign"]
        )
        direction.update({"pass": direction_pass, "sign": common_sign})
        for block in ["A", "B"]:
            detail = direction["blocks"][block]
            _audit_row(
                audit,
                role,
                "common_direction_median",
                block,
                detail["n"],
                detail["median"],
                "common nonzero sign; bootstrap excludes zero",
                direction_pass,
            )

    if not endpoint_support:
        status = "NOT_ESTIMABLE_ENDPOINT_SUPPORT"
    elif not shape_support:
        status = "NOT_ESTIMABLE_SHAPE_SUPPORT"
    elif not representation_pass:
        status = "REPRESENTATION_FAIL"
    elif direction["pass"]:
        status = "REPRESENTATION_PASS_COMMON_DIRECTION"
    else:
        status = "REPRESENTATION_PASS_NO_COMMON_DIRECTION"
    summary = {
        "status": status,
        "primary_trajectories": len(primary),
        "three_plus_event_trajectories": len(shape),
        "checks": {
            "endpoint_support": endpoint_support,
            "shape_support": shape_support,
            "nondegeneracy": all(nondeg_checks),
            "shape": all(shape_checks),
            "definition_and_clock": all(definition_checks),
            "external_geometry": all(external_checks),
        },
        "shape": shape_summary,
        "definitions": definition_summary,
        "external": external_summary,
        "common_direction": direction,
    }
    return summary, audit


def _coupling(
    spec: dict[str, Any], trajectory: pd.DataFrame, passing_roles: list[str]
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    primary = trajectory.loc[trajectory["definition"].eq(spec["population"]["primary_definition"])]
    records: list[dict[str, Any]] = []
    pair_decisions: dict[tuple[str, str], bool] = {}
    for left, right in combinations(passing_roles, 2):
        scopes: dict[str, dict[str, Any]] = {}
        for scope in ["GLOBAL", "A", "B"]:
            residuals: dict[str, pd.Series] = {}
            for role in [left, right]:
                role_frame = _scope(primary.loc[primary["role"].eq(role)], scope)
                controls = [
                    f"control__{field}__endpoint_rate" for field in spec["roles"][role]["controls"]
                ]
                residuals[role] = _rank_residuals(role_frame, "endpoint_rate", controls)
            joint = pd.concat(
                [residuals[left].rename("left"), residuals[right].rename("right")], axis=1
            ).dropna()
            rho = _spearman(joint["left"], joint["right"])
            scopes[scope] = {"n": len(joint), "spearman": rho}
            records.append(
                {
                    "left_role": left,
                    "right_role": right,
                    "scope": scope,
                    "n": len(joint),
                    "residual_spearman": rho,
                }
            )
        global_min = spec["residual_compression"]["minimum_global_intersection"]
        block_min = spec["residual_compression"]["minimum_each_block_intersection"]
        signs = [_sign(scopes[scope]["spearman"]) for scope in ["GLOBAL", "A", "B"]]
        passed = bool(
            scopes["GLOBAL"]["n"] >= global_min
            and all(scopes[block]["n"] >= block_min for block in ["A", "B"])
            and abs(scopes["GLOBAL"]["spearman"])
            >= spec["residual_compression"]["minimum_global_absolute_spearman"]
            and all(
                abs(scopes[block]["spearman"])
                >= spec["residual_compression"]["minimum_each_block_absolute_spearman"]
                for block in ["A", "B"]
            )
            and signs[0] != 0
            and signs[0] == signs[1] == signs[2]
        )
        pair_decisions[(left, right)] = passed
        for record in records[-3:]:
            record["pair_compression_pass"] = passed
    compression: dict[str, str] = {}
    minimal: list[str] = []
    for role in spec["residual_compression"]["fixed_priority"]:
        if role not in passing_roles:
            continue
        parent = next(
            (
                retained
                for retained in minimal
                if pair_decisions.get(tuple(sorted((retained, role))), False)
            ),
            None,
        )
        if parent is None:
            minimal.append(role)
        else:
            compression[role] = parent
    return pd.DataFrame(records), compression, minimal


def _manual_case_audit(
    spec: dict[str, Any], source: pd.DataFrame, trajectory: pd.DataFrame
) -> dict[str, Any]:
    primary = trajectory.loc[
        trajectory["definition"].eq(spec["population"]["primary_definition"])
    ].copy()
    primary["selection_hash"] = primary.apply(
        lambda row: hashlib.sha256(
            f"MKT-BREAKOUT-DYN-001|{row.sequence_id}|{row.role}".encode()
        ).hexdigest(),
        axis=1,
    )
    selected: list[pd.Series] = []
    used: set[str] = set()
    for _, row in primary.sort_values("selection_hash").iterrows():
        if row["sequence_id"] in used:
            continue
        selected.append(row)
        used.add(str(row["sequence_id"]))
        if len(selected) == spec["validation"]["manual_scalar_cases"]:
            break
    if len(selected) != spec["validation"]["manual_scalar_cases"]:
        raise BreakoutDynamicsError("manual scalar case support changed")
    cases: list[dict[str, Any]] = []
    maximum = 0.0
    for row in selected:
        role = str(row["role"])
        flag = spec["roles"][role]["domain_flag"]
        rows = source.loc[
            source["sequence_id"].eq(row["sequence_id"])
            & source["definition"].eq(spec["population"]["primary_definition"])
            & source[flag]
        ].sort_values("market_sequence_rank")
        ranks = [float(value) for value in rows["market_sequence_rank"]]
        values = [float(value) for value in rows[role]]
        endpoint = (values[-1] - values[0]) / (ranks[-1] - ranks[0])
        if len(values) >= 3:
            mean_x = sum(ranks) / len(ranks)
            mean_y = sum(values) / len(values)
            ols = sum(
                (x - mean_x) * (y - mean_y) for x, y in zip(ranks, values, strict=True)
            ) / sum((x - mean_x) ** 2 for x in ranks)
            slopes = [
                (values[j] - values[i]) / (ranks[j] - ranks[i])
                for i in range(len(ranks) - 1)
                for j in range(i + 1, len(ranks))
            ]
            theil = float(np.median(slopes))
        else:
            ols = np.nan
            theil = np.nan
        differences = [abs(endpoint - float(row["endpoint_rate"]))]
        if np.isfinite(ols):
            differences.append(abs(ols - float(row["ols_slope"])))
            differences.append(abs(theil - float(row["theil_sen_slope"])))
        case_max = max(differences)
        maximum = max(maximum, case_max)
        cases.append(
            {
                "sequence_id": row["sequence_id"],
                "role": role,
                "selection_hash": row["selection_hash"],
                "maximum_absolute_difference": case_max,
            }
        )
    if maximum > spec["validation"]["maximum_aggregate_absolute_difference"]:
        raise BreakoutDynamicsError("manual scalar reconstruction failed")
    return {"cases": cases, "maximum_aggregate_absolute_difference": maximum}


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _report(result: dict[str, Any]) -> str:
    roles = result["roles"]
    lines = [
        "# MKT-BREAKOUT-DYN-001 repeated-event dynamics",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        "- Representation-passing roles: "
        f"{', '.join(result['representation_passing_roles']) or 'none'}.",
        f"- Common-direction roles: {', '.join(result['common_direction_roles']) or 'none'}.",
        f"- Residual minimal roles: {', '.join(result['residual_minimal_roles']) or 'none'}.",
        "- Rates use actual market-session gaps across qualifying crossing days; "
        "non-crossing days are absent, never zero-filled.",
        "- Every source value is post-cross attribution. The complete trajectory "
        "is available only at 15:30 on its last included day.",
        "- No future return, outcome, strategy field, post-2023 partition, raw "
        "minute row, or CY-011 was read.",
        "",
        "## Role decisions",
        "",
        "| Role | Status | Endpoint trajectories | Three-plus-event trajectories |",
        "|---|---|---:|---:|",
    ]
    for role, detail in roles.items():
        lines.append(
            f"| {role} | {detail['status']} | {detail['primary_trajectories']} | "
            f"{detail['three_plus_event_trajectories']} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "A stable or direction-annotated trajectory is not favorable acceptance, "
            "prediction, habitat usefulness, or a trading rule. Residual compression "
            "is not a latent score or synergy claim.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec']}`",
            f"- Runner SHA-256: `{result['hashes']['runner']}`",
            f"- Trajectory SHA-256: `{result['hashes']['trajectory_panel']}`",
            f"- Stability SHA-256: `{result['hashes']['stability_audit']}`",
            f"- Coupling SHA-256: `{result['hashes']['coupling_audit']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    started = time.monotonic()
    spec, parent = _load_spec()
    source = _load_parent_panel(spec, parent)
    _resource_guard(spec, started)
    trajectory = _build_trajectories(spec, source)
    role_results: dict[str, Any] = {}
    audit_rows: list[dict[str, Any]] = []
    for role in spec["roles"]:
        role_result, role_audit = _evaluate_role(spec, trajectory, role)
        role_results[role] = role_result
        audit_rows.extend(role_audit)
    passing = [
        role
        for role, detail in role_results.items()
        if detail["status"].startswith("REPRESENTATION_PASS")
    ]
    common = [role for role in passing if role_results[role]["common_direction"]["pass"]]
    coupling, compression, minimal = _coupling(spec, trajectory, passing)
    scalar = _manual_case_audit(spec, source, trajectory)
    stability = (
        pd.DataFrame(audit_rows).sort_values(["role", "challenge", "scope"]).reset_index(drop=True)
    )
    coupling = (
        coupling.sort_values(["left_role", "right_role", "scope"]).reset_index(drop=True)
        if not coupling.empty
        else pd.DataFrame(
            columns=[
                "left_role",
                "right_role",
                "scope",
                "n",
                "residual_spearman",
                "pair_compression_pass",
            ]
        )
    )
    _write_csv(trajectory, PANEL_PATH)
    _write_csv(stability, STABILITY_PATH)
    _write_csv(coupling, COUPLING_PATH)
    _resource_guard(spec, started)
    if not passing:
        status = "COMPLETE_NO_TEMPORAL_REPRESENTATION"
    elif common:
        status = "COMPLETE_REPRESENTATION_PASS_COMMON_DIRECTION_PRESENT"
    else:
        status = "COMPLETE_REPRESENTATION_PASS_NO_COMMON_DIRECTION"
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "population": {
            "input_panel_rows": len(source),
            "trajectory_rows": len(trajectory),
            "primary_endpoint_trajectories_by_role": {
                role: detail["primary_trajectories"] for role, detail in role_results.items()
            },
            "primary_three_plus_by_role": {
                role: detail["three_plus_event_trajectories"]
                for role, detail in role_results.items()
            },
            "raw_minute_rows_read": 0,
        },
        "roles": role_results,
        "representation_passing_roles": passing,
        "common_direction_roles": common,
        "residual_compression": compression,
        "residual_minimal_roles": minimal,
        "scalar_reconstruction": scalar,
        "hashes": {
            "spec": _sha256_file(SPEC_PATH),
            "runner": _sha256_file(Path(__file__)),
            **RUNNER_DEPENDENCIES,
            "parent_panel": spec["inputs"]["session_panel"]["sha256"],
            "parent_result": spec["inputs"]["parent_result"]["sha256"],
            "temporal_map": spec["inputs"]["temporal_dynamics_map"]["sha256"],
            "trajectory_panel": _sha256_file(PANEL_PATH),
            "stability_audit": _sha256_file(STABILITY_PATH),
            "coupling_audit": _sha256_file(COUPLING_PATH),
        },
        "future_fields_read": False,
        "strategy_or_outcome_fields_read": False,
        "post_2023_data_read": False,
        "cy011_read": False,
        "prediction_or_usefulness_claim": False,
        "new_strategy_archetype": False,
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    durable = sum(
        path.stat().st_size
        for path in [PANEL_PATH, STABILITY_PATH, COUPLING_PATH, RESULT_PATH, REPORT_PATH]
    )
    if durable > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise BreakoutDynamicsError("durable output ceiling breached")
    _resource_guard(spec, started)
    print(
        json.dumps(
            {
                "status": status,
                "passing_roles": passing,
                "common_direction_roles": common,
                "minimal_roles": minimal,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
