#!/usr/bin/env python3
"""Execute one committed, preregistered ChinNext V2 2018-2021 mechanism attempt."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
CHINEXT_ROOT = ROOT / "research/chinext_v1"
for import_root in (str(SCRIPTS), str(CHINEXT_ROOT)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

import run_chinext_v1_extended_replay as extended  # noqa: E402
from run_chinext_v1_full_survivor import (  # noqa: E402
    INITIAL_CASH,
    performance_extensions,
    read_jsonl,
)
from run_chinext_v1_pit_replay import concentration, reconstruct_round_trips  # noqa: E402
from run_chinext_v1_smoke import run as run_engine  # noqa: E402
from strategy.chinext_v2_candidate import (  # noqa: E402
    PARENT_V1_STRATEGY_SHA256,
    policy_for,
)

START = date(2018, 1, 2)
END = date(2021, 12, 31)
WARMUP_START = date(2017, 4, 12)
PREREG_RELATIVE = Path(
    "research/chinext_v1/specs/chinext_v2_attempt_preregistration.json"
)
PREREG = ROOT / PREREG_RELATIVE
V1_STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CANDIDATE_MODULE = ROOT / "research/chinext_v1/strategy/chinext_v2_candidate.py"
ENGINE = ROOT / "research/chinext_v1/scripts/run_chinext_v1_smoke.py"
RUNNER = Path(__file__).resolve()
V1_SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_extended_replay_summary.json"
DECOMPOSITION = (
    ROOT / "research/chinext_v1/reports/chinext_v1_extended_failure_decomposition.json"
)
HYPOTHESIS_LEDGER = (
    ROOT / "research/chinext_v1/specs/chinext_v2_failure_hypothesis_ledger.json"
)
MARKET = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")


class V2ResearchError(RuntimeError):
    """Raised when a V2 attempt would violate its frozen research contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def candidate_identity(policy_name: str) -> str:
    payload = {
        "candidate_module_sha256": sha256_file(CANDIDATE_MODULE),
        "engine_sha256": sha256_file(ENGINE),
        "parent_v1_strategy_sha256": PARENT_V1_STRATEGY_SHA256,
        "policy": policy_for(policy_name).to_dict(),
        "semantic_delta": "ONE_POST_MINVOL_PRE_RANK_RS_ADMISSION_CONDITION",
    }
    return hashlib.sha256(extended.canonical_bytes(payload)).hexdigest()


