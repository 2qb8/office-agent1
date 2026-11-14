"""Render the real window and save a screenshot (docs/window.png).

Used by the Windows build to produce the picture in the README:

    python assets/window_shot.py

It needs a desktop session, so it runs in CI rather than in a headless
build. The window is filled with a small example so the picture shows a
real run instead of an empty form.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import tkinter as tk
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))

import gui  # noqa: E402  (needs ROOT on the path first)


def main() -> int:
    root = tk.Tk()

    window = gui.OfficeAgentWindow(root)

    window.use_instruction(
        Path.home() / "Documents" / "monthly-report" / "instruction.docx"
    )

    window.language_combo.set("English")
    window.on_language()

    window.provider_var.set("Ollama (local)")
    window.on_provider_change()

    window._append("Instruction: instruction.docx", "head")
    window._append(
        "Instruction contains a job spec; running it directly.", "muted"
    )
    window._append("", None)
    window._append("[OK] read_sales: Read 4 columns x 12 rows", "ok")
    window._append("[OK] totals: Summed revenue by region", "ok")
    window._append("[OK] report: Created report.docx", "ok")
    window._append("", None)
    window._append(
        str(Path.home() / "Documents" / "monthly-report" / "output"
            / "report.docx"),
        "path",
    )
    window._set_status("Done — 2 file(s) created.", gui.SUCCESS)

    root.attributes("-topmost", True)
    root.lift()
    root.update_idletasks()
    root.update()

    time.sleep(0.8)
    root.update()

    x = root.winfo_rootx()
    y = root.winfo_rooty()
    width = root.winfo_width()
    height = root.winfo_height()

    image = ImageGrab.grab(bbox=(x, y, x + width, y + height))

    target = ROOT / "docs" / "window.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)

    print(f"saved {target} ({image.width}x{image.height})")

    root.destroy()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
