"""Fuzzy comparison helpers for body composition extraction tests."""

from typing import Any

from data_model import BodyComposition, BodyCompositionMultipleScan

# Maximum absolute difference allowed for floating-point measurements.
_FLOAT_ABS_TOLERANCE = 1.5

# Maximum absolute difference allowed for integer fields.
_INT_ABS_TOLERANCE = 1

# Maximum Levenshtein edit distance allowed for string fields.
_STRING_EDIT_TOLERANCE = 1


def _levenshtein(left: str, right: str) -> int:
    """Return the Levenshtein edit distance between two strings.

    Args:
        left: First string.
        right: Second string.

    Returns:
        Minimum number of single-character edits to transform left into right.
    """
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous_row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current_row = [i]
        for j, right_char in enumerate(right, start=1):
            insertions = previous_row[j] + 1
            deletions = current_row[j - 1] + 1
            substitutions = previous_row[j - 1] + (left_char != right_char)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def _format_number(value: float | int) -> str:
    """Return a stable string representation for numeric fuzzy comparison.

    Args:
        value: Numeric value to format.

    Returns:
        String form with trailing zeros removed from decimals.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _values_close(field_name: str, actual: Any, expected: Any) -> bool:
    """Return whether two field values are close enough for extraction tests.

    Args:
        field_name: Name of the field being compared.
        actual: Value returned by the extractor.
        expected: Expected value from the test fixture.

    Returns:
        True when the values match exactly or are within configured tolerance.
    """
    if actual == expected:
        return True

    if field_name == "gender":
        return actual == expected

    if field_name == "age":
        return abs(int(actual) - int(expected)) <= _INT_ABS_TOLERANCE

    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if abs(float(actual) - float(expected)) <= _FLOAT_ABS_TOLERANCE:
            return True
        return (
            _levenshtein(_format_number(actual), _format_number(expected))
            <= _STRING_EDIT_TOLERANCE
        )

    if isinstance(actual, str) and isinstance(expected, str):
        return _levenshtein(actual, expected) <= _STRING_EDIT_TOLERANCE

    return False


def _field_mismatches(actual: BodyComposition, expected: BodyComposition) -> list[str]:
    """Collect human-readable mismatches between two body composition records.

    Args:
        actual: Value returned by the extractor.
        expected: Expected value from the test fixture.

    Returns:
        Descriptions of fields that differ beyond tolerance.
    """
    mismatches: list[str] = []
    for field_name in BodyComposition.model_fields:
        actual_value = getattr(actual, field_name)
        expected_value = getattr(expected, field_name)
        if not _values_close(field_name, actual_value, expected_value):
            mismatches.append(
                f"{field_name}: expected {expected_value!r}, got {actual_value!r}"
            )
    return mismatches


def assert_body_composition_close(
    actual: BodyComposition,
    expected: BodyComposition,
    *,
    scan_index: int,
) -> None:
    """Assert that two body composition records match within fuzzy tolerance.

    Args:
        actual: Value returned by the extractor.
        expected: Expected value from the test fixture.
        scan_index: Zero-based index of the scan in a multi-scan image.

    Raises:
        AssertionError: If any field differs beyond tolerance.
    """
    mismatches = _field_mismatches(actual, expected)
    if mismatches:
        details = "\n".join(f"  - {mismatch}" for mismatch in mismatches)
        raise AssertionError(f"Scan {scan_index} mismatches:\n{details}")


def assert_body_composition_multiple_scan_close(
    actual: BodyCompositionMultipleScan,
    expected: BodyCompositionMultipleScan,
) -> None:
    """Assert that multi-scan extraction results match within fuzzy tolerance.

    Args:
        actual: Value returned by the extractor.
        expected: Expected value from the test fixture.

    Raises:
        AssertionError: If scan count differs or any scan field is outside tolerance.
    """
    if len(actual.scans) != len(expected.scans):
        raise AssertionError(
            f"Expected {len(expected.scans)} scans, got {len(actual.scans)}"
        )

    for scan_index, (actual_scan, expected_scan) in enumerate(
        zip(actual.scans, expected.scans, strict=True)
    ):
        assert_body_composition_close(
            actual_scan,
            expected_scan,
            scan_index=scan_index,
        )
