"""Write Word and Excel files the same way every time.

Two runs over the same inputs should produce the same bytes — that is what
lets a golden-output regression pack compare hashes instead of eyeballing
documents. An OOXML file carries two clocks: the timestamp of every zip
member, and the core properties inside ``docProps/core.xml``. The
properties are pinned where a file is created (see
:func:`agent.metadata.pin_default_dates`), and the archive is rewritten here
with fixed member timestamps and a fixed order.

Nothing in the document itself is touched: a plan that sets ``created`` or
``modified`` keeps the date it asked for.
"""

from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# A date early enough to be recognisably "not the run's clock", and valid
# for the zip format, which cannot store anything before 1980.
STABLE_DATE = (2000, 1, 1, 0, 0, 0)

OFFICE_SUFFIXES = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx"}

# Readers look these up by part name rather than by position, but the
# package format opens with the content types and the root relationships,
# so keep them where every writer puts them.
LEADING_PARTS = ("[Content_Types].xml", "_rels/.rels")

CORE_PART = "docProps/core.xml"

_MODIFIED = re.compile(
    rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)"
)


def timestamp(value) -> str | None:
    """Format a property date the way OOXML writes it."""

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)

    return value.isoformat(timespec="seconds") + "Z"


def _order(name: str) -> tuple[int, str]:
    if name in LEADING_PARTS:
        return (LEADING_PARTS.index(name), "")

    return (len(LEADING_PARTS), name)


def _pin_modified(data: bytes, stamp: str) -> bytes:
    """Replace the modified stamp, leaving the rest of the part alone."""

    return _MODIFIED.sub(
        lambda match: match.group(1) + stamp.encode("utf-8") + match.group(2),
        data,
        count=1,
    )


def stabilize(path, modified=None) -> Path:
    """Rewrite an OOXML file with fixed member timestamps and order.

    Safe to call twice, and a no-op for anything that is not a zip — a
    plan can name an output ``.docx`` and have the run fail before it is
    written, and this must not turn that into a different error.
    """

    path = Path(path)

    if path.suffix.lower() not in OFFICE_SUFFIXES or not path.is_file():
        return path

    try:
        with zipfile.ZipFile(path) as archive:
            members = {
                info.filename: archive.read(info)
                for info in archive.infolist()
                if not info.is_dir()
            }
    except (OSError, zipfile.BadZipFile):
        return path

    stamp = timestamp(modified)

    if stamp and CORE_PART in members:
        members[CORE_PART] = _pin_modified(members[CORE_PART], stamp)

    temporary = path.with_name(path.name + ".stable")

    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members, key=_order):
            info = zipfile.ZipInfo(name, date_time=STABLE_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o600 << 16

            archive.writestr(info, members[name])

    os.replace(temporary, path)

    return path


def save_workbook(workbook, path) -> Path:
    """Save an openpyxl workbook, then make the bytes reproducible.

    openpyxl rewrites ``modified`` to the current time as it saves, whatever
    the workbook's properties said, so the intended value is put back after
    the fact — a plan that set a date still gets the date it asked for.
    """

    modified = getattr(workbook.properties, "modified", None)

    workbook.save(path)

    return stabilize(path, modified=modified)


def save_document(document, path) -> Path:
    """Save a python-docx document, then make the bytes reproducible."""

    properties = getattr(document, "core_properties", None)
    modified = getattr(properties, "modified", None) if properties else None

    document.save(path)

    return stabilize(path, modified=modified)
