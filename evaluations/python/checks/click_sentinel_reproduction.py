"""Independent reproduction: serializing an unset sentinel must retain identity."""

import pickle
from pathlib import Path

import click
from click._utils import UNSET

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


assert pickle.loads(pickle.dumps(UNSET)) is UNSET  # noqa: S301 - round-trip only this in-process constant.
