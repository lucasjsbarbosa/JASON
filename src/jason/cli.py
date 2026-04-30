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


@ingest_app.command("tmdb-releases")
def ingest_tmdb_releases_cmd(
    window_past: int = typer.Option(
        365, "--window-past", help="Days behind today to start (default 365).",
    ),
    window_future: int = typer.Option(
        180, "--window-future", help="Days ahead of today to end (default 180).",
    ),
    region: str = typer.Option("BR", "--region", help="2-char ISO region (default BR)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show window without calling TMDb."),
) -> None:
    """Pull horror releases (theatrical|digital) from TMDb into horror_releases."""
    from datetime import UTC, datetime, timedelta

    today = datetime.now(UTC).date()
    gte = today - timedelta(days=window_past)
    lte = today + timedelta(days=window_future)

    if dry_run:
        typer.echo(f"[dry-run] would fetch TMDb horror releases for region={region}")
        typer.echo(f"           window: {gte} -> {lte} ({window_past + window_future} days)")
        raise typer.Exit(0)

    from jason.ingestion.tmdb import ingest_tmdb_releases

    result = ingest_tmdb_releases(
        window_past=window_past, window_future=window_future, region=region,
    )
    typer.secho(
        f"tmdb releases: {result['inserted']} new, {result['updated']} updated, "
        f"{result['skipped']} skipped (of {result['requested']} fetched)",
        fg=typer.colors.GREEN,
    )


@ingest_app.command("transcripts")
def ingest_transcripts(
    audio_dir: Path = typer.Option(
        ..., "--audio-dir", "-a",
        help="Directory containing {video_id}.{ext} audio files (.m4a/.mp3/.wav/etc).",
    ),
    channel: str | None = typer.Option(
        None, "--channel", "-c",
        help="Only transcribe videos from this channel (UC...).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count what would be transcribed."),
) -> None:
    """Transcribe audio files for known videos via faster-whisper (PT-BR)."""
    if dry_run:
        import duckdb

        from jason.ingestion.transcripts import _resolve_audio_for

        settings = get_settings()
        with duckdb.connect(str(settings.duckdb_path)) as con:
            sql = "SELECT id FROM videos"
            params: list = []
            if channel:
                sql += " WHERE channel_id = ?"
                params.append(channel)
            rows = con.execute(sql, params).fetchall()

        out_dir = settings.data_dir / "transcripts"
        with_audio = sum(1 for (vid,) in rows if _resolve_audio_for(vid, audio_dir))
        already_done = sum(1 for (vid,) in rows if (out_dir / f"{vid}.json").exists())
        typer.echo(
            f"[dry-run] {len(rows)} candidate video(s); "
            f"{with_audio} have audio in {audio_dir}; "
            f"{already_done} already transcribed"
        )
        raise typer.Exit(0)

    from jason.ingestion.transcripts import transcribe_pending

    result = transcribe_pending(audio_dir, channel_id=channel)
    typer.secho(
        f"transcripts: {result['transcribed']} done, "
        f"{result['skipped']} already done, "
        f"{result['no_audio']} missing audio "
        f"(of {result['requested']} candidates)",
        fg=typer.colors.GREEN,
    )


