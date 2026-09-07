import ast
from pathlib import Path

from five_strategy_bundle import reproduce

ROOT = Path(__file__).resolve().parents[2]


def test_production_dependency_firewall():
    files = [*ROOT.joinpath("src").rglob("*.py"), ROOT / "reproduce.py"]
    forbidden_text = ("/Users/", "/Volumes/", "git show", "git cat-file", "sys.path")
    forbidden_imports = ("research", "market_behavior_os_v2", "supermind_v6")
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not any(token in text for token in forbidden_text), path
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(
                name == root or name.startswith(root + ".")
                for name in names
                for root in forbidden_imports
            ), path


def test_production_does_not_require_golden(monkeypatch, tmp_path: Path) -> None:
    sentinel_inputs = {"registered": tmp_path}
    monkeypatch.setattr(reproduce, "load_input_config", lambda _: sentinel_inputs)
    monkeypatch.setattr(
        reproduce,
        "run_mcb",
        lambda inputs, output: {"strategy": "MCB", "status": "FULL_END_TO_END_REPRODUCIBLE"},
    )
    assert reproduce.main([
        "--strategy", "MCB",
        "--input-config", str(tmp_path / "registered.json"),
        "--output-root", str(tmp_path / "output"),
    ]) == 0
