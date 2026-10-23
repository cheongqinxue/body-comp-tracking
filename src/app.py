"""Streamlit app for extracting body composition data and saving to Google Sheets."""

import base64
import hashlib
import logging
import mimetypes
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from pydantic import ValidationError

pd.set_option("mode.string_storage", "python")

from data_model import BodyComposition, BodyCompositionMultipleScan, BodyCompositionTable
from debug_trace import (
    get_environment_snapshot,
    read_crash_dump_lines,
    read_recent_trace_lines,
    setup_crash_diagnostics,
    trace,
    trace_exception,
)

load_dotenv()
setup_crash_diagnostics()
trace("app_module_loaded", **get_environment_snapshot())

logger = logging.getLogger(__name__)

IMAGE_TYPES = ["jpg", "jpeg", "png", "webp"]
SESSION_IMAGE_PATH = "image_path"
SESSION_EXTRACTION = "extraction"
SESSION_SELECTED_SCAN = "selected_scan_index"
SESSION_UPLOAD_TOKEN = "upload_token"
SESSION_IMAGE_SOURCE_KEY = "image_source_key"
SESSION_EXTRACTION_WIDGET_KEY = "extraction_widget_key"
ACTIVE_PAGE_KEY = "active_page"


def _render_bounded_image_preview(image_path: Path) -> None:
    """Render an image capped at 60% of the viewport width or height.

    Args:
        image_path: Path to the image file to display.
    """
    mime_type, _ = mimetypes.guess_type(image_path)
    if mime_type is None:
        mime_type = "image/jpeg"

    encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    st.markdown(
        (
            f'<img src="data:{mime_type};base64,{encoded_image}" '
            'style="max-width: 60vw; max-height: 60vh; width: auto; height: auto; '
            'object-fit: contain; display: block;" />'
        ),
        unsafe_allow_html=True,
    )


def _scan_to_form_values(scan: BodyComposition) -> dict[str, object]:
    """Convert a body composition scan into editable form values.

    Args:
        scan: Extracted scan model.

    Returns:
        Dictionary of field names to form values.
    """
    return scan.model_dump()


def _widget_scope(source_key: str) -> str:
    """Return a stable, Streamlit-safe widget key suffix for a source key.

    Args:
        source_key: Identifier for the current image or extraction source.

    Returns:
        Short hash usable in Streamlit widget keys.
    """
    return hashlib.sha256(source_key.encode()).hexdigest()[:16]


def _clear_extraction_state() -> None:
    """Drop cached extraction results and form widget scope."""
    st.session_state[SESSION_EXTRACTION] = None
    st.session_state[SESSION_SELECTED_SCAN] = 0
    st.session_state.pop(SESSION_EXTRACTION_WIDGET_KEY, None)


def _mark_image_source_changed(source_key: str) -> None:
    """Invalidate extraction results when the selected image changes.

    Args:
        source_key: Stable identifier for the currently selected image.
    """
    previous_source = st.session_state.get(SESSION_IMAGE_SOURCE_KEY)
    if previous_source != source_key:
        _clear_extraction_state()
    st.session_state[SESSION_IMAGE_SOURCE_KEY] = source_key


def _cleanup_uploaded_image() -> None:
    """Delete a previously uploaded temporary image file."""
    image_path = st.session_state.get(SESSION_IMAGE_PATH)
    upload_token = st.session_state.get(SESSION_UPLOAD_TOKEN)
    if not upload_token or not image_path:
        return

    path = Path(image_path)
    if path.exists() and str(path).startswith(tempfile.gettempdir()):
        path.unlink(missing_ok=True)


def _store_uploaded_image(uploaded_file: Any) -> Path:
    """Persist an uploaded image to a temporary file.

    Args:
        uploaded_file: Image uploaded through Streamlit.

    Returns:
        Path to the saved temporary image file.
    """
    _cleanup_uploaded_image()
    _mark_image_source_changed(f"upload:{uploaded_file.file_id}")

    suffix = Path(uploaded_file.name).suffix or ".jpg"
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(uploaded_file.getbuffer())
    temp_file.close()

    st.session_state[SESSION_IMAGE_PATH] = temp_file.name
    st.session_state[SESSION_UPLOAD_TOKEN] = uploaded_file.file_id
    return Path(temp_file.name)


