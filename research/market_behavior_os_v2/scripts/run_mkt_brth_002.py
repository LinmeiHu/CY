#!/usr/bin/env python3
"""Deterministic serial retry of the frozen MKT-BRTH-001 scientific design."""

from __future__ import annotations

import json
from pathlib import Path

import run_mkt_brth_001 as breadth


PROGRAM = Path(__file__).resolve().parents[1]
breadth.SPEC_PATH = PROGRAM / "experiments/MKT-BRTH-002_spec.json"
breadth.PANEL_PATH = PROGRAM / "artifacts/MKT-BRTH-002_breadth_panel.csv"
breadth.RESULT_PATH = PROGRAM / "artifacts/MKT-BRTH-002_result.json"
breadth.REPORT_PATH = PROGRAM / "reports/MKT-BRTH-002_breadth_representation_freeze.md"
breadth.DUCKDB_THREADS = 1


if __name__ == "__main__":
    final = breadth.run()
    print(json.dumps({
        "status": final["status"],
        "rows": final["population"]["rows"],
        "accepted_roles": final["minimal_panel"]["accepted_roles"],
        "excluded_roles": final["minimal_panel"]["excluded_roles"],
        "latent_components": final["latent_components"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
