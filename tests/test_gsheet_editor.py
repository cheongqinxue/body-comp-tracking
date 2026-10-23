"""Tests for Google Sheets OAuth login and editor initialization."""

import os

from dotenv import load_dotenv

load_dotenv()


from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_model import BodyCompositionTable
from gsheet_editor import (
    CLIENT_SECRET_ENV,
    REQUIRED_COLUMNS,
    SCOPES,
    TOKEN_PATH_ENV,
    GSheetEditor,
    get_user_credentials,
)


def _client_secret_path() -> Path | None:
    """Return the configured OAuth client secret path when it exists.

    Returns:
        Path to the client secret file, or None when not configured.
    """
    configured_path = os.getenv(CLIENT_SECRET_ENV)
    if not configured_path:
        return None

    client_secret = Path(configured_path)
    return client_secret if client_secret.is_file() else None


def _token_path() -> Path:
    """Return the configured OAuth token storage path.

    Returns:
        Path where the OAuth token JSON is stored.
    """
    return Path(os.getenv(TOKEN_PATH_ENV, "token.json"))


def _sample_record() -> BodyCompositionTable:
    """Return a sample body composition table record.

    Returns:
        A populated ``BodyCompositionTable`` instance for tests.
    """
    return BodyCompositionTable(
        name="Alice",
        date="2026-07-11",
        age=35,
        gender="female",
        weight=43.5,
        height=154.0,
        body_fat_percentage=29.3,
        visceral_fat_rating=2.0,
        muscle_mass=29.3,
        bone_mass=1.5,
        body_mass_index=18.3,
        basal_metabolic_rate_kj=3866.0,
        total_body_water=20.8,
        total_body_water_percentage=47.8,
        fat_free_mass=30.3,
    )


def _valid_worksheet_dataframe() -> pd.DataFrame:
    """Return a worksheet DataFrame with all required columns.

    Returns:
        Empty DataFrame containing the ``BodyCompositionTable`` columns.
    """
    return pd.DataFrame(columns=REQUIRED_COLUMNS)


def _worksheet_rows_from_records(records: list[BodyCompositionTable]) -> list[list[object]]:
    """Build worksheet rows with a header row and optional records.

    Args:
        records: Records to include after the header row.

    Returns:
        Worksheet values as row lists.
    """
    rows: list[list[object]] = [REQUIRED_COLUMNS]
    for record in records:
        rows.append([record.model_dump()[column] for column in REQUIRED_COLUMNS])
    return rows


@pytest.fixture
def editor() -> GSheetEditor:
    """Return a ``GSheetEditor`` with authentication mocked out.

    Returns:
        Editor instance that does not perform real OAuth.
    """
    mock_creds = MagicMock()
    mock_creds.valid = True

    with (
        patch("gsheet_editor.get_user_credentials", return_value=mock_creds),
        patch("gsheet_editor.gspread.authorize", return_value=MagicMock()),
    ):
        yield GSheetEditor(
            client_secret_path="/tmp/credentials.json",
            token_path="/tmp/token.json",
            spreadsheet_name="Body Composition",
        )


class TestGSheetEditorColumns:
    """Tests for worksheet column validation."""

    def test_assert_columns_present_passes_for_required_columns(
        self,
        editor: GSheetEditor,
    ) -> None:
        """Accept a worksheet that contains every required column.

        Args:
            editor: Editor instance under test.
        """
        editor._assert_columns_present(_valid_worksheet_dataframe())

    def test_assert_columns_present_raises_when_columns_missing(
        self,
        editor: GSheetEditor,
    ) -> None:
        """Raise ValueError when required columns are missing.

        Args:
            editor: Editor instance under test.
        """
        incomplete_dataframe = pd.DataFrame(columns=["name", "date", "weight"])

        with pytest.raises(ValueError, match="missing required columns"):
            editor._assert_columns_present(incomplete_dataframe)

    def test_read_worksheet_returns_empty_dataframe_when_sheet_is_empty(
        self,
        editor: GSheetEditor,
    ) -> None:
        """Return an empty DataFrame when the worksheet is completely blank.

        Args:
            editor: Editor instance under test.
        """
        mock_worksheet = MagicMock()
        empty_dataframe = pd.DataFrame()

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch("gsheet_editor.get_as_dataframe", return_value=empty_dataframe),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            result = editor.read_worksheet()

        assert result.empty
        assert len(result.columns) == 0

    def test_read_worksheet_returns_header_only_sheet_without_error(
        self,
        editor: GSheetEditor,
    ) -> None:
        """Return an empty DataFrame with headers when only a header row exists.

        Args:
            editor: Editor instance under test.
        """
        mock_worksheet = MagicMock()
        header_only_dataframe = pd.DataFrame(columns=["name", "date", "weight"])

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch("gsheet_editor.get_as_dataframe", return_value=header_only_dataframe),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            result = editor.read_worksheet()

        assert result.empty
        assert list(result.columns) == ["name", "date", "weight"]

    def test_read_worksheet_raises_when_data_present_and_columns_missing(
        self,
        editor: GSheetEditor,
    ) -> None:
        """Raise ValueError when data rows exist but required columns are missing.

        Args:
            editor: Editor instance under test.
        """
        mock_worksheet = MagicMock()
        incomplete_dataframe = pd.DataFrame(
            [{"name": "Alice", "date": "2026-07-11", "weight": 43.5}]
        )

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch("gsheet_editor.get_as_dataframe", return_value=incomplete_dataframe),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            with pytest.raises(ValueError, match="missing required columns"):
                editor.read_worksheet()