def _resolve_image_path(source_mode: str, disk_path: str) -> Path:
    """Resolve the image path from the selected input mode.

    Args:
        source_mode: Either ``upload`` or ``disk``.
        disk_path: Filesystem path entered by the user.

    Returns:
        Validated image path.

    Raises:
        ValueError: If the image path is missing or invalid.
    """
    if source_mode == "upload":
        image_path = st.session_state.get(SESSION_IMAGE_PATH)
        if not image_path:
            raise ValueError("Upload an image before extracting.")
        return Path(image_path)

    normalized_path = Path(disk_path).expanduser()
    if not normalized_path.is_file():
        raise ValueError(f"Image path does not exist: {normalized_path}")

    if normalized_path.suffix.lower().lstrip(".") not in IMAGE_TYPES:
        raise ValueError("Image path must point to a JPG, JPEG, PNG, or WEBP file.")

    resolved_source_key = f"disk:{normalized_path.resolve()}"
    _mark_image_source_changed(resolved_source_key)
    st.session_state[SESSION_IMAGE_PATH] = str(normalized_path)
    st.session_state[SESSION_UPLOAD_TOKEN] = None
    return normalized_path


async def _extract_from_image(image_path: Path) -> BodyCompositionMultipleScan:
    """Extract body composition scans from an image.

    Args:
        image_path: Path to the image file.

    Returns:
        Extracted scans from the image.
    """
    from extract import Extractor

    extractor = Extractor()
    return await extractor.extract(str(image_path))


def _render_scan_selector(scans: list[BodyComposition]) -> int:
    """Render a scan selector when multiple scans were extracted.

    Args:
        scans: Extracted scans from the image.

    Returns:
        Zero-based index of the selected scan.
    """
    if len(scans) == 1:
        return 0

    labels = [f"Scan {index + 1} ({scan.date or 'no date'})" for index, scan in enumerate(scans)]
    selected_index = st.selectbox(
        "Select scan to review",
        options=list(range(len(scans))),
        format_func=lambda index: labels[index],
        key="scan_selector",
    )
    st.session_state[SESSION_SELECTED_SCAN] = selected_index
    return selected_index


def _render_body_composition_form(
    scan_values: dict[str, object],
    *,
    form_key: str,
) -> dict[str, object]:
    """Render editable inputs for a body composition scan.

    Args:
        scan_values: Current values for the scan form.
        form_key: Unique Streamlit form key.

    Returns:
        Updated form values from user input.
    """
    updated_values = dict(scan_values)
    left_column, right_column = st.columns(2)

    with left_column:
        updated_values["date"] = st.text_input("Date", value=str(scan_values["date"]), key=f"{form_key}_date")
        updated_values["age"] = st.number_input(
            "Age",
            min_value=0,
            value=int(scan_values["age"]),
            step=1,
            key=f"{form_key}_age",
        )
        updated_values["gender"] = st.selectbox(
            "Gender",
            options=["female", "male"],
            index=0 if scan_values["gender"] == "female" else 1,
            key=f"{form_key}_gender",
        )
        updated_values["weight"] = st.number_input(
            "Weight (kg)",
            min_value=0.0,
            value=float(scan_values["weight"]),
            format="%.1f",
            key=f"{form_key}_weight",
        )
        updated_values["height"] = st.number_input(
            "Height (cm)",
            min_value=0.0,
            value=float(scan_values["height"]),
            format="%.1f",
            key=f"{form_key}_height",
        )
        updated_values["body_fat_percentage"] = st.number_input(
            "Body fat (%)",
            min_value=0.0,
            value=float(scan_values["body_fat_percentage"]),
            format="%.1f",
            key=f"{form_key}_body_fat_percentage",
        )
        updated_values["visceral_fat_rating"] = st.number_input(
            "Visceral fat rating",
            min_value=0.0,
            value=float(scan_values["visceral_fat_rating"]),
            format="%.1f",
            key=f"{form_key}_visceral_fat_rating",
        )

    with right_column:
        updated_values["muscle_mass"] = st.number_input(
            "Muscle mass (kg)",
            min_value=0.0,
            value=float(scan_values["muscle_mass"]),
            format="%.1f",
            key=f"{form_key}_muscle_mass",
        )
        updated_values["bone_mass"] = st.number_input(
            "Bone mass (kg)",
            min_value=0.0,
            value=float(scan_values["bone_mass"]),
            format="%.1f",
            key=f"{form_key}_bone_mass",
        )
        updated_values["body_mass_index"] = st.number_input(
            "BMI",
            min_value=0.0,
            value=float(scan_values["body_mass_index"]),
            format="%.1f",
            key=f"{form_key}_body_mass_index",
        )
        updated_values["basal_metabolic_rate_kj"] = st.number_input(
            "Basal metabolic rate (kJ/day)",
            min_value=0.0,
            value=float(scan_values["basal_metabolic_rate_kj"]),
            format="%.0f",
            key=f"{form_key}_basal_metabolic_rate_kj",
        )
        updated_values["total_body_water"] = st.number_input(
            "Total body water (L)",
            min_value=0.0,
            value=float(scan_values["total_body_water"]),
            format="%.1f",
            key=f"{form_key}_total_body_water",
        )
        updated_values["total_body_water_percentage"] = st.number_input(
            "Total body water (%)",
            min_value=0.0,
            value=float(scan_values["total_body_water_percentage"]),
            format="%.1f",
            key=f"{form_key}_total_body_water_percentage",
        )
        updated_values["fat_free_mass"] = st.number_input(
            "Fat-free mass (kg)",
            min_value=0.0,
            value=float(scan_values["fat_free_mass"]),
            format="%.1f",
            key=f"{form_key}_fat_free_mass",
        )

    return updated_values


