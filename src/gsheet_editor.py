"""Google Sheets editor with OAuth authentication and DataFrame read/write."""

import os
from pathlib import Path

import gspread
import pandas as pd
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from gspread import Spreadsheet, Worksheet
from gspread_dataframe import get_as_dataframe

from data_model import BodyCompositionTable

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DEFAULT_TOKEN_PATH = "token.json"
CLIENT_SECRET_ENV = "GCP_OAUTH_CLIENT_SECRET_PATH"
TOKEN_PATH_ENV = "GCP_OAUTH_TOKEN_PATH"
SPREADSHEET_NAME_ENV = "GCP_SPREADSHEET_NAME"
REQUIRED_COLUMNS = list(BodyCompositionTable.model_fields.keys())


class GoogleAuthRequiredError(RuntimeError):
    """Raised when Google OAuth credentials must be renewed interactively."""


def is_google_auth_error(error: Exception | str) -> bool:
    """Return whether an error indicates expired or revoked Google OAuth credentials.

    Args:
        error: Exception or message raised during Google API access.

    Returns:
        True when the user must sign in to Google again.
    """
    message = str(error).lower()
    return "invalid_grant" in message or "refresherror" in message


def google_auth_help_message() -> str:
    """Return instructions for renewing Google OAuth credentials.

    Returns:
        Human-readable re-authentication instructions.
    """
    return (
        "Your Google sign-in token has expired or was revoked. "
        "Re-authenticate by running this in a terminal:\n\n"
        "uv run --env-file .env python scripts/gsheet_login.py\n\n"
        "Complete the browser sign-in, then retry in the app."
    )


def _save_credentials(credentials: Credentials, token_path: Path) -> None:
    """Persist authorized user credentials to disk.

    Args:
        credentials: OAuth credentials to store.
        token_path: Destination path for the token JSON file.
    """
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding="utf-8")


def _run_local_oauth_flow(client_secret_path: str) -> Credentials:
    """Run the installed-app OAuth flow in a local browser session.

    Args:
        client_secret_path: Path to the OAuth desktop client secrets JSON file.

    Returns:
        Newly authorized Google OAuth credentials.
    """
    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    return flow.run_local_server(port=0)


def get_user_credentials(client_secret_path: str, token_path: str) -> Credentials:
    """Load or obtain OAuth credentials for Google Sheets API access.

    Uses a saved token file when available. Refreshes expired tokens or runs
    the local OAuth flow when credentials are missing or invalid.

    Args:
        client_secret_path: Path to the OAuth desktop client secrets JSON file.
        token_path: Path where the authorized user token JSON is stored.

    Returns:
        Valid Google OAuth credentials for the configured scopes.
    """
    token_file = Path(token_path)
    credentials: Credentials | None = None

    if token_file.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            if credentials.valid:
                _save_credentials(credentials, token_file)
                return credentials
        except RefreshError:
            credentials = None
            token_file.unlink(missing_ok=True)

    credentials = _run_local_oauth_flow(client_secret_path)
    _save_credentials(credentials, token_file)
    return credentials


