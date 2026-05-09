#!/usr/bin/env python3
"""Validate knowledge entry JSON files.

Usage:
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py knowledge/articles/*.json
"""

import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://\S+")
SUMMARY_MIN_LENGTH = 20
TAGS_MIN_COUNT = 1
SCORE_MIN = 1
SCORE_MAX = 10


class ValidationError:
    """A single validation error for a file."""

    def __init__(self, file_path: str, message: str, field: str | None = None):
        self.file_path = file_path
        self.message = message
        self.field = field

    def __str__(self) -> str:
        prefix = f"[{self.field}]" if self.field else "[file]"
        return f"  {self.file_path}: {prefix} {self.message}"


def validate_file(file_path: Path) -> list[ValidationError]:
    """Validate a single JSON knowledge entry file."""
    errors: list[ValidationError] = []
    file_str = str(file_path)

    if not file_path.exists():
        errors.append(ValidationError(file_str, "File not found"))
        return errors

    if file_path.suffix.lower() != ".json":
        errors.append(ValidationError(file_str, "Not a .json file"))

    try:
        data = file_path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(ValidationError(file_str, f"Failed to read file: {e}"))
        return errors

    try:
        obj = json.loads(data)
    except json.JSONDecodeError as e:
        errors.append(ValidationError(file_str, f"Invalid JSON: {e}"))
        return errors

    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            item_errors = _validate_entry(item, f"{file_str}[{idx}]")
            errors.extend(item_errors)
    elif isinstance(obj, dict):
        errors.extend(_validate_entry(obj, file_str))
    else:
        errors.append(ValidationError(file_str, "Root element must be a JSON object or array"))

    return errors


def _validate_entry(entry: dict, location: str) -> list[ValidationError]:
    """Validate a single knowledge entry dict."""
    errors: list[ValidationError] = []

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in entry:
            errors.append(ValidationError(location, f"Missing required field", field=field))
        elif not isinstance(entry[field], expected_type):
            errors.append(
                ValidationError(
                    location,
                    f"Expected type {expected_type.__name__}, got {type(entry[field]).__name__}",
                    field=field,
                )
            )

    if "id" in entry and isinstance(entry["id"], str):
        if not ID_PATTERN.match(entry["id"]):
            errors.append(
                ValidationError(
                    location,
                    f"Invalid id format '{entry['id']}', expected {{source}}-{{YYYYMMDD}}-{{NNN}}",
                    field="id",
                )
            )

    if "status" in entry and isinstance(entry["status"], str):
        if entry["status"] not in VALID_STATUSES:
            errors.append(
                ValidationError(
                    location,
                    f"Invalid status '{entry['status']}', expected one of {sorted(VALID_STATUSES)}",
                    field="status",
                )
            )

    if "source_url" in entry and isinstance(entry["source_url"], str):
        if not URL_PATTERN.match(entry["source_url"]):
            errors.append(
                ValidationError(
                    location,
                    f"Invalid URL format '{entry['source_url']}'",
                    field="source_url",
                )
            )

    if "summary" in entry and isinstance(entry["summary"], str):
        if len(entry["summary"]) < SUMMARY_MIN_LENGTH:
            errors.append(
                ValidationError(
                    location,
                    f"Summary too short ({len(entry['summary'])} chars), minimum {SUMMARY_MIN_LENGTH}",
                    field="summary",
                )
            )

    if "tags" in entry and isinstance(entry["tags"], list):
        if len(entry["tags"]) < TAGS_MIN_COUNT:
            errors.append(
                ValidationError(
                    location,
                    f"At least {TAGS_MIN_COUNT} tag(s) required, got {len(entry['tags'])}",
                    field="tags",
                )
            )

    if "score" in entry:
        score = entry["score"]
        if not isinstance(score, (int, float)):
            errors.append(
                ValidationError(
                    location,
                    f"Expected numeric type for score, got {type(score).__name__}",
                    field="score",
                )
            )
        elif score < SCORE_MIN or score > SCORE_MAX:
            errors.append(
                ValidationError(
                    location,
                    f"Score {score} out of range [{SCORE_MIN}, {SCORE_MAX}]",
                    field="score",
                )
            )

    if "audience" in entry:
        audience = entry["audience"]
        if audience not in VALID_AUDIENCES:
            errors.append(
                ValidationError(
                    location,
                    f"Invalid audience '{audience}', expected one of {sorted(VALID_AUDIENCES)}",
                    field="audience",
                )
            )

    return errors


def collect_json_files(args: list[str]) -> list[Path]:
    """Collect all JSON files from CLI arguments, supporting glob patterns."""
    files: list[Path] = []
    for arg in args:
        path = Path(arg)
        if "*" in arg or "?" in arg:
            files.extend(sorted(path.parent.glob(path.name)))
        else:
            if path.exists():
                files.append(path)
            else:
                print(f"Error: file not found: {arg}", file=sys.stderr)
    return files


def print_summary(results: dict[str, list[ValidationError]]) -> None:
    """Print summary statistics."""
    total_files = len(results)
    total_entries = 0
    total_errors = 0
    valid_count = 0

    for file_path, errors in results.items():
        if not errors:
            valid_count += 1
        total_errors += len(errors)

    print(f"\n{'=' * 50}")
    print(f"Validation Summary")
    print(f"{'=' * 50}")
    print(f"  Files checked:     {total_files}")
    print(f"  Files passed:      {valid_count}")
    print(f"  Files failed:      {total_files - valid_count}")
    print(f"  Total errors:      {total_errors}")
    print(f"{'=' * 50}")


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <json_file> [json_file2 ...]", file=sys.stderr)
        return 1

    files = collect_json_files(sys.argv[1:])
    if not files:
        print("Error: no JSON files to validate", file=sys.stderr)
        return 1

    results: dict[str, list[ValidationError]] = {}
    has_errors = False

    for file_path in files:
        errors = validate_file(file_path)
        results[str(file_path)] = errors
        if errors:
            has_errors = True
            for error in errors:
                print(error, file=sys.stderr)

    print_summary(results)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
