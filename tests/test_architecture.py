import ast
from pathlib import Path

from rob2_kit.interfaces.cli.app import app


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


def test_lean_v1_keeps_interfaces_at_the_run_engine_boundary() -> None:
    """Only the Harness bootstrap and diagnostics remain as CLI capabilities."""

    command_names = {command.name for command in app.registered_commands}
    assert command_names == {"bootstrap", "doctor"}

    package = Path(__file__).parents[1] / "src" / "rob2_kit"
    assert not (package / "application" / "gateway.py").exists()
    assert not (package / "application" / "interfaces.py").exists()
    assert not any((package / "review").rglob("*.py"))

    violations: list[str] = []
    for layer in ("application", "domain"):
        for path in (package / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imports_interface = any(
                alias.name.startswith(("rob2_kit.interfaces", "rob2_kit.review"))
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            ) or any(
                (
                    node.module is not None
                    and node.module.startswith(("rob2_kit.interfaces", "rob2_kit.review"))
                )
                or (
                    node.module == "rob2_kit"
                    and any(alias.name in {"interfaces", "review"} for alias in node.names)
                )
                or (
                    node.level > 0
                    and any(alias.name in {"interfaces", "review"} for alias in node.names)
                )
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            )
            if imports_interface:
                violations.append(str(path))
    assert not violations
