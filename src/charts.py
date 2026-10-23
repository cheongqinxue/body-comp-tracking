"""Chart builders for body composition time-series display."""

from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import pandas as pd

DUAL_AXIS_CHARTS: list[dict[str, str]] = [
    {
        "title": "Body fat",
        "left_column": "body_fat_mass",
        "left_label": "Body fat mass (kg)",
        "right_column": "body_fat_percentage",
        "right_label": "Body fat (%)",
    },
    {
        "title": "Total body water",
        "left_column": "total_body_water",
        "left_label": "Total body water (L)",
        "right_column": "total_body_water_percentage",
        "right_label": "Total body water (%)",
    },
    {
        "title": "Fat-free mass",
        "left_column": "fat_free_mass",
        "left_label": "Fat-free mass (kg)",
        "right_column": "fat_free_mass_percentage",
        "right_label": "Fat-free mass (%)",
    },
]

SINGLE_AXIS_CHARTS: list[dict[str, str]] = [
    {"column": "weight", "label": "Weight (kg)"},
    {"column": "height", "label": "Height (cm)"},
    {"column": "visceral_fat_rating", "label": "Visceral fat rating"},
    {"column": "muscle_mass", "label": "Muscle mass (kg)"},
    {"column": "bone_mass", "label": "Bone mass (kg)"},
    {"column": "body_mass_index", "label": "BMI"},
    {"column": "basal_metabolic_rate_kj", "label": "Basal metabolic rate (kJ/day)"},
    {"column": "age", "label": "Age (years)"},
]

NUMERIC_COLUMNS: list[str] = [
    "age",
    "weight",
    "height",
    "body_fat_percentage",
    "visceral_fat_rating",
    "muscle_mass",
    "bone_mass",
    "body_mass_index",
    "basal_metabolic_rate_kj",
    "total_body_water",
    "total_body_water_percentage",
    "fat_free_mass",
]


def _coerce_numeric_columns(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Convert worksheet metric columns to numeric values for charting.

    Args:
        dataframe: Person records that may contain object-typed sheet values.

    Returns:
        DataFrame with numeric metric columns where possible.
    """
    coerced = dataframe.copy()
    for column in NUMERIC_COLUMNS:
        if column in coerced.columns:
            coerced[column] = pd.to_numeric(coerced[column], errors="coerce")
    return coerced


def prepare_person_dataframe(dataframe: pd.DataFrame, person_name: str) -> pd.DataFrame:
    """Filter and sort worksheet data for one person.

    Args:
        dataframe: Worksheet contents from Google Sheets.
        person_name: Person name to filter on.

    Returns:
        Sorted records for the selected person.
    """
    if dataframe.empty or "name" not in dataframe.columns:
        return pd.DataFrame()

    normalized_name = person_name.strip().lower()
    filtered_rows = [
        row
        for row in dataframe.to_dict(orient="records")
        if str(row.get("name", "")).strip().lower() == normalized_name
    ]
    person_dataframe = pd.DataFrame(filtered_rows)
    if person_dataframe.empty:
        return person_dataframe

    person_dataframe["date"] = pd.to_datetime(person_dataframe["date"], errors="coerce")
    person_dataframe = person_dataframe.dropna(subset=["date"])
    return person_dataframe.sort_values("date")


def enrich_person_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Add derived chart columns used by dual-axis charts.

    Args:
        dataframe: Sorted person records.

    Returns:
        Person records with derived metric columns added.
    """
    enriched = _coerce_numeric_columns(dataframe)
    enriched["body_fat_mass"] = enriched["weight"] * enriched["body_fat_percentage"] / 100
    enriched["fat_free_mass_percentage"] = (enriched["fat_free_mass"] / enriched["weight"]) * 100
    return enriched


def list_person_names(dataframe: pd.DataFrame) -> list[str]:
    """Return sorted person names from worksheet data.

    Args:
        dataframe: Worksheet contents from Google Sheets.

    Returns:
        Unique person names sorted alphabetically.
    """
    if dataframe.empty or "name" not in dataframe.columns:
        return []

    names = {
        str(value).strip()
        for value in dataframe["name"].tolist()
        if str(value).strip()
    }
    return sorted(names, key=str.lower)


def build_dual_axis_chart(
    dataframe: pd.DataFrame,
    *,
    title: str,
    left_column: str,
    left_label: str,
    right_column: str,
    right_label: str,
) -> Figure:
    """Build a dual-axis line chart for a mass metric and related percentage.

    Args:
        dataframe: Person records sorted by date.
        title: Chart title.
        left_column: Primary-axis column name.
        left_label: Primary-axis label.
        right_column: Secondary-axis column name.
        right_label: Secondary-axis label.

    Returns:
        Matplotlib figure ready for display.
    """
    figure, left_axis = plt.subplots(figsize=(6, 4))
    dates = dataframe["date"]
    left_axis.plot(
        dates,
        dataframe[left_column],
        marker="o",
        color="#1f77b4",
        label=left_label,
    )
    left_axis.set_ylabel(left_label, color="#1f77b4")
    left_axis.tick_params(axis="y", labelcolor="#1f77b4")
    left_axis.set_xlabel("Date")
    left_axis.set_title(title)

    right_axis = left_axis.twinx()
    right_axis.plot(
        dates,
        dataframe[right_column],
        marker="o",
        color="#ff7f0e",
        label=right_label,
    )
    right_axis.set_ylabel(right_label, color="#ff7f0e")
    right_axis.tick_params(axis="y", labelcolor="#ff7f0e")

    figure.autofmt_xdate()
    figure.tight_layout()
    return figure


def build_single_axis_chart(
    dataframe: pd.DataFrame,
    *,
    column: str,
    label: str,
) -> Figure:
    """Build a single-axis line chart for one metric over time.

    Args:
        dataframe: Person records sorted by date.
        column: Column name to plot.
        label: Axis and chart title.

    Returns:
        Matplotlib figure ready for display.
    """
    figure, axis = plt.subplots(figsize=(6, 4))
    axis.plot(dataframe["date"], dataframe[column], marker="o", color="#1f77b4")
    axis.set_xlabel("Date")
    axis.set_ylabel(label)
    axis.set_title(label)
    figure.autofmt_xdate()
    figure.tight_layout()
    return figure
