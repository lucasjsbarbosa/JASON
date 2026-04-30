"""Smoke tests — package imports, config loads, CLI registers commands."""

from typer.testing import CliRunner

from jason import __version__
from jason.cli import app
from jason.config import get_settings


def test_version_is_set() -> None:
    assert __version__
    assert isinstance(__version__, str)


def test_settings_load_with_defaults() -> None:
    settings = get_settings()
    assert settings.anthropic_model
    assert settings.whisper_model == "large-v3"


def test_cli_help_exits_zero() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "JASON" in result.stdout


def test_cli_version_subcommand() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
