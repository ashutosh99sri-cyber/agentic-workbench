"""Independent optional value, alternate help flag, and default-help behavior."""

from pathlib import Path

import click
from click.testing import CliRunner

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


@click.command(context_settings={"help_option_names": ["-?", "--help"]})
@click.argument("help", required=False, default="index")
def handbook(help):
    click.echo(help)


runner = CliRunner()
for arguments, expected in (([], "index\n"), (["chapter"], "chapter\n")):
    result = runner.invoke(handbook, arguments)
    assert result.exit_code == 0, result.output
    assert result.output == expected, result.output
for arguments in (["--help"], ["-?"]):
    result = runner.invoke(handbook, arguments)
    assert result.exit_code == 0
    assert "Usage:" in result.output and "Show this message" in result.output
