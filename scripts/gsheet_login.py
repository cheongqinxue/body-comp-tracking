"""Re-authenticate with Google Sheets OAuth."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from gsheet_editor import GSheetEditor  # noqa: E402


def main() -> None:
    """Run the Google OAuth login flow and verify access."""
    load_dotenv(PROJECT_ROOT / ".env")
    editor = GSheetEditor()
    if not editor.is_authenticated():
        raise SystemExit("Google authentication failed.")

    print("Google authentication succeeded.")
    if editor.spreadsheet_name:
        print(f"Default spreadsheet: {editor.spreadsheet_name}")


if __name__ == "__main__":
    main()
