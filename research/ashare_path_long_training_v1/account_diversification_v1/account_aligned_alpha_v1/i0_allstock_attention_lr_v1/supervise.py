#!/usr/bin/env python3
"""Wait for the resumable inner grid, then launch the frozen formal stage once."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
LOCK = HERE / "PIPELINE.lock"
STATE = HERE / "RUN_STATE.json"


def live(pid: int) -> bool:
    try:
        os.kill(pid, 0); return True
    except ProcessLookupError:
        return False


while True:
    if LOCK.exists() and LOCK.read_text().strip():
        pid = int(LOCK.read_text())
        if live(pid):
            time.sleep(60); continue
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if (HERE / "INNER_SELECTION.json").exists() and state.get("stage") == "P3_INNER_SELECTION_FROZEN":
        with (HERE / "FORMAL.log").open("a") as log:
            result = subprocess.run(["python", str(HERE / "formal.py")], cwd=REPO,
                                    env={**os.environ, "PYTHONPATH": "."}, stdout=log, stderr=subprocess.STDOUT)
        raise SystemExit(result.returncode)
    if state.get("status") == "BLOCKED_NEEDS_CODEX":
        raise SystemExit(2)
    with (HERE / "SUPERVISOR.log").open("a") as log:
        result = subprocess.run(["python", str(HERE / "run.py"), "inner-grid"], cwd=REPO,
                                env={**os.environ, "PYTHONPATH": "."}, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(result.returncode)