@ingest_app.command("thumbnails")
def ingest_thumbnails(
    channel: str | None = typer.Option(
        None, "--channel", "-c",
        help="Limit to a single channel (UC...). Default: all known videos.",
    ),
    force: bool = typer.Option(False, "--force", help="Re-download even if file exists."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count what would be fetched."),
) -> None:
    """Download maxres thumbnails for known videos to data/thumbnails/."""
    import duckdb

    settings = get_settings()

    if dry_run:
        with duckdb.connect(str(settings.duckdb_path)) as con:
            sql = "SELECT COUNT(*) FROM videos WHERE thumbnail_url IS NOT NULL"
            params = []
            if channel:
                sql += " AND channel_id = ?"
                params.append(channel)
            count = con.execute(sql, params).fetchone()[0]
        typer.echo(
            f"[dry-run] would consider {count} thumbnail(s)"
            + (f" for channel {channel}" if channel else "")
            + (" (force)" if force else " (skipping existing)")
        )
        raise typer.Exit(0)

    from jason.ingestion.thumbnails import download_all

    result = download_all(channel_id=channel, force=force)
    typer.secho(
        f"thumbnails: {result['downloaded']} downloaded, "
        f"{result['skipped']} skipped, {result['failed']} failed "
        f"(of {result['requested']} requested)",
        fg=typer.colors.GREEN if result["failed"] == 0 else typer.colors.YELLOW,
    )


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

    handles = []
    for raw in file.read_text(encoding="utf-8").splitlines():
        # Strip inline comments first (e.g. "@foo  # description"), then trim.
        stripped = raw.split("#", 1)[0].strip()
        if stripped:
            handles.append(stripped)
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


@features_app.command("title")
def features_title(
    channel: str | None = typer.Option(
        None, "--channel", "-c",
        help="Limit to one channel (UC...). Default: all videos.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Recompute even videos that already have features.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Count what would be computed."),
) -> None:
    """Compute title-level features (length, caps, niche keywords, etc.)."""
    import duckdb

    settings = get_settings()

    if dry_run:
        with duckdb.connect(str(settings.duckdb_path)) as con:
            sql = "SELECT COUNT(*) FROM videos v"
            params: list = []
            if not force:
                sql += " LEFT JOIN video_features f ON f.video_id = v.id WHERE f.video_id IS NULL"
            else:
                sql += " WHERE 1=1"
            if channel:
                sql += " AND v.channel_id = ?"
                params.append(channel)
            count = con.execute(sql, params).fetchone()[0]
        typer.echo(f"[dry-run] would compute features for {count} video(s)")
        raise typer.Exit(0)

    from jason.features.title_features import compute_title_features

    result = compute_title_features(channel_id=channel, force=force)
    typer.secho(
        f"title features: {result['computed']} computed (of {result['requested']} pending)",
        fg=typer.colors.GREEN,
    )


@features_app.command("topics")
def features_topics(
    themes: bool = typer.Option(False, "--themes", help="Fit BERTopic on masked titles."),
    franchises: bool = typer.Option(False, "--franchises", help="Fit BERTopic on raw titles."),
) -> None:
    """Fit two-layer BERTopic (themes with name-masking + franchises raw).

    Long-form videos only (Shorts excluded). Requires `uv sync --group ml`.
    """
    if not (themes or franchises):
        typer.echo("Pick --themes, --franchises, or both.", err=True)
        raise typer.Exit(1)

    if themes:
        from jason.features.topics import fit_themes
        r = fit_themes()
        typer.secho(
            f"themes: {r['fit']} videos → {r['topics']} non-noise topics",
            fg=typer.colors.GREEN,
        )

    if franchises:
        from jason.features.topics import fit_franchises
        r = fit_franchises()
        typer.secho(
            f"franchises: {r['fit']} videos → {r['topics']} non-noise topics",
            fg=typer.colors.GREEN,
        )


@features_app.command("embeddings")
def features_embeddings(
    titles: bool = typer.Option(False, "--titles", help="Encode title embeddings."),
    thumbnails: bool = typer.Option(False, "--thumbnails", help="Encode thumbnail embeddings."),
    channel: str | None = typer.Option(
        None, "--channel", "-c", help="Limit to one channel (UC...).",
    ),
    force: bool = typer.Option(False, "--force", help="Recompute even if already present."),
) -> None:
    """Compute title (sentence-transformers) and/or thumbnail (OpenCLIP) embeddings.

    Requires the optional `ml` dependency group: `uv sync --group ml`.
    First run downloads ~1.6GB of models.
    """
    if not (titles or thumbnails):
        typer.echo("Pick --titles, --thumbnails, or both.", err=True)
        raise typer.Exit(1)

    if titles:
        from jason.features.embeddings import embed_titles
        r = embed_titles(channel_id=channel, force=force)
        typer.secho(
            f"title embeddings: {r['encoded']} encoded (of {r['requested']} pending)",
            fg=typer.colors.GREEN,
        )

    if thumbnails:
        from jason.features.embeddings import embed_thumbnails
        r = embed_thumbnails(channel_id=channel, force=force)
        typer.secho(
            f"thumb embeddings: {r['encoded']} encoded (of {r['requested']} pending)",
            fg=typer.colors.GREEN,
        )


@features_app.command("outliers")
def features_outliers(
    channel: str | None = typer.Option(
        None, "--channel", "-c",
        help="Compute for one channel (UC...). Default: all channels.",
    ),
    target_days: int = typer.Option(28, "--target-days", help="Age (days) for views_at_age."),
    window_days: int = typer.Option(90, "--window-days", help="Window for intra-channel percentile."),
    skip_percentile: bool = typer.Option(False, "--skip-percentile", help="Only compute multipliers."),
) -> None:
    """Compute outlier multipliers + intra-channel percentiles per video."""
    import duckdb

    from jason.features.outliers import compute_multiplier, compute_percentile

    settings = get_settings()
    if channel:
        targets = [channel]
    else:
        with duckdb.connect(str(settings.duckdb_path)) as con:
            targets = [r[0] for r in con.execute("SELECT id FROM channels").fetchall()]

    for cid in targets:
        m = compute_multiplier(cid, target_days=target_days)
        msg = (
            f"  {cid}: total={m['total_videos']} eligible={m['eligible']} "
            f"computed={m['computed']} skipped(baseline)={m['skipped_no_baseline']} "
            f"skipped(age_data)={m['skipped_no_age_data']}"
        )
        typer.secho(msg, fg=typer.colors.GREEN if m["computed"] else typer.colors.YELLOW)

        if not skip_percentile and m["computed"] > 0:
            p = compute_percentile(cid, window_days=window_days)
            typer.echo(f"     percentiles updated for {p['computed']} video(s)")


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
