"""Isolated worker process for Google Sheets operations."""

import json
import sys
from typing import Any

from data_model import BodyCompositionTable
from debug_trace import setup_crash_diagnostics, trace, trace_exception
from gsheet_editor import GSheetEditor

setup_crash_diagnostics()


def _add_record(record_payload: str) -> None:
    """Add or update a worksheet record from JSON input.

    Args:
        record_payload: JSON string for a ``BodyCompositionTable`` record.
    """
    trace("worker_add_record_started", payload_bytes=len(record_payload))
    record = BodyCompositionTable.model_validate_json(record_payload)
    trace("worker_add_record_validated", name=record.name, date=record.date)
    editor = GSheetEditor()
    trace("worker_add_record_editor_ready")
    editor.add_record(record)
    trace("worker_add_record_completed", name=record.name, date=record.date)


def _read_worksheet() -> list[dict[str, Any]]:
    """Read worksheet rows as JSON-serializable records.

    Returns:
        Worksheet records as a list of dictionaries.
    """
    trace("worker_read_worksheet_started")
    editor = GSheetEditor()
    trace("worker_read_worksheet_editor_ready")
    dataframe = editor.read_worksheet()
    trace("worker_read_worksheet_loaded", row_count=len(dataframe))
    if dataframe.empty:
        return []
    return dataframe.to_dict(orient="records")


def main() -> None:
    """Run a Google Sheets worker command."""
    if len(sys.argv) < 2:
        raise SystemExit("Usage: gsheet_worker.py <add-record|read-worksheet>")

    command = sys.argv[1]
    trace("worker_started", command=command, pid=__import__("os").getpid())

    try:
        if command == "add-record":
            _add_record(sys.stdin.read())
            return

        if command == "read-worksheet":
            print(json.dumps(_read_worksheet()))
            return

        raise SystemExit(f"Unknown command: {command}")
    except Exception as error:
        trace_exception(f"worker_failed_{command or 'unknown'}", error)
        raise


if __name__ == "__main__":
    main()
