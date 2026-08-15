from typer.testing import CliRunner

from chatgpt_archive import __version__
from chatgpt_archive.cli import app


def test_version_command_matches_package_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__ == "1.0.0"