def _column_letter(column_index: int) -> str:
    """Convert a one-based column index into an Excel-style column label.

    Args:
        column_index: One-based column index.

    Returns:
        Column label such as ``A`` or ``AA``.
    """
    letters = ""
    index = column_index
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class GSheetEditor:
    """Read and write Google Sheets using pandas DataFrames."""

    def __init__(
        self,
        client_secret_path: str | None = None,
        token_path: str | None = None,
        spreadsheet_name: str | None = None,
    ) -> None:
        """Initialize the editor and authorize a gspread client.

        Args:
            client_secret_path: OAuth client secrets path. Defaults to
                ``GCP_OAUTH_CLIENT_SECRET_PATH``.
            token_path: OAuth token storage path. Defaults to
                ``GCP_OAUTH_TOKEN_PATH`` or ``token.json``.
            spreadsheet_name: Optional default spreadsheet title. Defaults to
                ``GCP_SPREADSHEET_NAME`` when set.
        """
        resolved_client_secret_path = client_secret_path or os.environ[CLIENT_SECRET_ENV]
        self.token_path = token_path or os.environ.get(TOKEN_PATH_ENV, DEFAULT_TOKEN_PATH)
        self.spreadsheet_name = spreadsheet_name or os.environ.get(SPREADSHEET_NAME_ENV)
        self.creds = get_user_credentials(resolved_client_secret_path, self.token_path)
        self.client = gspread.authorize(self.creds)

    def is_authenticated(self) -> bool:
        """Return whether the stored OAuth credentials are currently valid.

        Returns:
            True when credentials are valid for API access.
        """
        return self.creds.valid

    def _resolve_spreadsheet_name(self, spreadsheet_name: str | None) -> str:
        """Resolve the spreadsheet name from an argument or configured default.

        Args:
            spreadsheet_name: Explicit spreadsheet title, if provided.

        Returns:
            Spreadsheet title to open.

        Raises:
            ValueError: If no spreadsheet name is provided or configured.
        """
        resolved_name = spreadsheet_name or self.spreadsheet_name
        if not resolved_name:
            raise ValueError(
                "Spreadsheet name must be provided or configured via GCP_SPREADSHEET_NAME."
            )
        return resolved_name

    def _get_worksheet(self, spreadsheet: Spreadsheet, worksheet: str | int) -> Worksheet:
        """Return a worksheet from a spreadsheet by title or index.

        Args:
            spreadsheet: Open gspread spreadsheet instance.
            worksheet: Worksheet title or zero-based worksheet index.

        Returns:
            Matching worksheet instance.

        Raises:
            ValueError: If a worksheet index does not exist.
        """
        if isinstance(worksheet, str):
            return spreadsheet.worksheet(worksheet)

        resolved_worksheet = spreadsheet.get_worksheet(worksheet)
        if resolved_worksheet is None:
            raise ValueError(f"Worksheet index {worksheet} not found.")
        return resolved_worksheet

    def _is_worksheet_empty(self, dataframe: pd.DataFrame) -> bool:
        """Return whether a worksheet has no headers or cell values.

        Args:
            dataframe: Worksheet contents read from Google Sheets.

        Returns:
            True when the worksheet is completely blank.
        """
        return len(dataframe.columns) == 0

    def _empty_worksheet_dataframe(self) -> pd.DataFrame:
        """Return an empty worksheet DataFrame with the required column headers.

        Returns:
            DataFrame containing ``BodyCompositionTable`` columns and no rows.
        """
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    def _assert_columns_present(self, dataframe: pd.DataFrame) -> None:
        """Validate that a worksheet DataFrame contains all required columns.

        Args:
            dataframe: Worksheet contents read from Google Sheets.

        Raises:
            ValueError: If any ``BodyCompositionTable`` column is missing.
        """
        actual_columns = {str(column) for column in dataframe.columns}
        missing_columns = [
            column for column in REQUIRED_COLUMNS if column not in actual_columns
        ]
        if missing_columns:
            raise ValueError(
                "Worksheet is missing required columns: "
                f"{missing_columns}. Expected columns: {REQUIRED_COLUMNS}."
            )

    def _assert_headers_present(self, headers: list[str]) -> None:
        """Validate that worksheet headers contain all required columns.

        Args:
            headers: Header row values from the worksheet.

        Raises:
            ValueError: If any ``BodyCompositionTable`` column is missing.
        """
        actual_columns = {str(header) for header in headers if str(header)}
        missing_columns = [
            column for column in REQUIRED_COLUMNS if column not in actual_columns
        ]
        if missing_columns:
            raise ValueError(
                "Worksheet is missing required columns: "
                f"{missing_columns}. Expected columns: {REQUIRED_COLUMNS}."
            )

    def _record_index_key(self, name: object, date: object) -> tuple[str, str]:
        """Build a case-insensitive index key for upsert matching.

        Args:
            name: Person name from a worksheet row or incoming record.
            date: Measurement date from a worksheet row or incoming record.

        Returns:
            Lowercased name and date pair used as the record index.
        """
        return str(name).lower(), str(date).lower()

    def _record_to_row(self, record: BodyCompositionTable) -> list[object]:
        """Convert a record into a worksheet row ordered by required columns.

        Args:
            record: Record to serialize for Google Sheets.

        Returns:
            Row values ordered to match ``REQUIRED_COLUMNS``.
        """
        record_data = record.model_dump()
        return [record_data[column] for column in REQUIRED_COLUMNS]

    def _find_matching_row_number(
        self,
        worksheet_rows: list[list[str]],
        record: BodyCompositionTable,
    ) -> int | None:
        """Return the one-based worksheet row number matching a record index.

        Args:
            worksheet_rows: Worksheet values including the header row.
            record: Incoming record to match against existing rows.

        Returns:
            Matching row number, or ``None`` when no row matches.
        """
        if len(worksheet_rows) < 2:
            return None

        headers = worksheet_rows[0]
        self._assert_headers_present(headers)
        column_indexes = {column: headers.index(column) for column in REQUIRED_COLUMNS}
        record_name_key, record_date_key = self._record_index_key(record.name, record.date)

        for row_number, row in enumerate(worksheet_rows[1:], start=2):
            padded_row = row + [""] * (len(headers) - len(row))
            row_name = padded_row[column_indexes["name"]]
            row_date = padded_row[column_indexes["date"]]
            if self._record_index_key(row_name, row_date) == (record_name_key, record_date_key):
                return row_number

        return None

    def _write_row(self, worksheet: Worksheet, row_number: int, row_values: list[object]) -> None:
        """Write a full row to a worksheet range.

        Args:
            worksheet: Worksheet to update.
            row_number: One-based row number.
            row_values: Cell values ordered by ``REQUIRED_COLUMNS``.
        """
        last_column = _column_letter(len(REQUIRED_COLUMNS))
        cell_range = f"A{row_number}:{last_column}{row_number}"
        worksheet.update(cell_range, [row_values], value_input_option="USER_ENTERED")

    def read_worksheet(
        self,
        worksheet: str | int = 0,
        *,
        spreadsheet_name: str | None = None,
    ) -> pd.DataFrame:
        """Read a worksheet into a pandas DataFrame.

        Args:
            worksheet: Worksheet title or zero-based worksheet index.
            spreadsheet_name: Spreadsheet title. Uses the configured default when omitted.

        Returns:
            Worksheet contents as a DataFrame.
        """
        spreadsheet = self.client.open(self._resolve_spreadsheet_name(spreadsheet_name))
        worksheet_obj = self._get_worksheet(spreadsheet, worksheet)
        dataframe = get_as_dataframe(worksheet_obj)

        if self._is_worksheet_empty(dataframe):
            return pd.DataFrame()

        if not dataframe.empty:
            self._assert_columns_present(dataframe)

        return dataframe

    def add_record(
        self,
        record: BodyCompositionTable,
        worksheet: str | int = 0,
        *,
        spreadsheet_name: str | None = None,
    ) -> None:
        """Insert or update a body composition record in a worksheet.

        Uses lowercase ``name`` and ``date`` as an idempotency index. When a
        matching row already exists, that row is updated in place. Otherwise a
        new row is appended.

        Args:
            record: Record conforming to ``BodyCompositionTable``.
            worksheet: Worksheet title or zero-based worksheet index.
            spreadsheet_name: Spreadsheet title. Uses the configured default when omitted.

        Raises:
            ValueError: If the worksheet is missing required columns.
            TypeError: If ``record`` is not a ``BodyCompositionTable`` instance.
        """
        if not isinstance(record, BodyCompositionTable):
            raise TypeError(
                "record must be a BodyCompositionTable instance, "
                f"got {type(record).__name__}."
            )

        spreadsheet = self.client.open(self._resolve_spreadsheet_name(spreadsheet_name))
        worksheet_obj = self._get_worksheet(spreadsheet, worksheet)
        worksheet_rows = worksheet_obj.get_all_values()
        row_values = self._record_to_row(record)

        if not worksheet_rows:
            worksheet_obj.update(
                "A1",
                [REQUIRED_COLUMNS, row_values],
                value_input_option="USER_ENTERED",
            )
            return

        self._assert_headers_present(worksheet_rows[0])
        matching_row_number = self._find_matching_row_number(worksheet_rows, record)
        if matching_row_number is not None:
            self._write_row(worksheet_obj, matching_row_number, row_values)
            return

        worksheet_obj.append_row(row_values, value_input_option="USER_ENTERED")
