"""JASON CLI entrypoint — typer app exposing all subcommands.

Most subcommands are placeholders in Phase 0; they will be wired up in their
respective phases. `jason db init` is implemented because the DuckDB schema
ships in Phase 0.
"""

from __future__ import annotations

from pathlib import Path

import typer

from jason import __version__
from jason.config import get_settings

app = typer.Typer(
    name="jason",
    help="JASON — YouTube growth engine for @babygiulybaby.",
    no_args_is_help=True,
    add_completion=False,
)

db_app = typer.Typer(help="Manage the local DuckDB warehouse.", no_args_is_help=True)
ingest_app = typer.Typer(help="Pull data from YouTube + TMDb (Phase 1).", no_args_is_help=True)
features_app = typer.Typer(help="Compute outlier multipliers, embeddings, topics (Phase 2).", no_args_is_help=True)
model_app = typer.Typer(help="Train and score the title-multiplier regressor (Phase 3).", no_args_is_help=True)

app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(features_app, name="features")
app.add_typer(model_app, name="model")


@app.command("version")
def version() -> None:
    """Show JASON version."""
    typer.echo(f"jason {__version__}")


# --- db ----------------------------------------------------------------------


@db_app.command("init")
def db_init(
    migration: Path = typer.Option(
        Path("migrations/001_init.sql"),
        "--migration",
        "-m",
        help="Path to the SQL migration file.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print SQL without applying."),
) -> None:
    """Apply the initial DuckDB schema."""
    import duckdb

    settings = get_settings()
    sql = migration.read_text(encoding="utf-8")

    if dry_run:
        typer.echo(f"[dry-run] would apply {migration} to {settings.duckdb_path}")
        typer.echo(sql)
        raise typer.Exit(0)

    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(settings.duckdb_path)) as con:
        con.execute(sql)

    typer.echo(f"applied {migration} -> {settings.duckdb_path}")


# --- ingest (Phase 1 placeholders) ------------------------------------------


@ingest_app.command("channels")
def ingest_channels(
    ids: str = typer.Option(..., "--ids", help="Comma-separated channel IDs (UC...)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Ingest channels + their videos by channel ID."""
    raise typer.Exit(_not_yet("ingest channels", "Phase 1"))


@ingest_app.command("neighbors")
def ingest_neighbors(
    file: Path = typer.Option(..., "--file", help="File with one @handle or UC... per line."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Batch-ingest neighbor channels from a list."""
    raise typer.Exit(_not_yet("ingest neighbors", "Phase 1"))


# --- features (Phase 2) ------------------------------------------------------


@features_app.command("compute")
def features_compute(
    all_features: bool = typer.Option(False, "--all", help="Compute every feature."),
) -> None:
    """Compute multipliers, title features, embeddings, topics."""
    raise typer.Exit(_not_yet("features compute", "Phase 2"))


# --- model (Phase 3) ---------------------------------------------------------


@model_app.command("train")
def model_train() -> None:
    """Train the LightGBM multiplier regressor."""
    raise typer.Exit(_not_yet("model train", "Phase 3"))


@model_app.command("score")
def model_score(
    title: str = typer.Option(..., "--title"),
    channel: str = typer.Option(..., "--channel"),
) -> None:
    """Score a candidate title for a given channel."""
    raise typer.Exit(_not_yet("model score", "Phase 3"))


# --- suggest (Phase 4) -------------------------------------------------------


@app.command("suggest")
def suggest(
    transcript: Path = typer.Option(..., "--transcript", help="Path to transcript text/JSON."),
) -> None:
    """Generate 10 candidate titles, return top 3 ranked by the model."""
    raise typer.Exit(_not_yet("suggest", "Phase 4"))


# --- helpers -----------------------------------------------------------------


def _not_yet(cmd: str, phase: str) -> int:
    typer.secho(
        f"[{cmd}] Jason hasn't sharpened his machete for this yet — comes online in {phase}.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    return 1


if __name__ == "__main__":
    app()
