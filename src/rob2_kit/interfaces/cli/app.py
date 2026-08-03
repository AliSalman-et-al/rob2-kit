"""Project-local Harness bootstrap and diagnostics CLI."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rob2_kit.interfaces.harness import bootstrap_project, doctor_project

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


def main() -> None:
    app()
