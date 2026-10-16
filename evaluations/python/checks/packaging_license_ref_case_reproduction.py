"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.licenses import canonicalize_license_expression

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
assert canonicalize_license_expression("LicenseRef-Local OR LicenseRef-local") == (
    "LicenseRef-Local OR LicenseRef-Local"
)
