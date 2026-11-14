"""Draw the application icon (assets/office-agent.png and .ico).

    python assets/make_icon.py

Run it after changing the palette; the drawn result is committed so ordinary
builds do not need Pillow beyond what the project already installs.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

SIZE = 256
SCALE = 4

TOP = (37, 99, 235)
BOTTOM = (30, 64, 175)
PAPER = (248, 250, 252)
LINE = (148, 163, 184)
FOLD = (191, 219, 254)


def _mix(start: tuple[int, int, int], end: tuple[int, int, int], t: float):
    return tuple(round(a + (b - a) * t) for a, b in zip(start, end))


def draw() -> Image.Image:
    canvas = SIZE * SCALE

    background = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    painter = ImageDraw.Draw(background)

    for y in range(canvas):
        painter.line(
            [(0, y), (canvas, y)],
            fill=_mix(TOP, BOTTOM, y / (canvas - 1)) + (255,),
        )

    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, canvas - 1, canvas - 1],
        radius=round(canvas * 0.22),
        fill=255,
    )
    background.putalpha(mask)

    # The page, with a folded top-right corner.
    page = [round(canvas * 0.25), round(canvas * 0.18),
            round(canvas * 0.75), round(canvas * 0.82)]

    painter.rounded_rectangle(page, radius=round(canvas * 0.04), fill=PAPER)

    fold = round(canvas * 0.09)

    painter.polygon(
        [
            (page[2] - fold, page[1]),
            (page[2], page[1] + fold),
            (page[2] - fold, page[1] + fold),
        ],
        fill=FOLD,
    )

    width = round(canvas * 0.035)
    left = round(canvas * 0.34)
    right = round(canvas * 0.66)

    for index, y in enumerate((0.34, 0.46, 0.58)):
        end = right if index < 2 else round(canvas * 0.55)

        painter.rounded_rectangle(
            [left, round(canvas * y), end, round(canvas * y) + width],
            radius=width // 2,
            fill=LINE,
        )

    # A check mark in the lower right, the "job finished" mark.
    check = [(0.42, 0.70), (0.49, 0.77), (0.61, 0.63)]

    painter.line(
        [(round(canvas * x), round(canvas * y)) for x, y in check],
        fill=TOP,
        width=round(canvas * 0.045),
        joint="curve",
    )

    return background.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    icon = draw()

    png = HERE / "office-agent.png"
    ico = HERE / "office-agent.ico"

    icon.save(png)
    icon.save(
        ico,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    print(f"wrote {png} and {ico}")


if __name__ == "__main__":
    main()
