"""Independent reproduction: a positional help parameter must reach the callback."""

from pathlib import Path

import click
from click.testing import CliRunner

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


@click.command()
@click.argument("help")
def program(help):
    click.echo(f"document={help}")


result = CliRunner().invoke(program, ["manual"])
assert result.exit_code == 0, result.output
assert result.output == "document=manual\n", result.output
