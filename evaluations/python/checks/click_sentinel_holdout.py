"""Independent nested-copy and serialization identity checks."""

import copy
import pickle
from pathlib import Path

import click
from click._utils import UNSET

assert Path(click.__file__).resolve() == Path.cwd().resolve() / "src/click/__init__.py"


assert copy.deepcopy({"default": [UNSET]})["default"][0] is UNSET
for protocol in (0, 2, pickle.HIGHEST_PROTOCOL):
    assert pickle.loads(pickle.dumps((UNSET,), protocol=protocol))[0] is UNSET  # noqa: S301 - round-trip only this in-process constant.
assert repr(UNSET).endswith(".UNSET")
