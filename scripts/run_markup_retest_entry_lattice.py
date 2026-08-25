#!/usr/bin/env python3
"""Run the complete 81-entry MARKUP_RETEST development frequency gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cyq_game.strategy.markup_retest import MarkupRetestConfig, StrategyStage
from cyq_game.strategy.orchestration import prepare_development_research
from cyq_game.strategy.research import (
    persist_entry_frequency_trials,
    screen_entry_lattice_files,
    shortlist_entry_candidates,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--no-reuse", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MarkupRetestConfig.load(args.config)
    prepared = prepare_development_research(
        args.config,
        StrategyStage.DEVELOPMENT,
        reuse=not args.no_reuse,
        threads=args.threads,
    )
    if prepared.coverage_gate != "PASS":
        raise RuntimeError("development panel failed the configured coverage gate")

    panel_path = Path(str(prepared.panel["path"]))
    panel_files = tuple(sorted(panel_path.rglob("*.parquet")))
    panel_snapshot_id = str(prepared.panel["panel_snapshot_id"])
    lattice = screen_entry_lattice_files(
        panel_files,
        config,
        panel_snapshot_id=panel_snapshot_id,
        threads=args.threads,
        collect_signals=False,
    )
    boundary = config.stage(StrategyStage.DEVELOPMENT)
    evaluation_years = tuple(range(boundary.start.year, boundary.end.year + 1))
    shortlist = shortlist_entry_candidates(
        lattice,
        config,
        evaluation_years=evaluation_years,
    )
    ledger = persist_entry_frequency_trials(
        shortlist,
        config,
        panel_snapshot_id=panel_snapshot_id,
    )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": shortlist.status,
        "strategy_version": config.strategy_version,
        "config_path": str(config.path),
        "config_sha256": config.sha256,
        "stage": StrategyStage.DEVELOPMENT.value,
        "evaluation_start": boundary.start.isoformat(),
        "evaluation_end": boundary.end.isoformat(),
        "evaluation_years": list(evaluation_years),
        "panel_snapshot_id": panel_snapshot_id,
        "panel_manifest": str(prepared.panel["manifest_path"]),
        "signal_manifest": str(prepared.signals["manifest_path"]),
        "label_manifest": str(prepared.labels["manifest_path"]),
        "input_rows": lattice.input_rows,
        "evaluation_rows": lattice.evaluation_rows,
        "panel_passes": lattice.panel_passes,
        "parameter_trials": len(shortlist.trials),
        "candidate_parameter_ids": [
            item.parameter_id for item in shortlist.candidates
        ],
        "candidate_parameters": [
            item.canonical() for item in shortlist.candidates
        ],
        "reason_codes": list(shortlist.reason_codes),
        "trials": [
            {
                "parameter_id": trial.parameter_id,
                "parameters": trial.parameters.canonical(),
                "annual_signal_counts": {
                    str(year): count
                    for year, count in trial.annual_signal_counts.items()
                },
                "mean_annual_signals": trial.mean_annual_signals,
                "worst_target_deviation": trial.worst_target_deviation,
                "adjacent_frequency_passes": trial.adjacent_frequency_passes,
                "frequency_gate": trial.frequency_gate,
                "reason_codes": list(trial.reason_codes),
            }
            for trial in shortlist.trials
        ],
        "trial_ledger": str(ledger.ledger_path),
        "trial_run_id": ledger.run_id,
        "ledger_events": ledger.appended + ledger.existing,
    }
    payload["entry_lattice_snapshot_id"] = "entry-lattice-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    target = (
        config.outputs.validation_root
        / StrategyStage.DEVELOPMENT.value
        / config.sha256[:12]
        / "entry_frequency.json"
    )
    _write_immutable_json(target, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if shortlist.status == "PASS" else 2


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"entry lattice output already exists and differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temp.write_text(rendered, encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
