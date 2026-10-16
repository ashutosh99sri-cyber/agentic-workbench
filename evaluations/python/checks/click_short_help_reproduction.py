"""Independent reproduction: abbreviations must not end a command summary."""

from pathlib import Path

import click

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


command = click.Command("compare", help="Compare cats vs. dogs in the report. Details follow.")
assert command.get_short_help_str(limit=90) == "Compare cats vs. dogs in the report."
