"""Run the pinned Python repair corpus; live calls require explicit configuration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentic_workbench.errors import WorkbenchError
from agentic_workbench.evaluation import MODES, PYTHON_IMAGE, LiveConfig, evaluate_corpus


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("evaluations/python/manifest.json"))
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, required=True, help="New disposable evidence directory"
    )
    parser.add_argument("--mode", choices=MODES, default="no-patch-control")
    parser.add_argument("--task", action="append", dest="task_ids")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--download", action="store_true", help="Explicit official-source network fetch"
    )
    parser.add_argument(
        "--trusted-host", action="store_true", help="Reviewed fixtures only; no OS sandbox"
    )
    parser.add_argument("--python", default=sys.executable, dest="python_executable")
    parser.add_argument("--image", default=PYTHON_IMAGE)
    parser.add_argument(
        "--live-config", type=Path, help="Explicit model, prices, price provenance, USD <=5 budget"
    )
    args = parser.parse_args()
    try:
        if args.live_config is not None and args.mode != "provider":
            raise WorkbenchError("CONFIG_ERROR", "Live configuration requires provider mode")
        report = evaluate_corpus(
            args.manifest,
            args.cache,
            args.output,
            mode=args.mode,
            task_ids=args.task_ids,
            trials=args.trials,
            max_attempts=args.max_attempts,
            backend="trusted-host" if args.trusted_host else "docker",
            image=args.image,
            python_executable=args.python_executable,
            download=args.download,
            live=LiveConfig.read(args.live_config) if args.live_config else None,
        )
    except (WorkbenchError, OSError) as error:
        print(
            json.dumps(
                {
                    "error": error.code if isinstance(error, WorkbenchError) else "IO_ERROR",
                    "message": str(error),
                }
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "mode": report["mode"],
                "scorecards": report["scorecards"],
                "report": str(args.output / "report.json"),
            },
            indent=2,
        )
    )
    # Controls deliberately include unrepaired tasks. A completed report is a successful evaluation.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
