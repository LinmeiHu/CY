#!/usr/bin/env python3
"""Run the resumable CY-035 year chains under an external process supervisor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path("/Users/linmei/Documents/CY/.venv/bin/python")
EXTERNAL_ROOT = Path("/Volumes/quant/CY/data")
OUTPUT_ROOT = (
    EXTERNAL_ROOT
    / "staging/CY-035-MAIN-CHINEXT-EXACT-CHIP-2018-20260904-V13"
)
STAGE_ROOT = (
    EXTERNAL_ROOT
    / "staging/CY-035-MAIN-CHINEXT-EXACT-CHIP-2018-20260904-V13-stages"
)
JOB_ROOT = EXTERNAL_ROOT / "jobs/CY-035-MAIN-CHINEXT-EXACT-CHIP-2018-20260904-V13"
LOCAL_JOB_ROOT = Path(
    "/Users/linmei/Documents/CY/data/job_logs/"
    "CY-035-MAIN-CHINEXT-EXACT-CHIP-2018-20260904-V13"
)
DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1/daily"
)
MINUTE_ROOT = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars"
)
CY026_2023 = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-026-CURRENT-EXACT-CHIP-2023-20260824-V1/year=2023"
)
CY022_DELTA = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-022-BAOSTOCK-MARKET-DELTA-20260813-20260824-V1/raw_5m.parquet"
)
CY031_DELTA = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-031-SINA-MARKET-DELTA-20260825-20260904-V1/raw_5m.parquet"
)

_child: subprocess.Popen[bytes] | None = None
_status: dict[str, Any] = {}
_status_path: Path | None = None
_events_path: Path | None = None


def _now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _write_status(**updates: Any) -> None:
    if _status_path is None:
        return
    _status.update(updates, updated_at=_now())
    temporary = _status_path.with_suffix(".tmp.json")
    temporary.write_text(
        json.dumps(_status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(_status_path)


def _event(event: str, **details: Any) -> None:
    record = {"at": _now(), "event": event, "pid": os.getpid(), **details}
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if _events_path is not None:
        try:
            with _events_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as error:
            print(
                json.dumps(
                    {
                        "at": _now(),
                        "event": "event_log_write_failed",
                        "error": repr(error),
                        "original_event": event,
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )


def _handle_signal(signum: int, _frame: object) -> None:
    signal_name = signal.Signals(signum).name
    _event("signal_received", signal=signal_name, current_step=_status.get("current_step"))
    try:
        _write_status(state="SIGNALLED", signal=signal_name, exit_code=128 + signum)
    except OSError:
        pass
    if _child is not None and _child.poll() is None:
        try:
            os.killpg(_child.pid, signum)
        except ProcessLookupError:
            pass
    raise SystemExit(128 + signum)


def _require_inputs(paths: list[Path]) -> None:
    if not Path("/Volumes/quant").is_mount():
        raise RuntimeError("external volume /Volumes/quant is not mounted")
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"required inputs are missing: {missing}")


def _remove_incomplete_files(year: int) -> int:
    output = OUTPUT_ROOT / f"year={year}"
    removed = 0
    if output.is_dir():
        for path in output.rglob("*.tmp.parquet"):
            path.unlink()
            removed += 1
    _event("incomplete_files_removed", year=year, count=removed)
    return removed


def _run(command: list[str], *, step: str) -> None:
    global _child
    _write_status(state="RUNNING", current_step=step, command=command)
    _event("step_started", step=step, command=command)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    child_log_path = LOCAL_JOB_ROOT / f"{_status['chain']}-{step}.log"
    with child_log_path.open("ab", buffering=0) as child_log:
        child_log.write(
            ("\n" + json.dumps(
                {"at": _now(), "event": "child_started", "command": command},
                ensure_ascii=False,
            ) + "\n").encode("utf-8")
        )
        _child = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=environment,
            start_new_session=True,
            stdout=child_log,
            stderr=subprocess.STDOUT,
        )
        return_code = _child.wait()
    _child = None
    _event("step_exited", step=step, exit_code=return_code)
    _write_status(last_step=step, last_exit_code=return_code)
    if return_code != 0:
        raise RuntimeError(f"{step} exited with code {return_code}")


def _build_command(
    year: int,
    *,
    workers: int,
    resume_from: Path | None = None,
    end_date: str | None = None,
    delta_files: tuple[Path, ...] = (),
) -> list[str]:
    command = [
        str(PYTHON),
        "scripts/build_real_chip_year.py",
        "--year",
        str(year),
        "--warmup-start",
        "2018",
        "--workers",
        str(workers),
        "--buckets",
        "10",
        "--symbols-per-task",
        "24",
        "--memory-per-worker-gb",
        "1.5",
        "--daily-root",
        str(DAILY_ROOT),
        "--minute-root",
        str(MINUTE_ROOT),
        "--stage-root",
        str(STAGE_ROOT / f"year={year}"),
        "--output",
        str(OUTPUT_ROOT / f"year={year}"),
    ]
    if resume_from is not None:
        command.extend(("--resume-from", str(resume_from)))
    if end_date is not None:
        command.extend(("--end-date", end_date))
    for delta_file in delta_files:
        command.extend(("--baostock-delta-file", str(delta_file)))
    return command


def _validate_and_clean(year: int) -> dict[str, Any]:
    summary_path = OUTPUT_ROOT / f"year={year}/summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    required = {
        "status": summary.get("status"),
        "coverage": summary.get("coverage"),
        "rows": summary.get("rows"),
        "max_mass_error": summary.get("max_mass_error"),
        "max_same_day_resale": summary.get("max_same_day_resale"),
        "lineage_pass": summary.get("lineage_pass"),
    }
    if not (
        required["status"] == "PASS"
        and float(required["coverage"]) >= 0.95
        and required["max_mass_error"] == 0
        and required["max_same_day_resale"] == 0
        and required["lineage_pass"] is True
    ):
        raise RuntimeError(f"year {year} validation failed: {required}")
    summary_sha256 = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    stage = STAGE_ROOT / f"year={year}"
    if stage.is_dir():
        import shutil

        shutil.rmtree(stage)
    result = {**required, "summary_sha256": summary_sha256, "stage_removed": True}
    _event("year_validated", year=year, **result)
    return result


def _run_year(
    year: int,
    *,
    workers: int,
    resume_from: Path | None = None,
    end_date: str | None = None,
    delta_files: tuple[Path, ...] = (),
) -> dict[str, Any]:
    _require_inputs(
        [
            EXTERNAL_ROOT,
            DAILY_ROOT,
            MINUTE_ROOT,
            *([] if resume_from is None else [resume_from]),
            *delta_files,
        ]
    )
    _remove_incomplete_files(year)
    _run(
        _build_command(
            year,
            workers=workers,
            resume_from=resume_from,
            end_date=end_date,
            delta_files=delta_files,
        ),
        step=f"build_year_{year}",
    )
    return _validate_and_clean(year)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chain", choices=("history", "current"), required=True)
    args = parser.parse_args()

    global _status_path, _events_path
    JOB_ROOT.mkdir(parents=True, exist_ok=True)
    LOCAL_JOB_ROOT.mkdir(parents=True, exist_ok=True)
    _status_path = JOB_ROOT / f"{args.chain}-status.json"
    _events_path = JOB_ROOT / f"{args.chain}-events.jsonl"
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_signal)

    _status.clear()
    _status.update(
        chain=args.chain,
        pid=os.getpid(),
        state="STARTING",
        started_at=_now(),
        completed_years=[],
    )
    _write_status()
    _event("chain_started", chain=args.chain)

    try:
        if args.chain == "history":
            years = [
                (2018, 4, None, None, ()),
                (2019, 4, OUTPUT_ROOT / "year=2018", None, ()),
                (2020, 4, OUTPUT_ROOT / "year=2019", None, ()),
                (2021, 4, OUTPUT_ROOT / "year=2020", None, ()),
                (2022, 4, OUTPUT_ROOT / "year=2021", None, ()),
                (2023, 4, OUTPUT_ROOT / "year=2022", None, ()),
            ]
        else:
            years = [
                (2024, 10, CY026_2023, None, ()),
                (2025, 10, OUTPUT_ROOT / "year=2024", None, ()),
                (
                    2026,
                    10,
                    OUTPUT_ROOT / "year=2025",
                    "2026-09-04",
                    (CY022_DELTA, CY031_DELTA),
                ),
            ]
        for year, workers, resume_from, end_date, delta_files in years:
            summary_path = OUTPUT_ROOT / f"year={year}/summary.json"
            if summary_path.is_file():
                try:
                    result = _validate_and_clean(year)
                    _event("existing_year_reused", year=year)
                except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
                    _event("existing_year_rejected", year=year, error=repr(error))
                    result = _run_year(
                        year,
                        workers=workers,
                        resume_from=resume_from,
                        end_date=end_date,
                        delta_files=delta_files,
                    )
            else:
                result = _run_year(
                    year,
                    workers=workers,
                    resume_from=resume_from,
                    end_date=end_date,
                    delta_files=delta_files,
                )
            completed = [*_status.get("completed_years", []), {"year": year, **result}]
            _write_status(completed_years=completed)
    except Exception as error:
        _event(
            "chain_failed",
            error=repr(error),
            traceback=traceback.format_exc(),
            current_step=_status.get("current_step"),
        )
        _write_status(state="FAILED", error=repr(error), finished_at=_now(), exit_code=1)
        return 1

    _event("chain_completed", chain=args.chain)
    _write_status(
        state="COMPLETE",
        current_step=None,
        command=None,
        finished_at=_now(),
        exit_code=0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
