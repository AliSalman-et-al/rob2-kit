"""Typer CLI over the host-neutral application gateway."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from rob2_kit.application.gateway import ApplicationGateway
from rob2_kit.reports.archives import verify_archive

app = typer.Typer(no_args_is_help=True)


@app.command()
def init(
    project_root: Path = typer.Argument(Path(".")),
    authorize: bool = typer.Option(False, "--authorize"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    result = ApplicationGateway().initialize_project(project_root, authorized=authorize)
    _emit(result.model_dump(mode="json"), json_output)


def _project_call(project_root: Path, tool_name: str, as_json: bool) -> None:
    gateway = ApplicationGateway()
    project_id = gateway.resume_project(project_root)
    result = gateway.call(tool_name, project_id)
    _emit(result.model_dump(mode="json"), as_json)


@app.command()
def doctor(project_root: Path = typer.Argument(Path("."))) -> None:
    result = ApplicationGateway().expert_command(project_root, "doctor")
    typer.echo(json.dumps(result, sort_keys=True))


@app.command()
def status(
    project_root: Path = typer.Argument(Path(".")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _project_call(project_root, "project_status", json_output)


@app.command(name="continue")
def continue_(
    project_root: Path = typer.Argument(Path(".")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _project_call(project_root, "continue_preparation", json_output)


@app.command()
def review(
    project_root: Path = typer.Argument(Path(".")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _project_call(project_root, "open_review", json_output)


@app.command()
def report(project_root: Path = typer.Argument(Path("."))) -> None:
    _expert(project_root, "report")


@app.command()
def export(project_root: Path = typer.Argument(Path("."))) -> None:
    _expert(project_root, "export")


@app.command()
def archive(
    project_root: Path = typer.Argument(Path(".")),
    kind: str = typer.Option("complete", "--kind"),
) -> None:
    _archive(project_root, kind)


@app.command()
def verify(target: Path = typer.Argument(Path("."))) -> None:
    if target.is_file():
        receipt = verify_archive(target.read_bytes())
        typer.echo(json.dumps(receipt.model_dump(mode="json"), sort_keys=True))
    else:
        _expert(target, "verify")


@app.command()
def events(project_root: Path = typer.Argument(Path("."))) -> None:
    _expert(project_root, "events")


@app.command()
def repair(project_root: Path = typer.Argument(Path("."))) -> None:
    _expert(project_root, "repair")


@app.command()
def mcp() -> None:
    from rob2_kit.interfaces.mcp.server import main as run_mcp

    run_mcp()


def _emit(value: dict[str, object], as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(value, sort_keys=True))
    else:
        typer.echo(f"{value['status']}: {value['ledger_cursor']}")


def _expert(project_root: Path, command: str) -> None:
    typer.echo(
        json.dumps(
            ApplicationGateway().expert_command(project_root, command),
            sort_keys=True,
        )
    )


def _archive(
    project_root: Path,
    kind: str,
) -> None:
    typer.echo(
        json.dumps(
            ApplicationGateway().expert_command(
                project_root,
                "archive",
                archive_kind=kind,
            ),
            sort_keys=True,
        )
    )


def main() -> None:
    app()
