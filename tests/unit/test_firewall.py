import ast
from pathlib import Path


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
            assert not any(name == root or name.startswith(root + ".") for name in names for root in forbidden_imports), path
