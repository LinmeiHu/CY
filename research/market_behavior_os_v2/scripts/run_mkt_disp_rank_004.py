#!/usr/bin/env python3
"""Run high-dispersion industry-rank direction with a support-only amendment."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-DISP-RANK-004_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-004_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-004_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DISP-RANK-004_industry_rank.md"
RESOURCE_RUNNER_PATH = PROGRAM / "scripts/run_mkt_disp_rank_003.py"
EXPECTED_SPEC_SHA256 = "130bc11b00c3268c34159927ebc932b8767423916cba9171542b79703a629e98"


class DispersionRankAmendmentError(RuntimeError):
    """Fail-closed support-only amendment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise DispersionRankAmendmentError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


RESOURCE = _load_module("mkt_disp_rank_003_for_004", RESOURCE_RUNNER_PATH)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DispersionRankAmendmentError("support-amendment spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SUPPORT_ONLY_AMENDMENT_BEFORE_RESPONSE_SUMMARIES":
        raise DispersionRankAmendmentError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionRankAmendmentError(f"bound input changed: {name}")
    return spec


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _analyze_high_only(
    daily: pd.DataFrame, scientific: dict[str, Any], amendment: dict[str, Any], rank: Any
) -> tuple[pd.DataFrame, dict[str, Any]]:
    keys = rank.KEYS
    state_column = rank.STATE
    state = pd.read_csv(
        _resolve(scientific["inputs"]["industry_panel"]["path"]),
        parse_dates=["trade_date"],
    )[[*keys, state_column]]
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    panel = daily.merge(state, on=keys, how="left", validate="one_to_one")
    panel = panel.sort_values(keys).reset_index(drop=True)
    panel["calendar_year"] = panel.trade_date.dt.year
    panel["session_ordinal"] = panel.groupby(keys[1:], sort=False).cumcount()

    support = scientific["support"]
    cell_counts = panel.groupby(keys[1:]).size()
    pit = panel.dropna(subset=[state_column]).copy()
    pit_counts = pit.groupby(keys[1:]).size()
    high = pit.loc[pit[state_column].ge(0.8)].copy()
    low = pit.loc[pit[state_column].le(0.2)].copy()
    high_counts = high.groupby(keys[1:]).size()
    low_counts = low.groupby(keys[1:]).size()
    if (
        len(cell_counts) != 8
        or cell_counts.min() < support["minimum_daily_rows_per_cell"]
        or pit_counts.min() < support["minimum_pit_rows_per_cell"]
        or high_counts.min() < support["minimum_high_state_rows_per_cell"]
    ):
        raise DispersionRankAmendmentError("daily/PIT/high-state support gate failed")
    descriptive_low_floor = amendment["only_scientific_change"][
        "minimum_low_rows_for_descriptive_reporting"
    ]
    if len(low_counts) != 8 or low_counts.min() < descriptive_low_floor:
        raise DispersionRankAmendmentError("descriptive low-state support floor failed")
    annual_high = high.groupby(["calendar_year", *keys[1:]]).size()
    supported_annual = annual_high.loc[
        annual_high.index.get_level_values(0).isin([2020, 2021, 2022, 2023])
    ]
    if supported_annual.min() < support["minimum_high_state_rows_per_cell_year"]:
        raise DispersionRankAmendmentError("annual high-state support gate failed")

    high_summary: dict[str, Any] = {}
    low_summary: dict[str, Any] = {}
    for horizon in (1, 3, 5):
        high_median, high_cells = rank._median_by_cell(high, f"rank_ic_h{horizon}")
        low_median, low_cells = rank._median_by_cell(low, f"rank_ic_h{horizon}")
        high_spread, high_spread_cells = rank._median_by_cell(
            high, f"top_bottom_h{horizon}"
        )
        high_summary[str(horizon)] = {
            "median_cell_rank_ic": high_median,
            "cell_rank_ics": high_cells,
            "median_cell_top_bottom_attribution": high_spread,
            "cell_top_bottom_attributions": high_spread_cells,
        }
        low_summary[str(horizon)] = {
            "descriptive_only": True,
            "median_cell_rank_ic": low_median,
            "cell_rank_ics": low_cells,
        }
    annual: dict[str, float] = {}
    for year, annual_frame in high.groupby("calendar_year", sort=True):
        if int(year) in (2020, 2021, 2022, 2023):
            annual[str(year)] = rank._median_by_cell(annual_frame, "rank_ic_h3")[0]
    phases = {
        str(phase): rank._median_by_cell(
            high.loc[high.session_ordinal.mod(3).eq(phase)], "rank_ic_h3"
        )[0]
        for phase in range(3)
    }
    state_ic_cells = [
        float(rank.spearmanr(cell[state_column], cell["rank_ic_h3"]).statistic)
        for _, cell in pit.groupby(keys[1:], sort=True)
    ]
    boundary = scientific["classification"]
    h3 = high_summary["3"]["median_cell_rank_ic"]
    continuation = (
        h3 >= boundary["continuation_minimum_absolute_median_high_state_ic"]
        and all(value > 0 for value in high_summary["3"]["cell_rank_ics"])
        and all(value > 0 for value in annual.values())
        and high_summary["1"]["median_cell_rank_ic"] >= 0
        and high_summary["5"]["median_cell_rank_ic"] >= 0
        and all(value > 0 for value in phases.values())
    )
    reversal = (
        h3 <= boundary["reversal_maximum_median_high_state_ic"]
        and all(value < 0 for value in high_summary["3"]["cell_rank_ics"])
        and all(value < 0 for value in annual.values())
        and high_summary["1"]["median_cell_rank_ic"] <= 0
        and high_summary["5"]["median_cell_rank_ic"] <= 0
        and all(value < 0 for value in phases.values())
    )
    classification = (
        "HIGH_DISPERSION_INDUSTRY_RANK_CONTINUATION"
        if continuation
        else "HIGH_DISPERSION_INDUSTRY_RANK_REVERSAL"
        if reversal
        else "HIGH_DISPERSION_DIRECTIONLESS_OR_UNSTABLE_RANKING"
    )
    result = {
        "experiment_id": amendment["experiment_id"],
        "research_level": amendment["research_level"],
        "classification": classification,
        "support_amendment": amendment["only_scientific_change"],
        "high_dispersion": high_summary,
        "low_dispersion": low_summary,
        "high_dispersion_annual_h3_median_cell_rank_ic": annual,
        "high_dispersion_h3_nonoverlap_phase_median_cell_rank_ic": phases,
        "dispersion_state_to_h3_rank_ic": {
            "median_cell_spearman": float(np.median(state_ic_cells)),
            "cell_spearmans": state_ic_cells,
        },
        "support": {
            "panel_rows": len(panel),
            "minimum_daily_rows_per_cell": int(cell_counts.min()),
            "minimum_pit_rows_per_cell": int(pit_counts.min()),
            "minimum_high_rows_per_cell": int(high_counts.min()),
            "minimum_low_rows_per_cell_descriptive_only": int(low_counts.min()),
            "minimum_high_rows_per_supported_cell_year": int(supported_annual.min()),
            "minimum_industries_per_date_cell": int(panel.industry_count.min()),
            "minimum_industry_response_retention": float(
                panel.minimum_industry_retention.min()
            ),
        },
        "interpretation": {
            "industry_rank_direction_established": continuation or reversal,
            "security_selection_estimated": False,
            "portfolio_pnl_estimated": False,
            "strategy_authorized": False,
        },
        "same_bar_fill_assumed": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
    }
    return panel, result


def _render(result: dict[str, Any]) -> str:
    high = result["high_dispersion"]
    support = result["support"]
    return f"""# MKT-DISP-RANK-004 high-dispersion industry-rank discriminator

`{result['classification']}`. In the fixed high-dispersion state, median cell
industry rank IC at h=1/3/5 is {high['1']['median_cell_rank_ic']:.5f},
{high['3']['median_cell_rank_ic']:.5f}, and
{high['5']['median_cell_rank_ic']:.5f}. The h=3 top-minus-bottom industry
attribution is {high['3']['median_cell_top_bottom_attribution']:.5f}.

All eight high-state cells have at least {support['minimum_high_rows_per_cell']}
dates and all supported cell-years have at least
{support['minimum_high_rows_per_supported_cell_year']}. The low state has a
minimum of {support['minimum_low_rows_per_cell_descriptive_only']} rows and is
reported as descriptive context only. It is absent from every direction gate.

The support-only amendment was frozen after MKT-DISP-RANK-003 stopped before any
response summary was returned. High-state definitions, h1/h3/h5 responses, all
eight views, four annual gates, three phase gates, and direction boundaries are
unchanged.

These are future industry-response attributions using t membership, not
realizable portfolio returns. No same-bar fill, security selection, PnL, cost,
capacity, strategy outcome, post-2023 row, or CY-011 field is used.
"""


def run() -> dict[str, Any]:
    amendment = _load_spec()
    resource_spec = RESOURCE._load_spec()
    preflight = RESOURCE._resource_preflight(resource_spec)
    retry, scientific, industry_spec, industry_runner, rank = (
        RESOURCE.BASE._load_spec()
    )
    effective = RESOURCE._effective_scientific(scientific, resource_spec)
    scratch = Path(resource_spec["resource_contract"]["scratch_root"])
    previous_tempdir = tempfile.tempdir
    previous_builder = RESOURCE.BASE._create_rank_security_for_year
    tempfile.tempdir = str(scratch)
    RESOURCE.BASE._create_rank_security_for_year = (
        RESOURCE._create_rank_security_for_year_explicit_group
    )
    try:
        daily, telemetry = RESOURCE.BASE._build_daily_batched(
            retry, effective, industry_spec, industry_runner, rank
        )
    finally:
        tempfile.tempdir = previous_tempdir
        RESOURCE.BASE._create_rank_security_for_year = previous_builder
    panel, result = _analyze_high_only(daily, effective, amendment, rank)
    panel_csv = panel.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    if len(panel_csv.encode("utf-8")) > int(
        resource_spec["resource_contract"]["durable_output_ceiling_mib"] * 2**20
    ):
        raise DispersionRankAmendmentError("durable output ceiling breached")
    _atomic_write(PANEL_PATH, panel_csv)
    result["status"] = "COMPLETE_SUPPORT_ONLY_AMENDMENT"
    result["resource_preflight"] = preflight
    result["resource_contract"] = resource_spec["resource_contract"]
    result["engineering"] = telemetry
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
    }
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(rank._clean(result), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True, default=str))