def _build_table_record(name: str, scan_values: dict[str, object]) -> BodyCompositionTable:
    """Build a Google Sheets record from form values.

    Args:
        name: Person name provided by the user.
        scan_values: Edited body composition values.

    Returns:
        Validated record for ``GSheetEditor.add_record``.

    Raises:
        ValidationError: If the form values do not match the schema.
    """
    return BodyCompositionTable(name=name.strip(), **scan_values)


def _init_session_state() -> None:
    """Initialize Streamlit session state defaults."""
    if SESSION_IMAGE_PATH not in st.session_state:
        st.session_state[SESSION_IMAGE_PATH] = None
    if SESSION_EXTRACTION not in st.session_state:
        st.session_state[SESSION_EXTRACTION] = None
    if SESSION_SELECTED_SCAN not in st.session_state:
        st.session_state[SESSION_SELECTED_SCAN] = 0
    if SESSION_UPLOAD_TOKEN not in st.session_state:
        st.session_state[SESSION_UPLOAD_TOKEN] = None
    if SESSION_IMAGE_SOURCE_KEY not in st.session_state:
        st.session_state[SESSION_IMAGE_SOURCE_KEY] = None
    if SESSION_EXTRACTION_WIDGET_KEY not in st.session_state:
        st.session_state[SESSION_EXTRACTION_WIDGET_KEY] = None


def _show_extraction_error(error: Exception) -> None:
    """Display a user-friendly extraction error in Streamlit.

    Args:
        error: Exception raised while calling the inference server.
    """
    from extract import extraction_server_help_message, get_openai_base_url, is_extraction_connection_error

    if is_extraction_connection_error(error):
        st.error(extraction_server_help_message(get_openai_base_url()))
        return

    st.error(str(error))


def _show_google_sheets_error(error: Exception) -> None:
    """Display a user-friendly Google Sheets error in Streamlit.

    Args:
        error: Exception raised while accessing Google Sheets.
    """
    from gsheet_editor import google_auth_help_message, is_google_auth_error

    if is_google_auth_error(error):
        st.error(google_auth_help_message())
        return

    st.error(str(error))


def _load_worksheet_dataframe() -> pd.DataFrame:
    """Load worksheet records from Google Sheets.

    Returns:
        Worksheet contents as a DataFrame.

    Raises:
        Exception: If Google Sheets access fails.
    """
    from gsheet_streamlit import read_worksheet_in_subprocess

    return read_worksheet_in_subprocess()