class TestGSheetEditorAddRecord:
    """Tests for appending body composition records."""

    def test_add_record_initializes_columns_on_empty_sheet(self, editor: GSheetEditor) -> None:
        """Create required headers when appending to a blank worksheet.

        Args:
            editor: Editor instance under test.
        """
        record = _sample_record()
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = []

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            editor.add_record(record)

        mock_worksheet.update.assert_called_once()
        update_args = mock_worksheet.update.call_args.args
        assert update_args[0] == "A1"
        assert update_args[1][0] == REQUIRED_COLUMNS
        assert update_args[1][1][REQUIRED_COLUMNS.index("name")] == record.name

    def test_add_record_appends_row_when_columns_are_valid(self, editor: GSheetEditor) -> None:
        """Append a record when the worksheet has the required columns.

        Args:
            editor: Editor instance under test.
        """
        record = _sample_record()
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = [REQUIRED_COLUMNS]

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            editor.add_record(record)

        mock_worksheet.append_row.assert_called_once()
        appended_row = mock_worksheet.append_row.call_args.args[0]
        assert appended_row[REQUIRED_COLUMNS.index("name")] == record.name
        assert appended_row[REQUIRED_COLUMNS.index("weight")] == record.weight

    def test_add_record_updates_existing_row_when_index_matches(
        self,
        editor: GSheetEditor,
    ) -> None:
        """Update an existing row when name and date match case-insensitively.

        Args:
            editor: Editor instance under test.
        """
        existing_record = _sample_record()
        updated_record = existing_record.model_copy(update={"weight": 41.0, "name": "alice"})
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = _worksheet_rows_from_records([existing_record])

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            editor.add_record(updated_record)

        mock_worksheet.update.assert_called_once()
        updated_row = mock_worksheet.update.call_args.args[1][0]
        assert updated_row[REQUIRED_COLUMNS.index("name")] == "alice"
        assert updated_row[REQUIRED_COLUMNS.index("weight")] == 41.0

    def test_add_record_appends_when_date_differs(self, editor: GSheetEditor) -> None:
        """Append a new row when only the date index differs.

        Args:
            editor: Editor instance under test.
        """
        existing_record = _sample_record()
        new_record = existing_record.model_copy(update={"date": "2026-06-20", "weight": 44.3})
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = _worksheet_rows_from_records([existing_record])

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            editor.add_record(new_record)

        mock_worksheet.append_row.assert_called_once()
        appended_row = mock_worksheet.append_row.call_args.args[0]
        assert appended_row[REQUIRED_COLUMNS.index("date")] == "2026-06-20"
        assert appended_row[REQUIRED_COLUMNS.index("weight")] == 44.3

    def test_add_record_raises_when_columns_missing(self, editor: GSheetEditor) -> None:
        """Raise ValueError when appending to a worksheet with missing columns.

        Args:
            editor: Editor instance under test.
        """
        record = _sample_record()
        mock_worksheet = MagicMock()
        mock_worksheet.get_all_values.return_value = [
            ["name", "date", "weight"],
            ["Alice", "2026-07-11", 43.5],
        ]

        with (
            patch.object(editor.client, "open", return_value=MagicMock()),
            patch.object(GSheetEditor, "_get_worksheet", return_value=mock_worksheet),
        ):
            with pytest.raises(ValueError, match="missing required columns"):
                editor.add_record(record)

        mock_worksheet.append_row.assert_not_called()
        mock_worksheet.update.assert_not_called()

    def test_add_record_raises_for_invalid_record_type(self, editor: GSheetEditor) -> None:
        """Raise TypeError when the input is not a BodyCompositionTable.

        Args:
            editor: Editor instance under test.
        """
        with pytest.raises(TypeError, match="BodyCompositionTable"):
            editor.add_record({"name": "Alice"})  # type: ignore[arg-type]


