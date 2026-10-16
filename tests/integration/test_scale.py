import time
from pathlib import Path

from agentic_workbench.config import Config, ScanConfig
from agentic_workbench.policy import WorkspacePolicy
from agentic_workbench.repository import scan_workspace


def test_bounded_scale_inventory(tmp_path: Path) -> None:
    for number in range(1000):
        (tmp_path / f"module_{number:04}.py").write_text(
            f"def value_{number}():\n    return {number}\n"
        )
    started = time.monotonic()
    full = scan_workspace(WorkspacePolicy(tmp_path))
    elapsed = time.monotonic() - started
    assert len(full.files) == 1000 and len(full.symbols) == 1000
    bounded = scan_workspace(WorkspacePolicy(tmp_path, Config(scan=ScanConfig(max_files=100))))
    assert len(bounded.files) == bounded.coverage["scanned"] == 100
    assert bounded.coverage["limit_reached"] == 1
    print(f"scale files=1000 symbols=1000 elapsed_seconds={elapsed:.3f}")
