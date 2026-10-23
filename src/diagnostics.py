"""Run isolated subprocess checks to identify crash-prone components."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from debug_trace import (
    DIAGNOSTICS_REPORT_PATH,
    SEGFAULT_RETURN_CODES,
    get_environment_snapshot,
    setup_crash_diagnostics,
    trace,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
WORKER_PATH = SRC_DIR / "gsheet_worker.py"


def _run_isolated_test(name: str, code: str) -> dict[str, Any]:
    """Execute Python code in a fresh subprocess and capture the result.

    Args:
        name: Diagnostic test name.
        code: Python source code to execute.

    Returns:
        Structured result describing pass, failure, or segfault.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)

    process = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    result = {
        "name": name,
        "returncode": process.returncode,
        "stdout": process.stdout.strip(),
        "stderr": process.stderr.strip(),
    }
    if process.returncode in SEGFAULT_RETURN_CODES:
        result["status"] = "segfault"
    elif process.returncode == 0:
        result["status"] = "pass"
    else:
        result["status"] = "fail"
    return result


def _run_worker_test(command: str) -> dict[str, Any]:
    """Execute a gsheet worker command in a fresh subprocess.

    Args:
        command: Worker command name.

    Returns:
        Structured result describing pass, failure, or segfault.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)

    process = subprocess.run(
        [sys.executable, str(WORKER_PATH), command],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    result = {
        "name": f"gsheet_worker_{command.replace('-', '_')}",
        "returncode": process.returncode,
        "stdout": process.stdout.strip()[:500],
        "stderr": process.stderr.strip()[:500],
    }
    if process.returncode in SEGFAULT_RETURN_CODES:
        result["status"] = "segfault"
    elif process.returncode == 0:
        result["status"] = "pass"
    else:
        result["status"] = "fail"
    return result


def run_diagnostics() -> dict[str, Any]:
    """Run isolated diagnostics for imports and core operations.

    Returns:
        Full diagnostics report with environment info and per-test results.
    """
    setup_crash_diagnostics()
    trace("diagnostics_started")

    tests: list[tuple[str, str]] = [
        ("import_pandas", "import pandas as pd; print(pd.__version__)"),
        ("import_pyarrow", "import pyarrow as pa; print(pa.__version__)"),
        ("import_matplotlib", "import matplotlib; print(matplotlib.__version__)"),
        ("import_streamlit", "import streamlit as st; print(st.__version__)"),
        ("import_gspread", "import gspread; print('ok')"),
        ("import_numind", "import numind; print('ok')"),
        ("import_openai", "import openai; print(openai.__version__)"),
        (
            "create_dataframe",
            "import pandas as pd; df = pd.DataFrame([{'name': 'Alice', 'date': '2026-07-11'}]); print(len(df))",
        ),
        ("extractor_import", "from extract import Extractor; Extractor(); print('ok')"),
        (
            "streamlit_plus_pandas",
            "import streamlit as st; import pandas as pd; print(st.__version__, pd.__version__)",
        ),
        (
            "import_app_module",
            (
                "import sys\n"
                f"sys.path.insert(0, {str(SRC_DIR)!r})\n"
                "import app\n"
                "print('ok')"
            ),
        ),
    ]

    sample_image = PROJECT_ROOT / "tests" / "samples" / "fa019548-74fb-43a1-b9ba-ebe33f7b4817.jpeg"
    if sample_image.is_file():
        tests.append(
            (
                "extract_sample_image",
                (
                    "import asyncio\n"
                    "from extract import Extractor\n"
                    f"result = asyncio.run(Extractor().extract({str(sample_image)!r}))\n"
                    "print(len(result.scans))"
                ),
            )
        )

    results = [_run_isolated_test(name, code) for name, code in tests]

    if os.getenv("GCP_OAUTH_CLIENT_SECRET_PATH"):
        results.append(_run_worker_test("read-worksheet"))

    report = {
        "environment": get_environment_snapshot(),
        "results": results,
        "trace_log": str(PROJECT_ROOT / ".data" / "debug_trace.log"),
        "crash_dump": str(PROJECT_ROOT / ".data" / "crash_dump.log"),
    }

    DIAGNOSTICS_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTICS_REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    trace(
        "diagnostics_finished",
        failed=sum(1 for item in results if item["status"] != "pass"),
    )
    return report


def _print_report(report: dict[str, Any]) -> None:
    """Print a human-readable diagnostics report.

    Args:
        report: Diagnostics report dictionary.
    """
    print("Environment:")
    for key, value in report["environment"].items():
        print(f"  {key}: {value}")

    print("\nIsolated tests:")
    for result in report["results"]:
        print(
            f"  [{result['status'].upper():8}] {result['name']} "
            f"(exit={result['returncode']})"
        )
        if result["stdout"]:
            print(f"           stdout: {result['stdout']}")
        if result["stderr"]:
            print(f"           stderr: {result['stderr']}")

    print(f"\nFull report: {DIAGNOSTICS_REPORT_PATH}")
    print(f"Trace log:   {report['trace_log']}")
    print(f"Crash dump:  {report['crash_dump']}")


def main() -> None:
    """Run diagnostics from the command line."""
    report = run_diagnostics()
    _print_report(report)


if __name__ == "__main__":
    main()
