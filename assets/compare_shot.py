"""Compare a fresh window screenshot with the committed reference.

    python assets/compare_shot.py docs/window.png docs/window-golden.png

CI renders the window on Windows and runs this, so a layout regression (a
button that lost its padding, a card that stopped filling the width) shows
up as a failed step with ``docs/window-diff.png`` marking the pixels that
moved. A missing reference is not a failure: the first green run just says
so.

When the change is intentional, refresh the reference and commit it:

    cp docs/window.png docs/window-golden.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

# Share of pixels that may differ before it counts as a layout change. Font
# rendering shifts by a pixel between runner images; a moved button is far
# more than this.
TOLERANCE = 0.02

# Per-channel difference below this is anti-aliasing, not a change.
CHANNEL_FLOOR = 24

DIFF_PATH = Path("docs/window-diff.png")


def compare(actual: Path, golden: Path) -> int:
    if not actual.is_file():
        print(f"No screenshot at {actual}; nothing to compare.")
        return 0

    if not golden.is_file():
        print(f"No reference at {golden}; skipping the comparison.")
        print(f"To start one: cp {actual} {golden}")
        return 0

    with Image.open(actual) as image:
        fresh = image.convert("RGB")

    with Image.open(golden) as image:
        reference = image.convert("RGB")

    if fresh.size != reference.size:
        print(
            f"Window size changed: {reference.size[0]}x{reference.size[1]} "
            f"-> {fresh.size[0]}x{fresh.size[1]}"
        )
        print(f"If that is intended: cp {actual} {golden}")
        return 1

    difference = ImageChops.difference(fresh, reference)

    # Collapse to one channel and drop anti-aliasing: a pixel counts only
    # when some channel moved further than the floor.
    marked = difference.convert("L").point(
        lambda value: 255 if value > CHANNEL_FLOOR else 0
    )

    total = fresh.size[0] * fresh.size[1]
    # The first histogram bin holds the unchanged pixels.
    changed = total - marked.histogram()[0] if total else 0

    share = changed / total if total else 0.0

    print(f"Changed pixels: {changed} of {total} ({share:.2%})")

    if share <= TOLERANCE:
        print("Layout matches the reference.")
        return 0

    # Paint the changed pixels red over the fresh screenshot.
    overlay = fresh.copy()
    red = Image.new("RGB", fresh.size, (220, 38, 38))
    overlay.paste(red, (0, 0), marked)
    DIFF_PATH.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(DIFF_PATH)

    print(f"Wrote {DIFF_PATH} with the changed pixels in red.")
    print(f"If the change is intended: cp {actual} {golden} and commit it.")

    return 1


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    return compare(Path(argv[0]), Path(argv[1]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
