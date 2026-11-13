from __future__ import annotations

import os
from datetime import datetime
from typing import Any


DEFAULT_AUTHOR = "Office Automation Agent"

# These are the built-in defaults. Change them here, with the
# OFFICE_AGENT_AUTHOR environment variable, or per job/step in the spec.
DEFAULT_METADATA: dict[str, str] = {
    "author": DEFAULT_AUTHOR,
    "last_modified_by": DEFAULT_AUTHOR,
    "title": "",
    "subject": "",
    "keywords": "",
    "category": "",
    "comments": "",
}

TEXT_FIELDS = tuple(DEFAULT_METADATA)

DATE_FIELDS = ("created", "modified")

SUPPORTED_FIELDS = TEXT_FIELDS + DATE_FIELDS

AUTHOR_ENV = "OFFICE_AGENT_AUTHOR"

# Actions that accept a 'metadata' argument.
METADATA_ACTIONS = {
    ("word", "create_document"),
    ("word", "append_elements"),
    ("word", "set_metadata"),
    ("excel", "create_workbook"),
    ("excel", "set_metadata"),
}


class MetadataError(ValueError):
    """Raised for unknown metadata fields or unparseable dates."""


def defaults() -> dict[str, str]:
    """Built-in defaults, with the author overridable from the environment."""

    values = dict(DEFAULT_METADATA)

    author = os.getenv(AUTHOR_ENV, "").strip()

    if author:
        values["author"] = author
        values["last_modified_by"] = author

    return values


def resolve(
    overrides: dict[str, Any] | None = None,
    use_defaults: bool = True,
) -> dict[str, Any]:
    """
    Merge overrides over the defaults and validate them.

    Field names are case-insensitive. Dates accept ISO 8601 strings.
    With use_defaults=False only the supplied fields are returned, which
    leaves untouched metadata on existing files alone.
    """

    values: dict[str, Any] = defaults() if use_defaults else {}

    if overrides is None:
        return values

    if not isinstance(overrides, dict):
        raise MetadataError("'metadata' must be an object.")

    for key, value in overrides.items():
        name = str(key).strip().lower()

        if name not in SUPPORTED_FIELDS:
            raise MetadataError(
                f"Unknown metadata field '{key}'. Supported fields: "
                + ", ".join(SUPPORTED_FIELDS)
            )

        if name in DATE_FIELDS:
            values[name] = parse_datetime(value, name)
        else:
            values[name] = "" if value is None else str(value)

    return values


def parse_datetime(value: Any, name: str) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()

    if not text:
        return None

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise MetadataError(
            f"'{name}' must be an ISO 8601 date, "
            "for example 2026-01-31T09:00:00"
        ) from None


def apply_to_document(document, metadata: dict[str, Any]) -> None:
    """Write metadata into a python-docx document's core properties."""

    properties = document.core_properties

    for field in TEXT_FIELDS:
        if field in metadata:
            setattr(properties, field, metadata[field])

    for field in DATE_FIELDS:
        value = metadata.get(field)

        if value is not None:
            setattr(properties, field, value)


def apply_to_workbook(workbook, metadata: dict[str, Any]) -> None:
    """Write metadata into an openpyxl workbook's properties."""

    properties = workbook.properties

    mapping = {
        "author": "creator",
        "last_modified_by": "lastModifiedBy",
        "title": "title",
        "subject": "subject",
        "keywords": "keywords",
        "category": "category",
        "comments": "description",
    }

    for field, attribute in mapping.items():
        if field in metadata:
            setattr(properties, attribute, metadata[field])

    for field in DATE_FIELDS:
        value = metadata.get(field)

        if value is not None:
            setattr(properties, field, value)


def read_document_metadata(document) -> dict[str, Any]:
    properties = getattr(document, "core_properties", None)

    if properties is None:
        return {}

    values: dict[str, Any] = {
        field: getattr(properties, field, "")
        for field in TEXT_FIELDS
    }

    for field in DATE_FIELDS:
        value = getattr(properties, field, None)

        if value is not None:
            values[field] = value.isoformat(timespec="seconds")

    return values


def read_workbook_metadata(workbook) -> dict[str, Any]:
    properties = getattr(workbook, "properties", None)

    if properties is None:
        return {}

    mapping = {
        "author": "creator",
        "last_modified_by": "lastModifiedBy",
        "title": "title",
        "subject": "subject",
        "keywords": "keywords",
        "category": "category",
        "comments": "description",
    }

    values: dict[str, Any] = {
        field: getattr(properties, attribute, "") or ""
        for field, attribute in mapping.items()
    }

    for field in DATE_FIELDS:
        value = getattr(properties, field, None)

        if value is not None:
            values[field] = value.isoformat(timespec="seconds")

    return values
