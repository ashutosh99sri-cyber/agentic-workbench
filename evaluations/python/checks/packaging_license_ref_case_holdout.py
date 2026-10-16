"""Independently authored historical packaging behavior check."""

from pathlib import Path

import packaging
from packaging.licenses import canonicalize_license_expression

assert Path(packaging.__file__).resolve() == Path.cwd().resolve() / "src/packaging/__init__.py"
value = "(licenseref-Team AND MIT) OR LicenseRef-TEAM"
assert canonicalize_license_expression(value) == "(LicenseRef-Team AND MIT) OR LicenseRef-Team"
assert canonicalize_license_expression("apache-2.0 OR MIT") == "Apache-2.0 OR MIT"
