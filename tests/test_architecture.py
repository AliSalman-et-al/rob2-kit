import ast
from pathlib import Path


def test_domain_and_application_do_not_import_host_frameworks() -> None:
    forbidden_roots = {"fastapi", "typer", "mcp", "codex", "claude"}
    package = Path(__file__).parents[1] / "src" / "rob2_kit"
    violations: list[str] = []
    for layer in ("domain", "application"):
        for path in (package / layer).glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.split(".", 1)[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = {node.module.split(".", 1)[0]}
                else:
                    continue
                if roots & forbidden_roots:
                    violations.append(str(path))
    assert not violations
