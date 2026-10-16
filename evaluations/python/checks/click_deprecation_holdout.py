"""Independent command label generation and meaningful option help preservation."""

from pathlib import Path

import click

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


class CaptureFormatter(click.HelpFormatter):
    def __init__(self):
        super().__init__()
        self.texts = []

    def write_text(self, text):
        self.texts.append(text)


command = click.Command("obsolete", deprecated="use modern")
formatter = CaptureFormatter()
with click.Context(command) as context:
    command.format_help_text(context, formatter)
assert formatter.texts == ["(DEPRECATED: use modern)"], formatter.texts
assert (
    click.Option(["--old"], deprecated=True, help="Keep this context").help
    == "Keep this context (DEPRECATED)"
)
assert click.Option(["--plain"], help="ordinary").help == "ordinary"
