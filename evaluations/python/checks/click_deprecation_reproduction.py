"""Independent reproduction: an empty option help must not add label whitespace."""

from pathlib import Path

import click

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


option = click.Option(["--legacy"], deprecated=True, help="")
assert option.help == "(DEPRECATED)", repr(option.help)
