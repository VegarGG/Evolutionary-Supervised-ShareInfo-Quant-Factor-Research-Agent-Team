"""Operations CLI. Later-phase operations fail explicitly until implemented."""

import json

import typer

from qfr_core.config import RuntimeSettings, logging_config, mcp_config
from qfr_core.log_reader import LogQuery, LogReader

app = typer.Typer(no_args_is_help=True)
logs_app = typer.Typer(no_args_is_help=True)
app.add_typer(logs_app, name="logs")


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


@app.command("setup")
def setup() -> None:
    typer.echo(
        json.dumps(
            {
                "status": "not_implemented_in_phase_0",
                "setup_complete": False,
                "next": (
                    "Pool setup is Phase 2; data ingest is Phase 1; provider probes are Phase 4."
                ),
                "provider_calls_made": 0,
                "default_factors": 0,
                "default_strategies": 0,
            }
        )
    )
    raise typer.Exit(2)


if __name__ == "__main__":
    app()
