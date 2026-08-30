from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
REPORT = WORK / "FINAL_REPORT.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_final_report_contains_required_evidence_classes_and_answers() -> None:
    text = REPORT.read_text(encoding="utf-8")
    for heading in (
        "## FACT",
        "## EVIDENCE",
        "## INTERPRETATION",
        "## HYPOTHESIS",
        "## FAILED HYPOTHESIS",
        "## STRATEGY CANDIDATE",
        "## UNRESOLVED",
        "## Final answers to the ten required questions",
    ):
        assert heading in text
    final_answers = text.split(
        "## Final answers to the ten required questions", maxsplit=1
    )[1].split("## Reproducibility and artifact map", maxsplit=1)[0]
    answers = re.findall(r"^### (\d+)\.", final_answers, flags=re.MULTILINE)
    assert answers == [str(number) for number in range(1, 11)]
    assert "Keep frozen CHINEXT V1 unchanged" in text
    assert "bounded PIT-B" in text
    assert "not strict archival PIT-A" in text


def test_final_report_key_hashes_match_artifacts() -> None:
    text = REPORT.read_text(encoding="utf-8")
    paths = [
        ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py",
        WORK / "artifacts/daily_regime_features.parquet",
        WORK / "experiments/EXP-P7-003_spec.json",
        WORK / "artifacts/v1r_candidate_results.json",
        WORK / "artifacts/v1r_candidate_ledger_manifest.json",
        WORK / "artifacts/v1r_robustness_falsification.json",
        WORK / "artifacts/v1r_rolling_metrics.csv",
        WORK / "artifacts/v1r_temporal_metrics.csv",
    ]
    for path in paths:
        assert sha256(path) in text
