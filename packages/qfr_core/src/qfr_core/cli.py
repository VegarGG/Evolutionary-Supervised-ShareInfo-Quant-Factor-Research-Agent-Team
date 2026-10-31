"""Operations CLI: `qfr logs search|tail|correlate|export|maintain` and the command groups
the installed zone packages contribute."""

import json
from datetime import UTC, datetime
from importlib.metadata import entry_points
from pathlib import Path

import typer

from qfr_core.config import RuntimeSettings, logging_config, mcp_config
from qfr_core.log_maintenance import maintain as maintain_logs
from qfr_core.log_reader import LogQuery, LogReader

app = typer.Typer(no_args_is_help=True)
logs_app = typer.Typer(no_args_is_help=True)
app.add_typer(logs_app, name="logs")

# Zone packages contribute command groups through the "qfr.commands" entry point group,
# so an image only offers the commands of the packages installed in it (for example,
# `qfr data` exists only where qfr-eval is installed).
for _plugin in sorted(entry_points(group="qfr.commands"), key=lambda e: e.name):
    app.add_typer(_plugin.load(), name=_plugin.name)


def reader() -> LogReader:
    settings = RuntimeSettings()
    return LogReader(
        settings.log_dir, logging_config(settings.config_dir), mcp_config(settings.config_dir)
    )


@logs_app.command("search")
def search(query: str = "{}") -> None:
    """Search using a JSON LogQuery with filters, correlation ids and pagination."""
    typer.echo(reader().search(LogQuery.model_validate_json(query)).model_dump_json())


@logs_app.command("tail")
def tail(service: str | None = None, n: int | None = None) -> None:
    typer.echo(reader().tail(service, n).model_dump_json())


@logs_app.command("correlate")
def correlate(identifier: str, id_kind: str, query: str = "{}") -> None:
    typer.echo(
        json.dumps(reader().correlate(identifier, id_kind, LogQuery.model_validate_json(query)))
    )


@logs_app.command("export")
def export(out: Path, query: str = "{}") -> None:
    """Write the lines matching a JSON LogQuery to OUT as gzip JSON lines."""
    if out.suffixes[-2:] != [".jsonl", ".gz"]:
        raise typer.BadParameter("the export file name must end in .jsonl.gz")
    typer.echo(json.dumps(reader().export(LogQuery.model_validate_json(query), out)))


@logs_app.command("maintain")
def maintain() -> None:
    """Compress and delete old day files now, as the nightly job does (LOG-04)."""
    settings = RuntimeSettings()
    report = maintain_logs(
        settings.log_dir, logging_config(settings.config_dir), datetime.now(UTC).date()
    )
    typer.echo(report.model_dump_json())


if __name__ == "__main__":
    app()
