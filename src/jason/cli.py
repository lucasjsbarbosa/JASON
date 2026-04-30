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
snapshot_app = typer.Typer(help="Run periodic stats snapshots (Phase 1).", no_args_is_help=True)
features_app = typer.Typer(help="Compute outlier multipliers, embeddings, topics (Phase 2).", no_args_is_help=True)
model_app = typer.Typer(help="Train and score the title-multiplier regressor (Phase 3).", no_args_is_help=True)

app.add_typer(db_app, name="db")
app.add_typer(ingest_app, name="ingest")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(features_app, name="features")
app.add_typer(model_app, name="model")


@app.command("version")
def version() -> None:
    """Show JASON version."""
    typer.echo(f"jason {__version__}")


# --- db ----------------------------------------------------------------------


@db_app.command("init")
def db_init(
    migration: Path | None = typer.Option(
        None,
        "--migration",
        "-m",
        help="Apply a single migration file. Default: apply all .sql in migrations/ in name order.",
    ),
    migrations_dir: Path = typer.Option(
        Path("migrations"),
        "--migrations-dir",
        help="Directory containing migration files.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print files without applying."),
) -> None:
    """Apply DuckDB schema migrations (all in `migrations/` by default, in name order)."""
    import duckdb

    settings = get_settings()

    if migration is not None:
        files = [migration]
    else:
        files = sorted(migrations_dir.glob("*.sql"))
        if not files:
            typer.echo(f"no .sql files found in {migrations_dir}", err=True)
            raise typer.Exit(1)

    if dry_run:
        typer.echo(f"[dry-run] would apply {len(files)} migration(s) to {settings.duckdb_path}:")
        for f in files:
            typer.echo(f"  - {f}")
        raise typer.Exit(0)

    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(settings.duckdb_path)) as con:
        for f in files:
            con.execute(f.read_text(encoding="utf-8"))
            typer.echo(f"applied {f}")

    typer.echo(f"-> {settings.duckdb_path}")


# --- ingest (Phase 1 placeholders) ------------------------------------------


@ingest_app.command("channels")
def ingest_channels(
    ids: str = typer.Option(..., "--ids", help="Comma-separated channel IDs (UC...)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Ingest channels + their videos by channel ID (writes initial snapshot)."""
    from jason.ingestion.youtube_data import ingest_channel

    channel_ids = [s.strip() for s in ids.split(",") if s.strip()]
    if not channel_ids:
        typer.echo("no channel ids provided", err=True)
        raise typer.Exit(1)

    if dry_run:
        typer.echo(f"[dry-run] would ingest {len(channel_ids)} channel(s):")
        for cid in channel_ids:
            typer.echo(f"  - {cid}")
        raise typer.Exit(0)

    for cid in channel_ids:
        try:
            result = ingest_channel(cid)
        except Exception as exc:
            typer.secho(f"  {cid} FAILED: {exc}", fg=typer.colors.RED, err=True)
            continue
        typer.secho(
            f"  {cid}: {result['video_count']} videos, {result['snapshot_count']} snapshots "
            f"-> {result['raw_dump_path']}",
            fg=typer.colors.GREEN,
        )


@ingest_app.command("neighbors")
def ingest_neighbors(
    file: Path = typer.Option(..., "--file", help="File with one @handle or UC... per line."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Batch-ingest neighbor channels from a list."""
    raise typer.Exit(_not_yet("ingest neighbors", "Phase 1"))


@ingest_app.command("resolve-handles")
def ingest_resolve_handles(
    file: Path = typer.Option(
        ..., "--file", "-f",
        help="Plain-text file with one @handle per line (# comments and blank lines OK).",
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Optional output file: 'handle UC...' lines for downstream ingest.",
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", help="Bypass cache and re-query the API.",
    ),
) -> None:
    """Resolve @handles to UC... channel IDs (cached in handle_cache)."""
    from jason.ingestion.handle_resolver import resolve_handles

    handles = [
        line.strip()
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not handles:
        typer.echo(f"no handles found in {file}", err=True)
        raise typer.Exit(1)

    typer.echo(f"resolving {len(handles)} handles...")
    results = resolve_handles(handles, force_refresh=force_refresh)

    found = sum(1 for v in results.values() if v)
    missing = len(results) - found

    for h, ch_id in results.items():
        marker = ch_id if ch_id else typer.style("NOT FOUND", fg=typer.colors.RED)
        typer.echo(f"  {h:30s} -> {marker}")

    typer.secho(
        f"\n{found} resolved, {missing} not found",
        fg=typer.colors.GREEN if missing == 0 else typer.colors.YELLOW,
    )

    if output:
        output.write_text(
            "\n".join(f"{h} {ch_id}" for h, ch_id in results.items() if ch_id) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote {output}")


# --- snapshot (Phase 1) ------------------------------------------------------


@snapshot_app.command("run")
def snapshot_run(
    channel: str | None = typer.Option(
        None, "--channel", "-c",
        help="Limit snapshot to a single channel (UC...). Default: all known videos.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="List how many videos would be hit."),
) -> None:
    """Append a fresh row to video_stats_snapshots for every known video."""
    import duckdb

    settings = get_settings()

    if dry_run:
        with duckdb.connect(str(settings.duckdb_path)) as con:
            if channel:
                count = con.execute(
                    "SELECT COUNT(*) FROM videos WHERE channel_id = ?", [channel]
                ).fetchone()[0]
            else:
                count = con.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        typer.echo(
            f"[dry-run] would snapshot {count} video(s)"
            + (f" for channel {channel}" if channel else "")
        )
        raise typer.Exit(0)

    from jason.ingestion.stats_snapshot import snapshot_all

    result = snapshot_all(channel_id=channel)
    typer.secho(
        f"snapshot done at {result['captured_at'].isoformat()}: "
        f"{result['snapshotted']}/{result['requested']} videos "
        f"({result['missing']} missing)",
        fg=typer.colors.GREEN if result["missing"] == 0 else typer.colors.YELLOW,
    )


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
