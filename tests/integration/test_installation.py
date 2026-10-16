import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.distribution
def test_clean_installed_package(tmp_path: Path) -> None:
    python = os.environ.get("AGENTIC_INSTALLED_PYTHON")
    assert python is not None and Path(python).is_absolute(), (
        "Supply clean installed package Python"
    )
    script = Path(__file__).resolve().parents[2] / "scripts/verify_distribution.py"
    result = subprocess.run(
        [python, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"required_commands": 6' in result.stdout
