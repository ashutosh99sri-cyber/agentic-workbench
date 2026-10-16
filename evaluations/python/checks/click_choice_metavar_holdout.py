"""Independent variadic optional choices and unchanged required arguments."""

from pathlib import Path

import click
from click.testing import CliRunner

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


runner = CliRunner()
command = click.Command(
    "paint", params=[click.Argument(["colors"], type=click.Choice(["ochre", "indigo"]), nargs=-1)]
)
result = runner.invoke(command, ["--help"])
assert result.exit_code == 0
assert "[ochre|indigo]..." in result.output and "[[" not in result.output, result.output
required = click.Command("must", params=[click.Argument(["name"], required=True)])
assert "NAME" in runner.invoke(required, ["--help"]).output
assert "[NAME]" not in runner.invoke(required, ["--help"]).output
