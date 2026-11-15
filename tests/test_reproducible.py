"""Two identical runs must write identical files.

That is what a golden-output pack needs: the bytes of a generated DOCX or
XLSX should depend on the inputs and the plan, never on the clock.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from docx import Document
from openpyxl import load_workbook

from agent.registry import build_registry
from agent.runtime import AgentRuntime


SPEC = """\
title: Weekly pack
steps:
  - id: book
    tool: excel
    action: create_workbook
    arguments:
      output_path: output/pack.xlsx
      sheets:
        - name: Sales
          headers:
            - Region
            - Units
          rows:
            - [LatAm, 32]
            - [EMEA, 18]
  - id: more
    tool: excel
    action: append_rows
    arguments:
      path: output/pack.xlsx
      sheet: Sales
      rows:
        - [APAC, 7]
  - id: header
    tool: excel
    action: format_header
    arguments:
      path: output/pack.xlsx
      sheet: Sales
  - id: memo
    tool: word
    action: create_document
    arguments:
      output_path: output/memo.docx
      elements:
        - type: heading
          text: Weekly pack
          level: 1
        - type: paragraph
          text: Three regions, three rows.
        - type: table
          headers: [Region, Units]
          rows:
            - [LatAm, 32]
            - [EMEA, 18]
  - id: tidy
    tool: word
    action: append_elements
    arguments:
      path: output/memo.docx
      elements:
        - type: paragraph
          text: End of the pack.
  - id: notes
    tool: text
    action: write
    arguments:
      output_path: output/notes.md
      headers: [Region, Units]
      rows:
        - [LatAm, 32]
"""

DATED_SPEC = """\
title: Dated pack
steps:
  - id: book
    tool: excel
    action: create_workbook
    arguments:
      output_path: output/dated.xlsx
      metadata:
        title: Dated pack
        created: 2026-01-31T09:00:00
        modified: 2026-01-31T09:00:00
      sheets:
        - name: Sales
          headers:
            - Region
            - Units
          rows:
            - [LatAm, 32]
"""


class ReproducibleTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.root = Path(self._temp.name)

    def run_job(self, name: str, spec: str) -> Path:
        job = self.root / name
        job.mkdir()

        document = Document()

        for line in spec.splitlines():
            document.add_paragraph(line)

        document.save(job / "instruction.docx")

        runtime = AgentRuntime(job, build_registry())

        with redirect_stdout(io.StringIO()):
            state = runtime.run()

        self.assertEqual(state.status.value, "success")

        return job

    @staticmethod
    def hashes(job: Path) -> dict[str, str]:
        output = job / "output"

        return {
            path.relative_to(output).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }

    def test_two_runs_write_the_same_bytes(self):
        first = self.run_job("first", SPEC)

        # A different clock: any timestamp left in the files would show up.
        time.sleep(1.1)

        second = self.run_job("second", SPEC)

        first_hashes = self.hashes(first)
        second_hashes = self.hashes(second)

        self.assertEqual(
            sorted(first_hashes),
            ["memo.docx", "notes.md", "pack.xlsx"],
        )
        self.assertEqual(first_hashes, second_hashes)

    def test_the_archive_layout_is_stable(self):
        job = self.run_job("archives", SPEC)

        for name in ("pack.xlsx", "memo.docx"):
            with self.subTest(file=name):
                import zipfile

                with zipfile.ZipFile(job / "output" / name) as archive:
                    names = archive.namelist()
                    stamps = {info.date_time for info in archive.infolist()}

                self.assertEqual(names[0], "[Content_Types].xml")
                self.assertEqual(stamps, {(2000, 1, 1, 0, 0, 0)})

    def test_a_date_from_the_plan_is_kept(self):
        job = self.run_job("dated", DATED_SPEC)

        workbook = load_workbook(job / "output" / "dated.xlsx")

        try:
            created = workbook.properties.created
            modified = workbook.properties.modified
        finally:
            workbook.close()

        self.assertEqual(
            created.isoformat(timespec="seconds"),
            "2026-01-31T09:00:00",
        )
        self.assertEqual(
            modified.isoformat(timespec="seconds"),
            "2026-01-31T09:00:00",
        )