class TestGetUserCredentials:
    """Unit tests for OAuth credential loading."""

    def test_returns_valid_credentials_from_existing_token(self, tmp_path: Path) -> None:
        """Use an existing valid token file without running OAuth or refresh.

        Args:
            tmp_path: Pytest temporary directory fixture.
        """
        token_path = tmp_path / "token.json"
        token_path.write_text("{}", encoding="utf-8")
        client_secret_path = tmp_path / "credentials.json"
        client_secret_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch(
            "gsheet_editor.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ) as mock_from_file:
            result = get_user_credentials(str(client_secret_path), str(token_path))

        assert result is mock_creds
        mock_from_file.assert_called_once_with(str(token_path), SCOPES)

    def test_refreshes_expired_credentials(self, tmp_path: Path) -> None:
        """Refresh expired credentials when a refresh token is available.

        Args:
            tmp_path: Pytest temporary directory fixture.
        """
        token_path = tmp_path / "token.json"
        token_path.write_text("{}", encoding="utf-8")
        client_secret_path = tmp_path / "credentials.json"
        client_secret_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.to_json.return_value = '{"refresh_token": "refresh-token"}'

        def _mark_valid_after_refresh(*_args: object, **_kwargs: object) -> None:
            mock_creds.valid = True

        mock_creds.refresh.side_effect = _mark_valid_after_refresh

        with (
            patch(
                "gsheet_editor.Credentials.from_authorized_user_file",
                return_value=mock_creds,
            ),
            patch("gsheet_editor.Request") as mock_request,
        ):
            result = get_user_credentials(str(client_secret_path), str(token_path))

        assert result is mock_creds
        mock_creds.refresh.assert_called_once_with(mock_request.return_value)
        assert token_path.read_text() == mock_creds.to_json.return_value

    def test_reruns_oauth_flow_when_refresh_fails(self, tmp_path: Path) -> None:
        """Delete stale tokens and re-authenticate when refresh is rejected.

        Args:
            tmp_path: Pytest temporary directory fixture.
        """
        from google.auth.exceptions import RefreshError

        token_path = tmp_path / "token.json"
        token_path.write_text('{"refresh_token": "stale"}', encoding="utf-8")
        client_secret_path = tmp_path / "credentials.json"
        client_secret_path.write_text('{"installed": {}}', encoding="utf-8")

        stale_creds = MagicMock()
        stale_creds.valid = False
        stale_creds.expired = True
        stale_creds.refresh_token = "stale-refresh-token"
        stale_creds.refresh.side_effect = RefreshError("invalid_grant: Bad Request")

        new_creds = MagicMock()
        new_creds.valid = True
        new_creds.to_json.return_value = '{"token": "new-token"}'
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = new_creds

        with (
            patch(
                "gsheet_editor.Credentials.from_authorized_user_file",
                return_value=stale_creds,
            ),
            patch(
                "gsheet_editor.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ) as mock_from_secrets,
        ):
            result = get_user_credentials(str(client_secret_path), str(token_path))

        assert result is new_creds
        mock_from_secrets.assert_called_once()
        mock_flow.run_local_server.assert_called_once_with(port=0)
        assert token_path.read_text() == new_creds.to_json.return_value

    def test_runs_local_oauth_flow_when_token_missing(self, tmp_path: Path) -> None:
        """Run the installed-app OAuth flow when no token file exists.

        Args:
            tmp_path: Pytest temporary directory fixture.
        """
        token_path = tmp_path / "token.json"
        client_secret_path = tmp_path / "credentials.json"
        client_secret_path.write_text('{"installed": {}}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds.to_json.return_value = '{"token": "new-token"}'
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with (
            patch(
                "gsheet_editor.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ) as mock_from_secrets,
        ):
            result = get_user_credentials(str(client_secret_path), str(token_path))

        assert result is mock_creds
        mock_from_secrets.assert_called_once()
        mock_flow.run_local_server.assert_called_once_with(port=0)
        assert token_path.read_text() == mock_creds.to_json.return_value


class TestGSheetEditorLogin:
    """Integration tests for real OAuth login."""

    @pytest.mark.integration
    def test_oauth_login_succeeds(self) -> None:
        """Authenticate with Google using configured OAuth credentials.

        Skips when the client secret is not configured. When no token file
        exists yet, this test opens a browser window to complete the OAuth flow.
        """
        client_secret = _client_secret_path()
        if client_secret is None:
            pytest.skip(f"{CLIENT_SECRET_ENV} is not configured.")

        editor = GSheetEditor(client_secret_path=str(client_secret), token_path=str(_token_path()))

        assert editor.is_authenticated()
        assert editor.client is not None
        assert _token_path().is_file()
