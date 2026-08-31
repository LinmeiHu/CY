#!/usr/bin/env python3
"""Build one governed CHINEXT candidate panel and marginal information scan."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
CHX_SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(CHX_SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from run_chinext_v1_full_survivor import read_jsonl  # noqa: E402
from run_chinext_v1_pit_replay import reconstruct_round_trips  # noqa: E402

SPEC_PATH = PROGRAM / "experiments/HAB-CHX-RANK-INFO-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/HAB-CHX-RANK-INFO-001_candidate_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-RANK-INFO-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-RANK-INFO-001_information_scan.md"
EXPECTED_SPEC_SHA256 = "0ec65815558aab2373dc8f2e93c329cc61ee521275191aee2cf3308d8e9bac10"

FEATURES = (
    "rs_score",
    "r20",
    "r60",
    "r120",
    "rs_acceleration",
    "mom20",
    "mom60",
    "mom120",
    "box_width",
    "ma_dispersion",
    "direction_efficiency",
    "vol_ratio",
    "minvol_location",
    "minvol_ratio",
    "breakout_volume_ratio",
)
HIGHER_GOOD = {
    "rs_score",
    "r20",
    "r60",
    "r120",
    "mom20",
    "mom60",
    "mom120",
    "breakout_volume_ratio",
}
BLOCKS = {
    "development_2018_2021": ("development_event_ledger", "development_execution_ledger"),
    "consumed_2022_2023": ("consumed_event_ledger", "consumed_execution_ledger"),
}
START = date(2018, 1, 2)
END = date(2023, 12, 29)
OUTCOME_HORIZON = 20
TRANSACTION_COST = 0.001


class CandidateInformationError(RuntimeError):
    """Fail-closed candidate-information contract error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise CandidateInformationError("candidate-information spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_PANEL_AND_MARGINAL_SCAN_BEFORE_ACCEPTED_ESTIMATES":
        raise CandidateInformationError("candidate-information honesty status changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise CandidateInformationError(f"bound input identity mismatch: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "0.20", "future-path", "random-shuffle"):
        if phrase not in prohibited:
            raise CandidateInformationError(f"missing prohibition: {phrase}")
    return spec


def _validate_cy006(spec: dict[str, Any]) -> list[Path]:
    registry = json.loads(
        _resolve(spec["inputs"]["data_asset_registry"]["path"]).read_text()
    )
    assets = {row["asset_id"]: row for row in registry["assets"]}
    asset = assets.get("CY-006")
    if (
        asset is None
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or not asset.get("quality_evidence", {}).get("gate_pass")
        or asset.get("coverage", {}).get("start") > START.isoformat()
        or asset.get("coverage", {}).get("end") < END.isoformat()
    ):
        raise CandidateInformationError("CY-006 registry contract is not active")
    required_use = "daily causal state generation with row-level hard_valid enforcement"
    if required_use not in asset["allowed_uses"]:
        raise CandidateInformationError("CY-006 causal research use changed")
    manifest = json.loads(
        _resolve(spec["inputs"]["cy006_manifest"]["path"]).read_text()
    )
    root = Path(manifest["root"])
    files_by_year: dict[int, dict[str, Any]] = {}
    for binding in manifest["files"]:
        year = int(str(binding["path"]).split("partition_year=")[1].split("/")[0])
        files_by_year[year] = binding
    paths: list[Path] = []
    for year in range(START.year, END.year + 1):
        binding = files_by_year.get(year)
        if binding is None:
            raise CandidateInformationError(f"CY-006 manifest lacks year {year}")
        path = root / binding["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(binding["size"])
            or sha256_file(path) != binding["sha256"]
        ):
            raise CandidateInformationError(f"CY-006 partition identity mismatch: {year}")
        paths.append(path)
    return paths


def _candidate_rows(block: str, event_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in read_jsonl(event_path):
        if event.get("event") != "ENTRY_SIGNAL_EVALUATED":
            continue
        signal_date = date.fromisoformat(str(event["signal_date"]))
        if not START <= signal_date <= END:
            raise CandidateInformationError("event outside permitted pre-2024 range")
        if not bool(event["minvol"]["passed"]) or event.get("rs") is None:
            continue
        acceleration = Decimal(str(event["rs"]["r20"])) - Decimal(
            str(event["rs"]["r120"])
        )
        if acceleration >= Decimal("0.20"):
            continue
        rs = event["rs"]
        full = event["full40"]
        minimum = event["minvol"]
        breakout = event["breakout_volume"]
        row = {
            "block": block,
            "trade_date": signal_date,
            "decision_at": f"{signal_date.isoformat()}T15:00:00+08:00",
            "symbol": str(event["symbol"]),
            "rs_score": float(rs["score"]),
            "r20": float(rs["r20"]),
            "r60": float(rs["r60"]),
            "r120": float(rs["r120"]),
            "rs_acceleration": float(acceleration),
            "mom20": float(rs["mom20"]),
            "mom60": float(rs["mom60"]),
            "mom120": float(rs["mom120"]),
            "box_width": float(full["box_width"]),
            "ma_dispersion": float(full["ma_dispersion"]),
            "direction_efficiency": float(full["direction_efficiency"]),
            "vol_ratio": float(full["vol_ratio"]),
            "minvol_location": float(minimum["location"]),
            "minvol_ratio": float(minimum["minimum_volume_ratio"]),
            "breakout_volume_ratio": float(breakout["ratio"]),
        }
        if not all(math.isfinite(row[name]) for name in FEATURES):
            raise CandidateInformationError("candidate has nonfinite signal-time descriptor")
        rows.append(row)
    return rows


def _selection_maps(
    execution_path: Path,
) -> tuple[set[tuple[str, str]], dict[tuple[str, str], float]]:
    executions = read_jsonl(execution_path)
    if any(date.fromisoformat(str(row["execution_date"])) > END for row in executions):
        raise CandidateInformationError("execution ledger contains post-2023 row")
    selected = {
        (str(row["signal_date"]), str(row["symbol"]))
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
    }
    actual: dict[tuple[str, str], float] = {}
    for trip in reconstruct_round_trips(executions):
        key = (str(trip["entry_signal_date"]), str(trip["symbol"]))
        if key in actual:
            raise CandidateInformationError(f"duplicate completed cycle key: {key}")
        actual[key] = float(trip["round_trip_return"])
    return selected, actual


def _build_candidates(spec: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for block, (event_name, execution_name) in BLOCKS.items():
        block_rows = _candidate_rows(block, _resolve(spec["inputs"][event_name]["path"]))
        selected, actual = _selection_maps(
            _resolve(spec["inputs"][execution_name]["path"])
        )
        for row in block_rows:
            key = (row["trade_date"].isoformat(), row["symbol"])
            row["selected_by_current_system"] = key in selected
            row["actual_completed_trade_return"] = actual.get(key)
        rows.extend(block_rows)
    panel = pd.DataFrame(rows).sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    if panel.duplicated(["trade_date", "symbol"]).any():
        raise CandidateInformationError("candidate panel contains duplicate key")
    if len(panel) != 398:
        raise CandidateInformationError(f"frozen current-candidate count changed: {len(panel)}")
    panel["candidate_count"] = panel.groupby("trade_date")["symbol"].transform("size")
    panel["baseline_rank"] = (
        panel.sort_values(
            ["trade_date", "rs_score", "mom60", "symbol"],
            ascending=[True, False, False, True],
        )
        .groupby("trade_date")
        .cumcount()
        .add(1)
        .reindex(panel.index)
    )
    panel["candidate_id"] = (
        panel["block"].astype(str)
        + "|"
        + panel["trade_date"].astype(str)
        + "|"
        + panel["symbol"]
    )
    return panel


def _load_sessions(spec: dict[str, Any]) -> list[date]:
    calendar = pd.read_parquet(_resolve(spec["inputs"]["calendar"]["path"]))
    column = "trade_date" if "trade_date" in calendar else "cal_date"
    sessions = sorted(set(pd.to_datetime(calendar[column]).dt.date))
    if START not in sessions or END not in sessions:
        raise CandidateInformationError("calendar does not cover research boundary")
    return sessions


def _outcome_links(panel: pd.DataFrame, sessions: list[date]) -> pd.DataFrame:
    index = {day: offset for offset, day in enumerate(sessions)}
    rows = []
    for row in panel.itertuples():
        signal_index = index.get(row.trade_date)
        if signal_index is None or signal_index + OUTCOME_HORIZON >= len(sessions):
            raise CandidateInformationError("candidate lacks calendar outcome horizon")
        for horizon in range(1, OUTCOME_HORIZON + 1):
            rows.append((row.Index, row.symbol, sessions[signal_index + horizon], horizon))
    return pd.DataFrame(rows, columns=["candidate_row", "symbol", "trade_date", "horizon"])


def _query_outcome_rows(paths: list[Path], links: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register("candidate_links", links)
    columns = """
        l.candidate_row, l.horizon, d.trade_date, d.symbol,
        d.open, d.high, d.low, d.close,
        d.hard_valid, d.trade_status, d.current_day_data_tradable,
        d.buy_blocked_open, d.corporate_action_count,
        d.corporate_action_valid, d.corporate_action_blocking,
        d.corporate_action_available_date, d.share_multiplier,
        d.cash_per_share, d.rights_ratio, d.available_at
    """
    frame = connection.execute(
        f"""
        SELECT {columns}
        FROM read_parquet(?) d
        INNER JOIN candidate_links l
          ON d.symbol = l.symbol AND d.trade_date = l.trade_date
        ORDER BY l.candidate_row, l.horizon
        """,
        [[str(path) for path in paths]],
    ).fetchdf()
    expected = len(links)
    if len(frame) != expected or frame.duplicated(["candidate_row", "horizon"]).any():
        raise CandidateInformationError(
            f"candidate outcome join mismatch: rows={len(frame)}, expected={expected}"
        )
    return frame


def _visible_action(row: Any) -> tuple[float, float] | None:
    rights = 0.0 if pd.isna(row.rights_ratio) else float(row.rights_ratio)
    multiplier = 1.0 if pd.isna(row.share_multiplier) else float(row.share_multiplier)
    cash_per_share = 0.0 if pd.isna(row.cash_per_share) else float(row.cash_per_share)
    available = (
        None
        if pd.isna(row.corporate_action_available_date)
        else pd.Timestamp(row.corporate_action_available_date).date()
    )
    trade_date = pd.Timestamp(row.trade_date).date()
    valid = (
        bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and rights == 0.0
        and multiplier > 0
        and available is not None
        and available <= trade_date
        and all(math.isfinite(value) for value in (rights, multiplier, cash_per_share))
    )
    return (multiplier, cash_per_share) if valid else None


def _candidate_outcome(group: pd.DataFrame) -> dict[str, Any]:
    group = group.sort_values("horizon")
    if group["horizon"].tolist() != list(range(1, OUTCOME_HORIZON + 1)):
        return {"outcome_status": "MISSING_HORIZON"}
    entry = group.iloc[0]
    entry_available = pd.Timestamp(entry.available_at)
    entry_date = pd.Timestamp(entry.trade_date).date()
    entry_valid = (
        bool(entry.hard_valid)
        and int(entry.trade_status) == 1
        and bool(entry.current_day_data_tradable)
        and not bool(entry.buy_blocked_open)
        and math.isfinite(float(entry.open))
        and float(entry.open) > 0
        and not pd.isna(entry_available)
        and entry_available.date() <= entry_date
    )
    if not entry_valid:
        return {"outcome_status": "NEXT_OPEN_NOT_EXECUTABLE"}
    entry_price = float(entry.open)
    entry_cost = entry_price * (1.0 + TRANSACTION_COST)
    shares = 1.0
    cash = 0.0
    mfe = -math.inf
    mae = math.inf
    return5 = None
    return20 = None
    for row in group.itertuples():
        trade_date = pd.Timestamp(row.trade_date).date()
        available = pd.Timestamp(row.available_at)
        prices = (row.high, row.low, row.close)
        if (
            not bool(row.hard_valid)
            or pd.isna(available)
            or available.date() > trade_date
            or not all(value is not None and math.isfinite(float(value)) for value in prices)
        ):
            return {"outcome_status": "INVALID_PATH_ROW"}
        action_count = int(row.corporate_action_count or 0)
        if row.horizon > 1 and action_count > 0:
            action = _visible_action(row)
            if action is None:
                return {"outcome_status": "CORPORATE_ACTION_FAIL_CLOSED"}
            multiplier, cash_per_share = action
            cash += shares * cash_per_share
            shares *= multiplier
        high_return = (cash + shares * float(row.high)) / entry_cost - 1.0
        low_return = (cash + shares * float(row.low)) / entry_cost - 1.0
        close_return = (
            cash + shares * float(row.close) * (1.0 - TRANSACTION_COST)
        ) / entry_cost - 1.0
        mfe = max(mfe, high_return)
        mae = min(mae, low_return)
        if row.horizon == 5:
            return5 = close_return
        if row.horizon == OUTCOME_HORIZON:
            return20 = close_return
    return {
        "outcome_status": "COMPLETE",
        "next_open_price": entry_price,
        "forward_return_5": return5,
        "forward_return_20": return20,
        "mfe_20": mfe,
        "mae_20": mae,
    }


def _attach_outcomes(panel: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    outcomes = {
        int(candidate_row): _candidate_outcome(group)
        for candidate_row, group in rows.groupby("candidate_row", sort=True)
    }
    for column in (
        "outcome_status",
        "next_open_price",
        "forward_return_5",
        "forward_return_20",
        "mfe_20",
        "mae_20",
    ):
        panel[column] = [outcomes[index].get(column) for index in panel.index]
    for feature in FEATURES:
        oriented = panel[feature] if feature in HIGHER_GOOD else -panel[feature]
        panel[f"oriented_pct__{feature}"] = oriented.groupby(panel["trade_date"]).rank(
            method="average", pct=True
        )
    return panel


def _metrics(values: pd.Series) -> dict[str, Any]:
    finite = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    return {
        "n": len(finite),
        "mean": float(np.mean(finite)) if len(finite) else None,
        "median": float(np.median(finite)) if len(finite) else None,
        "win_rate": float(np.mean(finite > 0)) if len(finite) else None,
        "winner20_rate": float(np.mean(finite >= 0.20)) if len(finite) else None,
        "severe_loss_rate": float(np.mean(finite <= -0.10)) if len(finite) else None,
    }


def _rho(left: pd.Series, right: pd.Series) -> float | None:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 10 or frame.left.nunique() < 2 or frame.right.nunique() < 2:
        return None
    value = float(spearmanr(frame.left, frame.right).statistic)
    return value if math.isfinite(value) else None


def _top1_rows(panel: pd.DataFrame, score: str) -> pd.DataFrame:
    eligible = panel.loc[
        panel["forward_return_20"].notna() & panel["candidate_count"].ge(2)
    ].copy()
    return (
        eligible.sort_values(["trade_date", score, "symbol"], ascending=[True, False, True])
        .groupby("trade_date", as_index=False)
        .head(1)
    )


def _top1_diagnostic(panel: pd.DataFrame, feature: str) -> dict[str, Any]:
    score = f"oriented_pct__{feature}"
    selected = _top1_rows(panel, score)
    result: dict[str, Any] = {}
    for block in BLOCKS:
        rows = selected.loc[selected.block.eq(block)]
        candidates = panel.loc[
            panel.block.eq(block)
            & panel.forward_return_20.notna()
            & panel.candidate_count.ge(2)
        ]
        oracle = candidates.groupby("trade_date")["forward_return_20"].max()
        chosen = rows.set_index("trade_date")["forward_return_20"]
        aligned = pd.concat([chosen.rename("chosen"), oracle.rename("oracle")], axis=1).dropna()
        result[block] = {
            **_metrics(rows["forward_return_20"]),
            "date_count": int(rows.trade_date.nunique()),
            "oracle_winner_capture": float(np.mean(np.isclose(aligned.chosen, aligned.oracle)))
            if len(aligned)
            else None,
        }
    return result


def _scan_feature(panel: pd.DataFrame, feature: str) -> dict[str, Any]:
    finite = panel.loc[panel.forward_return_20.notna()].copy()
    oriented = finite[feature] if feature in HIGHER_GOOD else -finite[feature]
    block_rho = {}
    buckets = {}
    for block, rows in finite.groupby("block"):
        direction = rows[feature] if feature in HIGHER_GOOD else -rows[feature]
        block_rho[block] = _rho(direction, rows.forward_return_20)
        percentile = direction.rank(method="average", pct=True)
        labels = pd.cut(
            percentile,
            bins=[0.0, 1 / 3, 2 / 3, 1.0],
            labels=["bottom", "middle", "top"],
            include_lowest=True,
        )
        buckets[block] = {
            label: _metrics(rows.loc[labels.eq(label), "forward_return_20"])
            for label in ("bottom", "middle", "top")
        }
    return {
        "family": next(
            family
            for family, members in {
                "trend_relative_strength": FEATURES[:8],
                "supply_demand": FEATURES[11:],
                "risk_path_setup": FEATURES[8:11],
            }.items()
            if feature in members
        ),
        "orientation": "higher" if feature in HIGHER_GOOD else "lower",
        "coverage": float(panel[feature].notna().mean()),
        "oriented_spearman_all": _rho(oriented, finite.forward_return_20),
        "oriented_spearman_by_block": block_rho,
        "coarse_buckets": buckets,
        "same_date_top1": _top1_diagnostic(panel, feature),
    }


def _classify(scan: dict[str, Any], redundancy: float | None, baseline: dict[str, Any]) -> str:
    if redundancy is not None and redundancy >= 0.85:
        return "REDUNDANT"
    blocks = list(BLOCKS)
    rhos = [scan["oriented_spearman_by_block"].get(block) for block in blocks]
    deltas = []
    severe_deltas = []
    for block in blocks:
        current = scan["same_date_top1"][block]
        base = baseline["same_date_top1"][block]
        deltas.append(current["mean"] - base["mean"])
        severe_deltas.append(current["severe_loss_rate"] - base["severe_loss_rate"])
    if all(value is not None and value >= 0.05 for value in rhos) and all(
        value >= 0.01 for value in deltas
    ):
        return "STRONG_STANDALONE"
    if all(value <= -0.02 for value in severe_deltas):
        return "RISK_OR_EXECUTION"
    if all(value is not None for value in rhos) and rhos[0] * rhos[1] < 0:
        return "CONDITIONAL"
    if all(value is not None and abs(value) < 0.03 for value in rhos) and all(
        abs(value) < 0.005 for value in deltas
    ):
        return "NO_USEFUL_EVIDENCE"
    return "COMPLEMENTARY"


def _analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    scans = {feature: _scan_feature(panel, feature) for feature in FEATURES}
    feature_frame = panel.loc[panel.forward_return_20.notna(), FEATURES]
    correlation = feature_frame.corr(method="spearman")
    baseline = scans["rs_score"]
    for feature in FEATURES:
        redundancy = (
            None
            if feature == "rs_score"
            else abs(float(correlation.loc[feature, "rs_score"]))
        )
        scans[feature]["absolute_rho_with_existing_rs_score"] = redundancy
        scans[feature]["information_role"] = (
            "EXISTING_BASELINE_CONDITIONAL"
            if feature == "rs_score"
            else _classify(scans[feature], redundancy, baseline)
        )
    pairwise = []
    for left_index, left in enumerate(FEATURES):
        for right in FEATURES[left_index + 1 :]:
            pairwise.append(
                {"left": left, "right": right, "spearman": float(correlation.loc[left, right])}
            )
    pairwise.sort(key=lambda row: (-abs(row["spearman"]), row["left"], row["right"]))
    complete = panel.loc[panel.outcome_status.eq("COMPLETE")]
    counts = {
        "candidate_rows": len(panel),
        "complete_outcome_rows": len(complete),
        "outcome_coverage": float(len(complete) / len(panel)),
        "candidate_dates": int(panel.trade_date.nunique()),
        "multi_candidate_dates": int(
            panel.groupby("trade_date").size().ge(2).sum()
        ),
        "maximum_candidates_one_date": int(panel.groupby("trade_date").size().max()),
        "selected_new_position_events": int(panel.selected_by_current_system.sum()),
        "completed_selected_cycles": int(panel.actual_completed_trade_return.notna().sum()),
        "by_block": {
            block: {
                "candidate_rows": int(rows.shape[0]),
                "complete_outcomes": int(rows.forward_return_20.notna().sum()),
                "candidate_dates": int(rows.trade_date.nunique()),
                "multi_candidate_dates": int(rows.groupby("trade_date").size().ge(2).sum()),
            }
            for block, rows in panel.groupby("block")
        },
    }
    if counts["candidate_rows"] != 398 or counts["complete_outcome_rows"] != 397:
        raise CandidateInformationError("candidate or outcome count changed")
    return {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_CANDIDATE_INFORMATION_SCAN",
        "honesty_boundary": spec["honesty_boundary"],
        "counts": counts,
        "outcome_summary": {
            block: _metrics(rows["forward_return_20"])
            for block, rows in complete.groupby("block")
        },
        "descriptors": scans,
        "pairwise_redundancy_top20": pairwise[:20],
        "claim_boundary": {
            "untouched_validation": False,
            "post_2023_rows_read": False,
            "cy011_read": False,
            "fixed_veto_changed": False,
            "portfolio_replay": False,
            "future_fields_used_as_predictors": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-RANK-INFO-001 — candidate information scan",
        "",
        "The current fixed admission system produced "
        f"{result['counts']['candidate_rows']} candidate events on "
        f"{result['counts']['candidate_dates']} dates. Only "
        f"{result['counts']['multi_candidate_dates']} dates contain ranking competition.",
        "",
        "| Descriptor | Family | Role | Oriented rho dev | Oriented rho later | "
        "Top-1 mean delta dev | Top-1 mean delta later |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    baseline = result["descriptors"]["rs_score"]
    for feature in FEATURES:
        row = result["descriptors"][feature]
        deltas = []
        for block in BLOCKS:
            deltas.append(
                row["same_date_top1"][block]["mean"]
                - baseline["same_date_top1"][block]["mean"]
            )
        rhos = row["oriented_spearman_by_block"]
        lines.append(
            f"| {feature} | {row['family']} | {row['information_role']} | "
            f"{rhos['development_2018_2021']:.3f} | "
            f"{rhos['consumed_2022_2023']:.3f} | {deltas[0]:.3%} | "
            f"{deltas[1]:.3%} |"
        )
    lines.extend(
        [
            "",
            "The 20-session target is attribution from an executable next open, not a "
            "strategy replay. All descriptors are available at the completed signal close; "
            "future return, MFE, and MAE fields are never predictors.",
            "",
            "Every block is consumed development history. No post-2023 or CY-011 row was read.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    if PANEL_PATH.exists() or RESULT_PATH.exists() or REPORT_PATH.exists():
        raise CandidateInformationError("candidate-information output already exists")
    daily_paths = _validate_cy006(spec)
    panel = _build_candidates(spec)
    sessions = _load_sessions(spec)
    links = _outcome_links(panel, sessions)
    outcome_rows = _query_outcome_rows(daily_paths, links)
    panel = _attach_outcomes(panel, outcome_rows)
    result = _analyze(panel, spec)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel_to_write = panel.copy()
    panel_to_write["trade_date"] = panel_to_write["trade_date"].astype(str)
    _atomic_write(PANEL_PATH, panel_to_write.to_csv(index=False, lineterminator="\n"))
    result["hashes"]["panel_sha256"] = sha256_file(PANEL_PATH)
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
