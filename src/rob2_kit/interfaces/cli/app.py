"""Project-local Harness bootstrap and diagnostics CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from rob2_kit.interfaces.harness import (
    bootstrap_project,
    doctor_project,
    rollback_project,
    uninstall_project,
    upgrade_project,
)

app = typer.Typer(no_args_is_help=True)

_LifecycleOperation = Callable[..., dict[str, Any]]


def _run_lifecycle(operation: _LifecycleOperation, project_root: Path, apply: bool) -> None:
    try:
        result = operation(project_root, apply=apply)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("bootstrap")
def bootstrap(
    project_root: Path = typer.Argument(Path(".")),
    unlocked: bool = typer.Option(
        False,
        "--unlocked",
        help=(
            "Wire directly to the shared release runtime instead of installing a "
            "project-local .rob2/runtime copy. From a source checkout, wires "
            "directly to that checkout instead of the published-registry "
            "launcher -- the supported way to bootstrap against local, "
            "unpublished rob2-kit source."
        ),
    ),
) -> None:
    """Install the locked Codex and Claude project-local Harness adapters."""

    try:
        result = bootstrap_project(project_root, mode="unlocked" if unlocked else "locked")
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("doctor")
def doctor(project_root: Path = typer.Argument(Path("."))) -> None:
    result = doctor_project(project_root)
    typer.echo(json.dumps(result, sort_keys=True))


@app.command("upgrade")
def upgrade(
    project_root: Path = typer.Argument(Path(".")),
    apply: bool = typer.Option(False, "--apply", help="Apply the previewed transaction."),
) -> None:
    """Preview, then explicitly apply a transactional locked-release upgrade."""

    _run_lifecycle(upgrade_project, project_root, apply)


@app.command("rollback")
def rollback(
    project_root: Path = typer.Argument(Path(".")),
    apply: bool = typer.Option(False, "--apply", help="Apply the previewed rollback."),
) -> None:
    """Preview, then restore the last complete release transaction."""

    _run_lifecycle(rollback_project, project_root, apply)


@app.command("uninstall")
def uninstall(
    project_root: Path = typer.Argument(Path(".")),
    apply: bool = typer.Option(False, "--apply", help="Apply the previewed uninstall."),
) -> None:
    """Preview, then remove only manifest-owned generated files."""

    _run_lifecycle(uninstall_project, project_root, apply)


def main() -> None:
    app()