def _render_data_entry_tab() -> None:
    """Render the image extraction and record entry workflow."""
    source_mode = st.radio(
        "Image source",
        options=["upload", "disk"],
        format_func=lambda value: "Upload photo" if value == "upload" else "Path on disk",
        horizontal=True,
    )

    disk_path = ""
    if source_mode == "upload":
        uploaded_file = st.file_uploader(
            "Upload body composition image",
            type=IMAGE_TYPES,
            key="image_uploader",
        )
        if uploaded_file is not None:
            _store_uploaded_image(uploaded_file)
    else:
        disk_path = st.text_input(
            "Image path on disk",
            placeholder="/path/to/body-composition.jpg",
            key="disk_image_path",
        )
        if disk_path.strip():
            try:
                normalized_disk_path = Path(disk_path).expanduser().resolve()
                _mark_image_source_changed(f"disk:{normalized_disk_path}")
            except OSError:
                pass

    extract_clicked = st.button("Extract from image", type="primary")

    if extract_clicked:
        try:
            trace("extract_button_clicked", source_mode=source_mode)
            image_path = _resolve_image_path(source_mode, disk_path)
            trace("extract_image_resolved", image_path=str(image_path))
            with st.spinner("Extracting body composition data..."):
                from async_runtime import run_async

                extraction = run_async(_extract_from_image(image_path))
            trace(
                "extract_completed",
                scan_count=len(extraction.scans),
                image_path=str(image_path),
                image_sha256=hashlib.sha256(image_path.read_bytes()).hexdigest()[:16],
            )
            source_key = st.session_state.get(SESSION_IMAGE_SOURCE_KEY) or str(image_path.resolve())
            st.session_state[SESSION_EXTRACTION] = extraction
            st.session_state[SESSION_SELECTED_SCAN] = 0
            st.session_state[SESSION_EXTRACTION_WIDGET_KEY] = _widget_scope(source_key)
            st.success(f"Extracted {len(extraction.scans)} scan(s).")
        except Exception as error:
            trace_exception("extract_failed", error)
            logger.exception("Image extraction failed.")
            _show_extraction_error(error)

    image_path_value = st.session_state.get(SESSION_IMAGE_PATH)
    if image_path_value and Path(image_path_value).is_file():
        st.subheader("Image preview")
        _render_bounded_image_preview(Path(image_path_value))

    extraction = st.session_state.get(SESSION_EXTRACTION)
    if extraction is None or not extraction.scans:
        st.info("Extract an image to review and save body composition data.")
        return

    widget_scope = st.session_state.get(SESSION_EXTRACTION_WIDGET_KEY, "pending")
    selected_scan_index = _render_scan_selector(extraction.scans)
    selected_scan = extraction.scans[selected_scan_index]
    scan_values = _scan_to_form_values(selected_scan)

    st.subheader("Review and edit extracted values")
    name = st.text_input("Name", placeholder="Required for Google Sheets", key="person_name")
    edited_values = _render_body_composition_form(
        scan_values,
        form_key=f"scan_{selected_scan_index}_{widget_scope}",
    )

    if st.button("Add record to Google Sheets", type="secondary"):
        if not name.strip():
            st.error("Name is required before adding a record to Google Sheets.")
            return

        try:
            trace("add_record_clicked", name=name.strip())
            record = _build_table_record(name, edited_values)
            from gsheet_streamlit import add_record_in_subprocess

            add_record_in_subprocess(record)
            trace("add_record_completed", record_name=record.name, record_date=record.date)
            st.session_state.pop("worksheet_dataframe", None)
            st.success(f"Added record for {record.name} to Google Sheets.")
        except ValidationError as error:
            trace_exception("add_record_validation_failed", error)
            st.error(f"Invalid form values: {error}")
        except Exception as error:
            trace_exception("add_record_failed", error)
            logger.exception("Failed to add record to Google Sheets.")
            _show_google_sheets_error(error)


