"""Crash diagnostics and step tracing for Streamlit debugging."""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import platform
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / ".data"
TRACE_LOG_PATH = DATA_DIR / "debug_trace.log"
CRASH_DUMP_PATH = DATA_DIR / "crash_dump.log"
DIAGNOSTICS_REPORT_PATH = DATA_DIR / "diagnostics_report.json"

SEGFAULT_RETURN_CODES = {-11, 139, 245}


def _timestamp() -> str:
    """Return the current UTC timestamp as an ISO-8601 string.

    Returns:
        ISO-formatted UTC timestamp.
    """
    return datetime.now(UTC).isoformat()


def setup_crash_diagnostics() -> None:
    """Enable faulthandler dumps and file logging for crash investigation."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    crash_dump_file = CRASH_DUMP_PATH.open("a", encoding="utf-8")
    faulthandler.enable(file=crash_dump_file, all_threads=True)
    faulthandler.enable(all_threads=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(TRACE_LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )

    trace(
        "crash_diagnostics_enabled",
        python=sys.version.split()[0],
        platform=platform.platform(),
        pid=os.getpid(),
        cwd=str(Path.cwd()),
    )


def trace(step: str, **context: Any) -> None:
    """Write a structured trace line for step-by-step debugging.

    Args:
        step: Short identifier for the operation being traced.
        **context: Additional key/value context to include in the log line.
    """
    payload = {"ts": _timestamp(), "step": step, **context}
    logging.getLogger("debug_trace").info(json.dumps(payload, default=str))


def trace_exception(step: str, error: BaseException) -> None:
    """Log an exception with traceback for a traced step.

    Args:
        step: Short identifier for the failed operation.
        error: Exception that was raised.
    """
    payload = {
        "ts": _timestamp(),
        "step": step,
        "error_type": type(error).__name__,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }
    logging.getLogger("debug_trace").error(json.dumps(payload, default=str))


def get_environment_snapshot() -> dict[str, str]:
    """Collect package versions useful for crash reports.

    Returns:
        Installed package versions and runtime metadata.
    """
    versions: dict[str, str] = {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "pid": str(os.getpid()),
        "cwd": str(Path.cwd()),
    }
    for package_name in (
        "streamlit",
        "pandas",
        "pyarrow",
        "altair",
        "gspread",
        "openai",
        "numind",
        "pydantic",
    ):
        try:
            module = __import__(package_name)
            versions[package_name] = getattr(module, "__version__", "unknown")
        except Exception as error:
            versions[package_name] = f"import_failed:{type(error).__name__}"

    return versions


def read_recent_trace_lines(limit: int = 80) -> list[str]:
    """Return the most recent trace log lines.

    Args:
        limit: Maximum number of lines to return.

    Returns:
        Recent lines from the trace log, or an empty list when unavailable.
    """
    if not TRACE_LOG_PATH.exists():
        return []

    lines = TRACE_LOG_PATH.read_text(encoding="utf-8").splitlines()
    return lines[-limit:]


def read_crash_dump_lines(limit: int = 80) -> list[str]:
    """Return the most recent faulthandler dump lines.

    Args:
        limit: Maximum number of lines to return.

    Returns:
        Recent lines from the crash dump log, or an empty list when unavailable.
    """
    if not CRASH_DUMP_PATH.exists():
        return []

    lines = CRASH_DUMP_PATH.read_text(encoding="utf-8").splitlines()
    return lines[-limit:]