def load_preregistered_attempt(attempt_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    committed = subprocess.run(
        ["git", "show", f"HEAD:{PREREG_RELATIVE.as_posix()}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if committed != PREREG.read_bytes():
        raise V2ResearchError("V2 attempt preregistration differs from committed bytes")
    prereg = json.loads(committed)
    if prereg["research_period"] != [START.isoformat(), END.isoformat()]:
        raise V2ResearchError("V2 research period is not exact 2018-2021")
    if prereg["recent_period_firewall"]["used_for_candidate_selection"] != "NO":
        raise V2ResearchError("2022-2025 research firewall is not active")
    attempts = {row["ATTEMPT_ID"]: row for row in prereg["attempts"]}
    if attempt_id not in attempts:
        raise V2ResearchError(f"attempt is not preregistered: {attempt_id}")
    attempt = attempts[attempt_id]
    if attempt["RESULT_STATUS"] != "PREREGISTERED_NOT_RUN":
        raise V2ResearchError("attempt is not in preregistered-not-run state")
    bindings = {
        "candidate_module": CANDIDATE_MODULE,
        "engine": ENGINE,
        "failure_decomposition": DECOMPOSITION,
        "hypothesis_ledger": HYPOTHESIS_LEDGER,
        "runner": RUNNER,
        "v1_extended_result": V1_SUMMARY,
        "v1_strategy": V1_STRATEGY,
    }
    for name, path in bindings.items():
        if sha256_file(path) != prereg["frozen_bindings"][f"{name}_sha256"]:
            raise V2ResearchError(f"preregistered file hash mismatch: {name}")
    if sha256_file(V1_STRATEGY) != PARENT_V1_STRATEGY_SHA256:
        raise V2ResearchError("frozen V1 strategy changed")
    if candidate_identity(attempt["CANDIDATE_POLICY"]) != attempt["STRATEGY_SHA"]:
        raise V2ResearchError("candidate strategy identity mismatch")
    return prereg, attempt


def v1_top20_identities() -> set[tuple[str, str]]:
    payload = json.loads(DECOMPOSITION.read_text(encoding="utf-8"))
    return {
        (str(row["symbol"]), str(row["entry_signal_date"]))
        for row in payload["right_tail"]["top20"]
    }


def build_result(
    engine_summary_path: Path,
    prepared: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    summary = json.loads(engine_summary_path.read_text(encoding="utf-8"))
    executions = read_jsonl(Path(summary["audit"]["execution_ledger"]))
    nav = read_jsonl(Path(summary["audit"]["daily_nav"]))
    trips = reconstruct_round_trips(executions)
    if len(nav) != 973 or nav[0]["trade_date"] != START.isoformat() or nav[-1][
        "trade_date"
    ] != END.isoformat():
        raise V2ResearchError("candidate NAV period violates the frozen 2018-2021 range")
    if any("2022" <= str(row["trade_date"])[:4] <= "2025" for row in nav):
        raise V2ResearchError("2022-2025 data reached candidate selection")
    same_day_fills = sum(
        row.get("status") == "FILLED" and row["signal_date"] == row["execution_date"]
        for row in executions
    )
    if same_day_fills or summary["audit"]["stale_held_valuation_count"]:
        raise V2ResearchError("candidate violated execution or valuation causality")
    portfolio = dict(summary["portfolio"])
    portfolio.update(performance_extensions(nav))
    tail = concentration(trips, float(portfolio["total_return"]))
    years = extended.annual_metrics(nav, trips)
    candidate_trip_ids = {
        (str(row["symbol"]), str(row["entry_signal_date"])) for row in trips
    }
    top20_retained = len(candidate_trip_ids & v1_top20_identities())
    result = {
        "ATTEMPT_ID": attempt["ATTEMPT_ID"],
        "CANDIDATE_POLICY": attempt["CANDIDATE_POLICY"],
        "HYPOTHESIS_ID": attempt["HYPOTHESIS_ID"],
        "RESULT_STATUS": "COMPLETED",
        "STRATEGY_SHA": attempt["STRATEGY_SHA"],
        "authorization": {
            "candidate_period": [START.isoformat(), END.isoformat()],
            "formal_v1_replay_executions": 0,
            "sample_status": "IN_SAMPLE_MECHANISM_RESEARCH",
            "used_2022_2025_for_v2_selection": "NO",
        },
        "audit": {
            "candidate_module_sha256": sha256_file(CANDIDATE_MODULE),
            "daily_nav_sha256": sha256_file(Path(summary["audit"]["daily_nav"])),
            "engine_sha256": sha256_file(ENGINE),
            "event_ledger_sha256": sha256_file(Path(summary["audit"]["event_ledger"])),
            "execution_ledger_sha256": sha256_file(
                Path(summary["audit"]["execution_ledger"])
            ),
            "input_manifest_sha256": prepared["canonical_sha256"],
            "runner_sha256": sha256_file(RUNNER),
            "same_day_fill_count": same_day_fills,
            "stale_held_valuation_count": summary["audit"][
                "stale_held_valuation_count"
            ],
        },
        "complexity": attempt["COMPLEXITY_DELTA"],
        "metrics": {
            "MAX_DRAWDOWN": portfolio["max_drawdown"],
            "MEAN_TRADE": portfolio["average_trade_return"],
            "MEDIAN_TRADE": portfolio["median_trade_return"],
            "RETURN_EX_BEST20": tail["return_ex_best20"],
            "TOP20_PNL_CONCENTRATION": tail[
                "top20_positive_pnl_concentration"
            ],
            "TOTAL_RETURN": portfolio["total_return"],
            "TRADES": len(trips),
            "V1_TOP20_ENTRY_IDENTITY_RETAINED": top20_retained,
            "WIN_RATE": portfolio["win_rate"],
            "year_returns": {year: row["return"] for year, row in years.items()},
        },
        "policy": summary["v2_candidate"],
    }
    first = extended.canonical_bytes(result)
    second = extended.canonical_bytes(result)
    if first != second:
        raise V2ResearchError("candidate result serialization is not deterministic")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt-id")
    parser.add_argument("--identity-only", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    cli = parse_args()
    if cli.identity_only:
        policy_names = ("V2_R120_MEDIAN", "V2_ALL_HORIZON_MEDIAN")
        print(
            json.dumps(
                {name: candidate_identity(name) for name in sorted(policy_names)},
                sort_keys=True,
            )
        )
        return 0
    if not cli.attempt_id or cli.output_dir is None:
        raise V2ResearchError("--attempt-id and --output-dir are required")
    _, attempt = load_preregistered_attempt(cli.attempt_id)
    cli.output_dir.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="chinext-v2-input-") as temporary:
        input_root = Path(temporary)
        prepared = extended.materialize_transient_inputs(input_root)
        frozen_v1 = json.loads(V1_SUMMARY.read_text(encoding="utf-8"))
        expected_input = frozen_v1["formal_replay"]["input_manifest"]["canonical_sha256"]
        if prepared["canonical_sha256"] != expected_input:
            raise V2ResearchError("candidate input differs from frozen V1 formal input")
        engine_summary = cli.output_dir / "engine_summary.json"
        args = argparse.Namespace(
            start=START,
            end=END,
            sample_size=10_000,
            full_survivor=True,
            initial_cash=INITIAL_CASH,
            pit_membership=input_root / "daily_membership.parquet",
            daily_root=input_root,
            market=MARKET,
            calendar=CALENDAR,
            summary=engine_summary,
            report=cli.output_dir / "engine_report.md",
            output_dir=cli.output_dir,
            warmup_start=WARMUP_START,
            ablation_arm=attempt["CANDIDATE_POLICY"],
        )
        run_engine(args)
        result = build_result(engine_summary, prepared, attempt)
        extended.gate_c.atomic_write(
            cli.output_dir / "attempt_result.json", extended.canonical_bytes(result)
        )
    print(
        json.dumps(
            {
                "attempt_id": result["ATTEMPT_ID"],
                "strategy_sha": result["STRATEGY_SHA"],
                **result["metrics"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
