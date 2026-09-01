from __future__ import annotations

from pathlib import Path


def test_failure_audit_preserves_development_only_saved_model_boundary() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts/run_ashare_tail_open_lgbm_v1_model_failure_audit.py"
    source = path.read_text(encoding="utf-8")
    assert "model.fit(" not in source
    assert "saved_model_diagnostic_scoring" in source
    assert "MODEL_TAIL_OVERFIT" in source