def _render_person_charts(person_dataframe: pd.DataFrame) -> None:
    """Render chart set for one person's body composition history.

    Args:
        person_dataframe: Sorted records for the selected person.
    """
    import matplotlib.pyplot as plt

    from charts import (
        DUAL_AXIS_CHARTS,
        SINGLE_AXIS_CHARTS,
        build_dual_axis_chart,
        build_single_axis_chart,
        enrich_person_dataframe,
    )

    chart_dataframe = enrich_person_dataframe(person_dataframe)
    chart_columns = st.columns(2)
    chart_index = 0

    for chart_definition in DUAL_AXIS_CHARTS:
        target_column = chart_columns[chart_index % 2]
        with target_column:
            figure = build_dual_axis_chart(
                chart_dataframe,
                title=chart_definition["title"],
                left_column=chart_definition["left_column"],
                left_label=chart_definition["left_label"],
                right_column=chart_definition["right_column"],
                right_label=chart_definition["right_label"],
            )
            st.pyplot(figure, width="stretch")
            plt.close(figure)
        chart_index += 1

    for chart_definition in SINGLE_AXIS_CHARTS:
        column = chart_definition["column"]
        if column not in chart_dataframe.columns:
            continue

        target_column = chart_columns[chart_index % 2]
        with target_column:
            figure = build_single_axis_chart(
                chart_dataframe,
                column=column,
                label=chart_definition["label"],
            )
            st.pyplot(figure, width="stretch")
            plt.close(figure)
        chart_index += 1


def _render_data_display_tab() -> None:
    """Render charts for stored body composition records."""
    from charts import list_person_names, prepare_person_dataframe

    if st.button("Refresh data from Google Sheets", key="refresh_sheet_data"):
        st.session_state.pop("worksheet_dataframe", None)

    try:
        worksheet_dataframe = st.session_state.get("worksheet_dataframe")
        if worksheet_dataframe is None:
            with st.spinner("Loading worksheet data..."):
                worksheet_dataframe = _load_worksheet_dataframe()
            st.session_state["worksheet_dataframe"] = worksheet_dataframe
    except Exception as error:
        logger.exception("Failed to load worksheet data.")
        _show_google_sheets_error(error)
        return

    if worksheet_dataframe.empty:
        st.info("No records in Google Sheets yet. Add data from the Data entry tab.")
        return

    person_names = list_person_names(worksheet_dataframe)
    if not person_names:
        st.info("No person names found in Google Sheets.")
        return

    selected_person = st.selectbox("Person", options=person_names, key="chart_person_selector")
    person_dataframe = prepare_person_dataframe(worksheet_dataframe, selected_person)

    if person_dataframe.empty:
        st.warning(f"No dated records found for {selected_person}.")
        return

    st.caption(f"Showing {len(person_dataframe)} record(s) for {selected_person}.")
    _render_person_charts(person_dataframe)


def _render_diagnostics_tab() -> None:
    """Render crash diagnostics and recent trace logs."""
    from diagnostics import run_diagnostics

    st.subheader("Crash diagnostics")
    st.caption(
        "If Streamlit segfaults, the last completed step is written to "
        "`.data/debug_trace.log`. Python stack dumps go to `.data/crash_dump.log`."
    )

    if st.button("Run isolated diagnostics", type="primary"):
        with st.spinner("Running isolated subprocess checks..."):
            report = run_diagnostics()
        st.session_state["diagnostics_report"] = report
        st.success("Diagnostics completed.")

    report = st.session_state.get("diagnostics_report")
    if report:
        st.json(report)

    st.subheader("Recent trace log")
    trace_lines = read_recent_trace_lines()
    if trace_lines:
        st.code("\n".join(trace_lines), language="json")
    else:
        st.info("No trace log entries yet.")

    st.subheader("Recent crash dump")
    crash_lines = read_crash_dump_lines()
    if crash_lines:
        st.code("\n".join(crash_lines))
    else:
        st.info("No crash dump entries yet.")

    st.subheader("CLI diagnostics")
    st.code("uv run --env-file .env python src/diagnostics.py", language="bash")


def main() -> None:
    """Run the Streamlit body composition tracking app."""
    st.set_page_config(page_title="Body Composition Tracker", layout="wide")
    st.title("Body Composition Tracker")
    st.caption("Upload printouts, save records to Google Sheets, and review trends over time.")

    _init_session_state()

    page = st.radio(
        "Page",
        options=["Data entry", "Charts", "Diagnostics"],
        horizontal=True,
        key=ACTIVE_PAGE_KEY,
    )
    trace("page_render_started", page=page)

    if page == "Data entry":
        _render_data_entry_tab()
    elif page == "Charts":
        _render_data_display_tab()
    else:
        _render_diagnostics_tab()


if __name__ == "__main__":
    main()
