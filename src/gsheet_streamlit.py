"""Streamlit helpers for running Google Sheets work in an isolated subprocess."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from data_model import BodyCompositionTable
from debug_trace import trace, trace_exception

APP_DIR = Path(__file__).resolve().parent


def _run_gsheet_worker(command: str, payload: str = "") -> str:
    """Run a Google Sheets worker command in a separate process.

    Streamlit and pandas/pyarrow can segfault when Google Sheets IO runs in the
    same process. Executing sheet work in a child process keeps the UI stable.

    Args:
        command: Worker command name.
        payload: Optional stdin payload for the worker.

    Returns:
        Worker stdout when the command returns output.

    Raises:
        RuntimeError: If the worker exits with a non-zero status.
    """
    process = subprocess.run(
        [sys.executable, str(APP_DIR / "gsheet_worker.py"), command],
        input=payload,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    if process.returncode != 0:
        error_message = process.stderr.strip() or process.stdout.strip() or "Google Sheets worker failed."
        trace(
            "gsheet_worker_failed",
            command=command,
            returncode=process.returncode,
            stderr=process.stderr.strip()[:500],
            stdout=process.stdout.strip()[:500],
        )
        raise RuntimeError(error_message)
    trace("gsheet_worker_completed", command=command, returncode=process.returncode)
    return process.stdout


def add_record_in_subprocess(record: BodyCompositionTable) -> None:
    """Add or update a worksheet record via the worker subprocess.

    Args:
        record: Record to write to Google Sheets.
    """
    trace("add_record_subprocess_started", name=record.name, date=record.date)
    try:
        _run_gsheet_worker("add-record", record.model_dump_json())
    except Exception as error:
        trace_exception("add_record_subprocess_failed", error)
        raise


def read_worksheet_in_subprocess() -> pd.DataFrame:
    """Read worksheet records via the worker subprocess.

    Returns:
        Worksheet contents as a DataFrame.
    """
    stdout = _run_gsheet_worker("read-worksheet")
    records: list[dict[str, Any]] = json.loads(stdout or "[]")
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).astype("object")
