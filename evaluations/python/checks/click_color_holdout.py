"""Independent background, invalid-input, and ordinary style checks."""

from pathlib import Path

import click

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


assert click.style("paper", bg=0) == "\x1b[48;5;0mpaper\x1b[0m"
for invalid in (True, False, -1, 256, (2, -1, 4), (1, 2), (1, 2, 300), "missing"):
    try:
        click.style("value", fg=invalid)
    except ValueError:
        pass
    else:
        raise AssertionError(f"invalid color accepted: {invalid!r}")
assert click.style("red", fg="red") == "\x1b[31mred\x1b[0m"
assert click.style("rgb", fg=(3, 4, 5)) == "\x1b[38;2;3;4;5mrgb\x1b[0m"
assert click.style("plain", reset=False) == "plain"
