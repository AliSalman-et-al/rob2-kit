"""Project-local Harness bootstrap and diagnostics CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rob2_kit.interfaces.harness import (
    bootstrap_project,
    doctor_project,
    rollback_project,
    uninstall_project,
    upgrade_project,
)

app = typer.Typer(no_args_is_help=True)


@app.command("bootstrap")
def bootstrap(project_root: Path = typer.Argument(Path("."))) -> None:
    """Install the locked Codex and Claude project-local Harness adapters."""

    try:
        result = bootstrap_project(project_root)
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

    try:
        typer.echo(json.dumps(upgrade_project(project_root, apply=apply), sort_keys=True))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@app.command("rollback")
def rollback(
    project_root: Path = typer.Argument(Path(".")),
    apply: bool = typer.Option(False, "--apply", help="Apply the previewed rollback."),
) -> None:
    """Preview, then restore the last complete release transaction."""

    try:
        typer.echo(json.dumps(rollback_project(project_root, apply=apply), sort_keys=True))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


@app.command("uninstall")
def uninstall(
    project_root: Path = typer.Argument(Path(".")),
    apply: bool = typer.Option(False, "--apply", help="Apply the previewed uninstall."),
) -> None:
    """Preview, then remove only manifest-owned generated files."""

    try:
        typer.echo(json.dumps(uninstall_project(project_root, apply=apply), sort_keys=True))
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def main() -> None:
    app()
