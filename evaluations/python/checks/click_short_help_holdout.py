"""Independent summary boundaries and ordinary short-help behavior."""

from pathlib import Path

import click

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


def short(text, limit=100):
    return click.Command("inspect", help=text).get_short_help_str(limit=limit)


assert short("Read e.g. small manifests. Then continue.") == "Read e.g. small manifests."
assert short("Load cfg. files before launch.") == "Load cfg. files before launch."
assert short("Done. Next stage.") == "Done."
assert short("host-side names stay intact", 15) == "host-side..."
assert short("\b") == ""
assert short("Simple summary") == "Simple summary"
