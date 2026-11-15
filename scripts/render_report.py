"""Say in one line whether the Linux window render produced a picture.

    python scripts/render_report.py docs/window-linux.png \\
        --out docs/render-linux.txt --outcome success --commit abc1234

The render step is allowed to fail: a PNG is not worth failing a release
for. It must not be silent either — a run that says PASS while the window
could not be drawn is the kind of green tick this project keeps trying to
avoid. The run log needs an account, so the plain fact goes into a committed
file that anyone can read.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> tuple[int, int] | None:
    """Width and height from the IHDR chunk, or None if it is not a PNG."""

    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None

    if len(header) < 24 or header[:8] != PNG_SIGNATURE:
        return None

    return struct.unpack(">II", header[16:24])


def build_line(
    image: Path,
    outcome: str,
    commit: str,
) -> str:
    where = f" at {commit}" if commit else ""

    if not image.is_file():
        return (
            f"Window render (Linux): produced nothing; the render step ended "
            f"as {outcome}{where}. The window tests are unaffected — this "
            f"only means the picture could not be drawn.\n"
        )

    size = png_size(image)

    if size is None:
        return (
            f"Window render (Linux): wrote {image.name}, but it is not a "
            f"readable PNG; the render step ended as {outcome}{where}.\n"
        )

    width, height = size

    return (
        f"Window render (Linux): produced {image.name}, {width}x{height}, "
        f"{image.stat().st_size} bytes; the render step ended as "
        f"{outcome}{where}.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="the PNG the render step should write")
    parser.add_argument(
        "--out",
        default="docs/render-linux.txt",
        help="where to write the one-line report",
    )
    parser.add_argument(
        "--outcome",
        default="unknown",
        help="the render step's outcome, as CI reports it",
    )
    parser.add_argument(
        "--commit",
        default="",
        help="short commit the run belongs to",
    )

    arguments = parser.parse_args()

    line = build_line(Path(arguments.image), arguments.outcome, arguments.commit)

    target = Path(arguments.out)

    if not target.is_absolute():
        target = Path.cwd() / target

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(line, encoding="utf-8")

    print(line, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
