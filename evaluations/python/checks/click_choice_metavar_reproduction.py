"""Independent reproduction: optional choices need one bracket pair in usage."""

from pathlib import Path

import click
from click.testing import CliRunner

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


command = click.Command(
    "pick",
    params=[click.Argument(["flavor"], type=click.Choice(["tea", "coffee"]), required=False)],
)
result = CliRunner().invoke(command, ["--help"])
assert result.exit_code == 0
assert "[tea|coffee]" in result.output
assert "[[" not in result.output, result.output
