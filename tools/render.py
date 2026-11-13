from __future__ import annotations

from functools import lru_cache
from typing import Any, Iterator

from PIL import Image, ImageDraw, ImageFont


PAGE_WIDTH = 1240
MARGIN = 72
CELL_PADDING = 8
BODY_SIZE = 15

INK = "#1a1a1a"
RULE = "#c8d3dd"
HEADER_FILL = "#e6edf5"

MAX_CANVAS_HEIGHT = 8000

_FONT_FILES = {
    False: (
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ),
    True: (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
}


@lru_cache(maxsize=None)
def font(size: int, bold: bool = False):
    """A scalable font: a common system font if found, else Pillow's."""

    for candidate in _FONT_FILES[bold]:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _line_height(face) -> int:
    ascent, descent = face.getmetrics()

    return ascent + descent


def wrap_text(
    text: str,
    face,
    max_width: float,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    words = str(text).split()

    if not words:
        return []

    lines: list[str] = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()

        if (
            draw.textlength(candidate, font=face) <= max_width
            or not current
        ):
            current = candidate
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


# ----------------------------------------------------------------------
# DOCX
# ----------------------------------------------------------------------


def document_blocks(document) -> Iterator[tuple[str, Any]]:
    """Paragraphs and tables in document order."""

    try:
        blocks = document.iter_inner_content()
    except AttributeError:  # python-docx < 1.1
        for paragraph in document.paragraphs:
            yield "paragraph", paragraph

        for table in document.tables:
            yield "table", table

        return

    for block in blocks:
        yield ("table" if hasattr(block, "rows") else "paragraph"), block


def paragraph_style(
    paragraph,
    body_size: int,
) -> tuple[int, bool, str]:
    """(font size, bold, text prefix) for a paragraph, from its style."""

    name = ""

    try:
        if paragraph.style is not None and paragraph.style.name:
            name = paragraph.style.name.lower()
    except Exception:
        name = ""

    if name == "title":
        return int(body_size * 2), True, ""

    if name.startswith("heading"):
        digits = "".join(character for character in name if character.isdigit())
        level = int(digits) if digits else 1

        factor = {1: 1.8, 2: 1.45, 3: 1.25}.get(level, 1.15)

        return int(body_size * factor), True, ""

    prefix = "• " if name.startswith("list bullet") else ""

    return body_size, False, prefix


def render_document(document, scale: float = 1.0) -> Image.Image:
    """Render a DOCX's content as one continuous PNG-sized image."""

    width = max(360, int(PAGE_WIDTH * scale))
    margin = int(MARGIN * scale)
    body_size = max(9, int(BODY_SIZE * scale))

    canvas = Image.new(
        "RGB",
        (width, MAX_CANVAS_HEIGHT),
        "white",
    )

    draw = ImageDraw.Draw(canvas)

    content_width = width - 2 * margin
    y = margin

    for kind, block in document_blocks(document):
        if kind == "paragraph":
            y = _draw_paragraph(
                draw, block, y, margin, content_width, scale, body_size
            )
        else:
            y = _draw_table(
                draw, block, y, margin, content_width, scale, body_size
            )

        if y > MAX_CANVAS_HEIGHT - margin:
            break

    bottom = min(max(y + margin, margin * 2), MAX_CANVAS_HEIGHT)

    return canvas.crop((0, 0, width, bottom))


def _draw_paragraph(
    draw, paragraph, y, x, width, scale, body_size
) -> int:

    text = paragraph.text.strip()

    if not text:
        return y + int(8 * scale)

    size, bold, prefix = paragraph_style(paragraph, body_size)

    face = font(size, bold)
    line_height = _line_height(face) + int(4 * scale)

    for line in wrap_text(prefix + text, face, width, draw):
        draw.text((x, y), line, font=face, fill=INK)
        y += line_height

    return y + int(10 * scale)


def _draw_table(
    draw, table, y, x, width, scale, body_size
) -> int:

    rows = [
        [cell.text.strip() for cell in row.cells]
        for row in table.rows
    ]

    if not rows:
        return y

    columns = max(len(row) for row in rows)

    rows = [
        row + [""] * (columns - len(row))
        for row in rows
    ]

    face = font(body_size)
    header_face = font(body_size, True)
    padding = int(CELL_PADDING * scale)
    line_height = _line_height(face) + int(3 * scale)

    natural: list[float] = []

    for index in range(columns):
        longest = max(
            draw.textlength(row[index], font=face)
            for row in rows
        )

        natural.append(max(longest + 2 * padding, 60 * scale))

    total = sum(natural)

    if total > width:
        natural = [value * width / total for value in natural]

    for row_index, row in enumerate(rows):
        row_face = header_face if row_index == 0 else face

        wrapped = [
            wrap_text(value, row_face, natural[i] - 2 * padding, draw)
            for i, value in enumerate(row)
        ]

        height = max(
            max(len(cells) for cells in wrapped) * line_height,
            int(24 * scale),
        ) + 2 * padding

        if row_index == 0:
            draw.rectangle(
                [x, y, x + sum(natural), y + height],
                fill=HEADER_FILL,
            )

        cursor = x

        for index, cells in enumerate(wrapped):
            draw.rectangle(
                [cursor, y, cursor + natural[index], y + height],
                outline=RULE,
            )

            text_y = y + padding

            for line in cells:
                draw.text(
                    (cursor + padding, text_y),
                    line,
                    font=row_face,
                    fill=INK,
                )
                text_y += line_height

            cursor += natural[index]

        y += height

    return y + int(12 * scale)


# ----------------------------------------------------------------------
# XLSX
# ----------------------------------------------------------------------


def render_worksheet(
    worksheet,
    scale: float = 1.0,
    max_rows: int = 40,
    max_columns: int = 12,
) -> Image.Image:
    """Render a worksheet grid as an image."""

    row_count = min(worksheet.max_row or 1, max_rows)
    column_count = min(worksheet.max_column or 1, max_columns)

    values = [
        list(row)
        for row in worksheet.iter_rows(
            min_row=1,
            max_row=row_count,
            min_col=1,
            max_col=column_count,
            values_only=True,
        )
    ]

    body_size = max(9, int(BODY_SIZE * scale))
    face = font(body_size)
    header_face = font(body_size, True)
    padding = int(CELL_PADDING * scale)

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    line_height = _line_height(face) + int(6 * scale)

    if not values or all(
        value is None for row in values for value in row
    ):
        image = Image.new(
            "RGB",
            (int(800 * scale), int(120 * scale)),
            "white",
        )
        draw = ImageDraw.Draw(image)
        draw.text(
            (padding * 2, padding * 2),
            "Empty worksheet",
            font=face,
            fill=INK,
        )
        return image

    columns = max(len(row) for row in values)
    widths: list[float] = []

    for index in range(columns):
        longest = 0.0

        for row in values:
            cell = row[index] if index < len(row) else None
            text = "" if cell is None else str(cell)
            longest = max(longest, probe.textlength(text, font=face))

        widths.append(min(max(longest + 2 * padding, 90 * scale), 320 * scale))

    height = line_height * len(values) + 2 * padding

    image = Image.new(
        "RGB",
        (int(sum(widths)) + 2 * padding, int(height) + 2 * padding),
        "white",
    )

    draw = ImageDraw.Draw(image)

    y = padding

    for row_index, row in enumerate(values):
        row_face = header_face if row_index == 0 else face

        if row_index == 0:
            draw.rectangle(
                [padding, y, padding + sum(widths), y + line_height],
                fill=HEADER_FILL,
            )

        cursor = padding

        for index in range(columns):
            cell = row[index] if index < len(row) else None
            text = "" if cell is None else str(cell)

            draw.rectangle(
                [cursor, y, cursor + widths[index], y + line_height],
                outline=RULE,
            )
            draw.text(
                (cursor + int(4 * scale), y + int(3 * scale)),
                text,
                font=row_face,
                fill=INK,
            )

            cursor += widths[index]

        y += line_height

    return image
