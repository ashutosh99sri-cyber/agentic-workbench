"""Independent reproduction: palette index zero is a real foreground color."""

from pathlib import Path

import click

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


assert click.style("ink", fg=0) == "\x1b[38;5;0mink\x1b[0m"
