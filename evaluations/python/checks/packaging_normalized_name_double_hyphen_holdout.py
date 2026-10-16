"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.utils import canonicalize_name, is_normalized_name

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
for value in ("a--b", "abc---def", "part--two-three"):
    assert not is_normalized_name(value), value
    assert is_normalized_name(canonicalize_name(value))
for value in ("a", "ab", "a1-b2-c3"):
    assert is_normalized_name(value), value
