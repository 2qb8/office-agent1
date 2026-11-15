"""The render line has to say what actually happened, not a guess.

A skipped render means the step never started, which happens when the window
tests before it fail. Saying "the window tests are unaffected" there would be
a lie in the exact place a reader goes to find out what broke.
"""

from __future__ import annotations

import importlib.util
import struct
import tempfile
import unittest
import zlib
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "render_report.py"
)

spec = importlib.util.spec_from_file_location("render_report", SCRIPT)
render_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_report)


def png_bytes(width: int, height: int) -> bytes:
    """Enough of a PNG for the header reader: signature and IHDR."""

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = (
        struct.pack(">I", len(header))
        + b"IHDR"
        + header
        + struct.pack(">I", zlib.crc32(b"IHDR" + header))
    )

    return b"\x89PNG\r\n\x1a\n" + chunk


class RenderReportTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.folder = Path(self._temp.name)
        self.missing = self.folder / "window-linux.png"

    def line(self, outcome: str, image: Path | None = None) -> str:
        return render_report.build_line(
            image or self.missing,
            outcome,
            "abc1234",
        )

    def test_a_skipped_render_does_not_blame_the_picture(self):
        line = self.line("skipped")

        self.assertIn("not attempted", line)
        self.assertIn("skipped", line)
        self.assertIn("abc1234", line)

        # The two claims that would be wrong when the tests failed first.
        self.assertNotIn("unaffected", line)
        self.assertNotIn("produced nothing", line)

    def test_a_render_that_ran_and_failed_says_so(self):
        line = self.line("failure")

        self.assertIn("produced nothing", line)
        self.assertIn("ran and ended as failure", line)
        self.assertIn("unaffected", line)

    def test_success_without_a_file_is_not_dressed_up(self):
        line = self.line("success")

        self.assertIn("wrote no PNG", line)
        self.assertNotIn("produced window-linux.png", line)

    def test_a_picture_is_named_with_its_size(self):
        image = self.folder / "window-linux.png"
        image.write_bytes(png_bytes(980, 708))

        line = self.line("success", image)

        self.assertIn("produced window-linux.png, 980x708", line)
        self.assertIn(f"{image.stat().st_size} bytes", line)
        self.assertIn("ended as success", line)

    def test_a_file_that_is_not_a_png_is_reported(self):
        image = self.folder / "window-linux.png"
        image.write_bytes(b"not a png at all, just bytes")

        line = self.line("success", image)

        self.assertIn("not a readable PNG", line)
        self.assertNotIn("produced window-linux.png,", line)
