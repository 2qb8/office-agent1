from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook
from PIL import Image

from agent.runtime import AgentRuntime
from run import build_registry


class ActionTestBase(unittest.TestCase):
    """Shared fixtures: one temporary directory and the real registry."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()

        self.root = Path(self._temp.name)

        self.registry = build_registry()

    def tearDown(self):
        self._temp.cleanup()

    def tool(self, name: str):
        return self.registry.get(name)

    def run_tool(self, name: str, action: str, **arguments):
        result = self.tool(name).run(action, arguments)

        self.assertTrue(result.success, result.error or result.message)

        return result

    def make_image(self, name: str = "shot.png") -> Path:
        path = self.root / name

        Image.new("RGB", (64, 48), "white").save(path)

        return path

    def make_workbook(self, name: str = "book.xlsx") -> Path:
        path = self.root / name

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Data"
        sheet.append(["Region", "Revenue"])
        sheet.append(["North", 10])

        workbook.save(path)

        return path

    def make_document(self, name: str = "doc.docx") -> Path:
        path = self.root / name

        document = Document()
        document.add_paragraph("Hello")

        document.save(path)

        return path


class ExcelActionTests(ActionTestBase):
    def test_excel_inspect(self):
        result = self.run_tool(
            "excel", "inspect", path=str(self.make_workbook())
        )

        sheet = result.data["sheets"][0]

        self.assertEqual(sheet["name"], "Data")
        self.assertEqual(sheet["headers"], ["Region", "Revenue"])

    def test_excel_read_table(self):
        result = self.run_tool(
            "excel",
            "read_table",
            path=str(self.make_workbook()),
            sheet="Data",
        )

        self.assertEqual(result.data["headers"], ["Region", "Revenue"])
        self.assertEqual(result.data["rows"], [["North", 10]])
        self.assertEqual(result.data["row_count"], 1)

    def test_excel_create_workbook(self):
        path = self.root / "created.xlsx"

        self.run_tool(
            "excel",
            "create_workbook",
            output_path=str(path),
            sheets=[
                {
                    "name": "Summary",
                    "headers": ["Item", "Total"],
                    "rows": [["Widget", 2]],
                }
            ],
            metadata={"author": "Ada Lovelace"},
        )

        workbook = load_workbook(path)

        self.assertEqual(workbook["Summary"]["A1"].value, "Item")
        self.assertEqual(workbook["Summary"]["B2"].value, 2)
        self.assertEqual(workbook.properties.creator, "Ada Lovelace")

        workbook.close()

    def test_excel_append_rows(self):
        path = self.make_workbook()

        result = self.run_tool(
            "excel",
            "append_rows",
            path=str(path),
            sheet="Data",
            rows=[["South", 20], ["East", 5]],
        )

        self.assertEqual(result.data["start_row"], 3)
        self.assertEqual(result.data["rows_added"], 2)

        rows = self.run_tool(
            "excel", "read_table", path=str(path), sheet="Data"
        ).data["rows"]

        self.assertEqual(
            rows,
            [["North", 10], ["South", 20], ["East", 5]],
        )

    def test_excel_set_cell(self):
        path = self.make_workbook()

        self.run_tool(
            "excel",
            "set_cell",
            path=str(path),
            sheet="Data",
            cell="B2",
            value=99,
        )

        result = self.run_tool(
            "excel",
            "verify_cell",
            path=str(path),
            sheet="Data",
            cell="B2",
            expected=99,
        )

        self.assertEqual(result.data["actual"], 99)

    def test_excel_set_range_values(self):
        path = self.make_workbook()

        self.run_tool(
            "excel",
            "set_range_values",
            path=str(path),
            sheet="Data",
            start_cell="A4",
            values=[["West", 1], ["Central", 2]],
        )

        rows = self.run_tool(
            "excel", "read_table", path=str(path), sheet="Data"
        ).data["rows"]

        self.assertEqual(rows[-2:], [["West", 1], ["Central", 2]])

    def test_excel_merge_cells(self):
        path = self.make_workbook()

        self.run_tool(
            "excel",
            "merge_cells",
            path=str(path),
            sheet="Data",
            range="A4:B4",
            value="Combined total",
        )

        workbook = load_workbook(path)

        merged = [str(item) for item in workbook["Data"].merged_cells.ranges]

        self.assertIn("A4:B4", merged)
        self.assertEqual(workbook["Data"]["A4"].value, "Combined total")

        workbook.close()

    def test_excel_format_header(self):
        path = self.make_workbook()

        self.run_tool(
            "excel",
            "format_header",
            path=str(path),
            sheet="Data",
        )

        workbook = load_workbook(path)

        self.assertTrue(workbook["Data"]["A1"].font.bold)
        self.assertEqual(
            workbook["Data"]["A1"].fill.fill_type,
            "solid",
        )

        workbook.close()

    def test_excel_autofit(self):
        path = self.make_workbook()

        self.run_tool(
            "excel",
            "set_cell",
            path=str(path),
            sheet="Data",
            cell="A5",
            value="A rather long region name",
        )

        self.run_tool(
            "excel",
            "autofit",
            path=str(path),
            sheet="Data",
        )

        workbook = load_workbook(path)

        self.assertGreaterEqual(
            workbook["Data"].column_dimensions["A"].width,
            20,
        )

        workbook.close()

    def test_excel_add_image(self):
        path = self.make_workbook()

        self.run_tool(
            "excel",
            "add_image",
            path=str(path),
            sheet="Data",
            image_path=str(self.make_image()),
            cell="D2",
            width=64,
            height=48,
        )

        workbook = load_workbook(path)

        self.assertEqual(len(workbook["Data"]._images), 1)

        workbook.close()

    def test_excel_set_metadata(self):
        path = self.make_workbook()

        result = self.run_tool(
            "excel",
            "set_metadata",
            path=str(path),
            metadata={"title": "Quarterly totals"},
        )

        self.assertEqual(
            result.data["metadata"]["title"],
            "Quarterly totals",
        )

        workbook = load_workbook(path)

        self.assertEqual(
            workbook.properties.title,
            "Quarterly totals",
        )

        workbook.close()

    def test_excel_verify_cell(self):
        result = self.run_tool(
            "excel",
            "verify_cell",
            path=str(self.make_workbook()),
            sheet="Data",
            cell="A1",
            expected="Region",
        )

        self.assertEqual(result.data["actual"], "Region")

    def test_excel_verify_workbook(self):
        self.run_tool(
            "excel",
            "verify_workbook",
            path=str(self.make_workbook()),
            expected={
                "sheets": [
                    {
                        "name": "Data",
                        "headers": ["Region", "Revenue"],
                        "rows": [["North", 10]],
                    }
                ]
            },
        )

    def test_excel_verify_exists(self):
        result = self.run_tool(
            "excel",
            "verify_exists",
            path=str(self.make_workbook()),
        )

        self.assertGreater(result.data["size_bytes"], 0)


class WordActionTests(ActionTestBase):
    def test_word_create_document(self):
        path = self.root / "report.docx"

        self.run_tool(
            "word",
            "create_document",
            output_path=str(path),
            elements=[
                {"type": "heading", "text": "Report", "level": 1},
                {"type": "paragraph", "text": "Body text"},
            ],
            metadata={"author": "Ada Lovelace"},
        )

        document = Document(path)

        self.assertEqual(
            [paragraph.text for paragraph in document.paragraphs],
            ["Report", "Body text"],
        )
        self.assertEqual(
            document.core_properties.author,
            "Ada Lovelace",
        )

    def test_word_append_elements(self):
        path = self.make_document()

        document = Document(path)
        document.core_properties.author = "Original Author"
        document.save(path)

        self.run_tool(
            "word",
            "append_elements",
            path=str(path),
            elements=[
                {"type": "paragraph", "text": "More text"},
                {
                    "type": "table",
                    "headers": ["Item", "Total"],
                    "rows": [["Widget", 3]],
                },
            ],
        )

        document = Document(path)

        self.assertEqual(
            [paragraph.text for paragraph in document.paragraphs],
            ["Hello", "More text"],
        )
        self.assertEqual(
            document.tables[0].cell(0, 0).text,
            "Item",
        )

        # Metadata is only touched when the step supplies it.
        self.assertEqual(
            document.core_properties.author,
            "Original Author",
        )

    def test_word_replace_text(self):
        path = self.root / "template.docx"

        document = Document()
        document.add_paragraph("Dear {{client}},")
        document.add_paragraph("Total: {{total}} and {{total}}.")

        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "{{client}} summary"

        document.save(path)

        result = self.run_tool(
            "word",
            "replace_text",
            path=str(path),
            replacements={"{{client}}": "Acme", "{{total}}": "100"},
        )

        self.assertEqual(result.data["total"], 4)
        self.assertEqual(
            result.data["replacements"],
            {"{{client}}": 2, "{{total}}": 2},
        )

        updated = Document(path)

        self.assertEqual(
            [paragraph.text for paragraph in updated.paragraphs],
            ["Dear Acme,", "Total: 100 and 100."],
        )
        self.assertEqual(
            updated.tables[0].cell(0, 0).text,
            "Acme summary",
        )

    def test_word_set_metadata(self):
        path = self.make_document()

        result = self.run_tool(
            "word",
            "set_metadata",
            path=str(path),
            metadata={
                "author": "Grace Hopper",
                "title": "Notes",
            },
        )

        self.assertEqual(
            result.data["metadata"]["author"],
            "Grace Hopper",
        )

        document = Document(path)

        self.assertEqual(
            document.core_properties.author,
            "Grace Hopper",
        )
        self.assertEqual(document.core_properties.title, "Notes")

    def test_word_append_image(self):
        path = self.make_document()

        self.run_tool(
            "word",
            "append_image",
            path=str(path),
            image_path=str(self.make_image()),
            caption="Preview",
            width_inches=2,
        )

        document = Document(path)

        self.assertEqual(len(document.inline_shapes), 1)
        self.assertEqual(document.paragraphs[-1].text, "Preview")

    def test_word_read_table(self):
        path = self.root / "tables.docx"

        document = Document()

        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Region"
        table.cell(0, 1).text = "Units"
        table.cell(1, 0).text = "North"
        table.cell(1, 1).text = "10"

        document.save(path)

        result = self.run_tool(
            "word",
            "read_table",
            path=str(path),
        )

        self.assertEqual(result.data["headers"], ["Region", "Units"])
        self.assertEqual(result.data["rows"], [["North", "10"]])

    def test_word_inspect(self):
        path = self.root / "inspect.docx"

        document = Document()
        document.add_paragraph("One")
        document.add_table(rows=1, cols=1)

        document.save(path)

        result = self.run_tool(
            "word",
            "inspect",
            path=str(path),
        )

        self.assertEqual(result.data["paragraph_count"], 1)
        self.assertEqual(result.data["table_count"], 1)
        self.assertIn("author", result.data["metadata"])

    def test_word_export_text(self):
        path = self.root / "export.docx"

        document = Document()
        document.add_paragraph("Line one")

        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "A"
        table.cell(0, 1).text = "B"

        document.save(path)

        output_path = self.root / "export.txt"

        self.run_tool(
            "word",
            "export_text",
            path=str(path),
            output_path=str(output_path),
        )

        text = output_path.read_text(encoding="utf-8")

        self.assertIn("Line one", text)
        self.assertIn("A", text)

    def test_word_verify_document(self):
        path = self.root / "verify.docx"

        document = Document()
        document.add_paragraph("First")
        document.add_paragraph("Second")

        document.save(path)

        result = self.run_tool(
            "word",
            "verify_document",
            path=str(path),
            expected={"paragraphs": ["First", "Second"]},
        )

        self.assertTrue(result.data["verified"])


class TextActionTests(ActionTestBase):
    def test_text_write(self):
        path = self.root / "notes.txt"

        self.run_tool(
            "text",
            "write",
            output_path=str(path),
            content="Hello\n",
        )

        self.assertEqual(
            path.read_text(encoding="utf-8"),
            "Hello\n",
        )

    def test_text_read(self):
        path = self.root / "notes.txt"
        path.write_text("one\ntwo\n", encoding="utf-8")

        result = self.run_tool(
            "text",
            "read",
            path=str(path),
        )

        self.assertEqual(result.data["text"], "one\ntwo\n")
        self.assertEqual(result.data["line_count"], 2)

    def test_text_verify(self):
        path = self.root / "notes.txt"
        path.write_text("alpha beta\n", encoding="utf-8")

        self.run_tool(
            "text",
            "verify",
            path=str(path),
            expected_contains=["alpha"],
        )


class TableActionTests(ActionTestBase):
    HEADERS = ["Region", "Revenue"]
    ROWS = [["North", 100], ["South", 50], ["North", 25]]

    def test_table_filter(self):
        result = self.run_tool(
            "table",
            "filter",
            headers=self.HEADERS,
            rows=self.ROWS,
            column="Region",
            op="==",
            value="North",
        )

        self.assertEqual(len(result.data["rows"]), 2)

    def test_table_sort(self):
        result = self.run_tool(
            "table",
            "sort",
            headers=self.HEADERS,
            rows=self.ROWS,
            column="Revenue",
            descending=True,
        )

        self.assertEqual(
            [row[1] for row in result.data["rows"]],
            [100, 50, 25],
        )

    def test_table_select(self):
        result = self.run_tool(
            "table",
            "select",
            headers=self.HEADERS,
            rows=self.ROWS,
            columns=["Revenue"],
        )

        self.assertEqual(result.data["headers"], ["Revenue"])
        self.assertEqual(result.data["rows"][0], [100])

    def test_table_aggregate(self):
        result = self.run_tool(
            "table",
            "aggregate",
            headers=self.HEADERS,
            rows=self.ROWS,
            column="Revenue",
            op="sum",
            group_by="Region",
        )

        self.assertEqual(
            result.data["headers"],
            ["Region", "sum(Revenue)"],
        )
        self.assertIn(["North", 125], result.data["rows"])

    def test_table_limit(self):
        result = self.run_tool(
            "table",
            "limit",
            headers=self.HEADERS,
            rows=self.ROWS,
            limit=2,
            offset=1,
        )

        self.assertEqual(
            result.data["rows"],
            [["South", 50], ["North", 25]],
        )


class FilesystemActionTests(ActionTestBase):
    def test_filesystem_copy_file(self):
        source = self.root / "source.txt"
        source.write_text("copy me\n", encoding="utf-8")

        destination = self.root / "copied.txt"

        self.run_tool(
            "filesystem",
            "copy_file",
            path=str(source),
            destination_path=str(destination),
        )

        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            "copy me\n",
        )

    def test_filesystem_list_files(self):
        (self.root / "data.xlsx").write_bytes(b"x")
        (self.root / "notes.txt").write_text("hi\n", encoding="utf-8")

        result = self.run_tool(
            "filesystem",
            "list_files",
            path=str(self.root),
        )

        types = {
            item["name"]: item["type"]
            for item in result.data["files"]
        }

        self.assertEqual(types["data.xlsx"], "excel")
        self.assertEqual(types["notes.txt"], "text")


class ScreenshotActionTests(ActionTestBase):
    def test_screenshot_document(self):
        output_path = self.root / "document.png"

        result = self.run_tool(
            "screenshot",
            "document",
            path=str(self.make_document()),
            output_path=str(output_path),
        )

        self.assertTrue(output_path.is_file())
        self.assertEqual(result.data["engine"], "preview")
        self.assertGreater(result.data["width"], 0)
        self.assertGreater(result.data["height"], 0)

        with Image.open(output_path) as image:
            self.assertEqual(image.format, "PNG")

    def test_screenshot_workbook(self):
        output_path = self.root / "workbook.png"

        result = self.run_tool(
            "screenshot",
            "workbook",
            path=str(self.make_workbook()),
            output_path=str(output_path),
            sheet="Data",
        )

        self.assertTrue(output_path.is_file())
        self.assertEqual(result.data["sheet"], "Data")

        with Image.open(output_path) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 100)

    def test_screenshot_rejects_missing_source(self):
        result = self.tool("screenshot").run(
            "document",
            {
                "path": str(self.root / "missing.docx"),
                "output_path": str(self.root / "out.png"),
            },
        )

        self.assertFalse(result.success)


class ActionCoverageTests(unittest.TestCase):
    def test_every_action_is_dispatched(self):
        registry = build_registry()

        for name in registry.list_tools():
            tool = registry.get(name)

            for action in getattr(tool, "actions", ()):
                result = tool.run(action, {})

                self.assertNotIn(
                    "Unknown",
                    (result.error or "") + result.message,
                    f"{name}.{action} is not wired into run()",
                )

    def test_every_advertised_action_has_a_test(self):
        registry = build_registry()

        names = {
            name
            for name in dir(ActionTestBase) + dir(ExcelActionTests)
            + dir(WordActionTests) + dir(TextActionTests)
            + dir(TableActionTests) + dir(FilesystemActionTests)
            + dir(ScreenshotActionTests)
            if name.startswith("test_")
        }

        missing = [
            f"{tool_name}.{action}"
            for tool_name in registry.list_tools()
            for action in getattr(
                registry.get(tool_name), "actions", ()
            )
            if f"test_{tool_name}_{action}" not in names
        ]

        self.assertEqual(
            missing,
            [],
            "advertised actions without a test: " + ", ".join(missing),
        )


INSTRUCTION = """\
Evidence job

```yaml
title: Evidence job

metadata:
  author: Ada Lovelace

steps:
  - id: notes
    tool: text
    action: read
    arguments:
      path: inputs/notes.txt

  - id: report
    tool: word
    action: create_document
    arguments:
      output_path: output/report.docx
      elements:
        - type: heading
          text: Report
          level: 1
        - type: paragraph
          text: $notes.text

  - id: preview
    tool: screenshot
    action: document
    arguments:
      path: output/report.docx
      output_path: evidence/report.png

  - id: attach
    tool: word
    action: append_image
    arguments:
      path: output/report.docx
      image_path: evidence/report.png
      caption: Report preview
      width_inches: 4

  - id: footer
    tool: word
    action: append_elements
    arguments:
      path: output/report.docx
      elements:
        - type: paragraph
          text: Generated automatically.

  - id: export
    tool: word
    action: export_text
    arguments:
      path: output/report.docx
      output_path: output/report.txt

  - id: reread
    tool: text
    action: read
    arguments:
      path: output/report.txt
```
"""


class TextReadAppendElementsJobTests(ActionTestBase):
    def test_job_reads_text_and_appends_to_a_document(self):
        job = self.root / "evidence-job"

        for name in ("inputs", "output", "evidence"):
            (job / name).mkdir(parents=True)

        (job / "inputs" / "notes.txt").write_text(
            "The numbers look good.\n",
            encoding="utf-8",
        )

        instruction = Document()

        for line in INSTRUCTION.strip().splitlines():
            instruction.add_paragraph(line)

        instruction.save(job / "instruction.docx")

        runtime = AgentRuntime(job, build_registry())

        state = runtime.run()

        self.assertEqual(state.status.value, "success", state.failed_steps)
        self.assertEqual(
            state.completed_steps,
            [
                "notes",
                "report",
                "preview",
                "attach",
                "footer",
                "export",
                "reread",
            ],
        )

        # text.read fed the document body ...
        report = Document(job / "output" / "report.docx")

        self.assertEqual(
            [
                paragraph.text.strip()
                for paragraph in report.paragraphs
                if paragraph.text.strip()
            ],
            [
                "Report",
                "The numbers look good.",
                "Report preview",
                "Generated automatically.",
            ],
        )

        # word.append_elements added the footer, append_image the preview.
        self.assertEqual(len(report.inline_shapes), 1)

        # The job-level metadata reached every DOCX step.
        self.assertEqual(
            report.core_properties.author,
            "Ada Lovelace",
        )

        # The automated screenshot landed in evidence/.
        screenshot = job / "evidence" / "report.png"

        self.assertTrue(screenshot.is_file())

        with Image.open(screenshot) as image:
            self.assertEqual(image.format, "PNG")
            self.assertGreater(image.width, 0)

        # text.read again, this time on the exported report.
        export = (job / "output" / "report.txt").read_text(
            encoding="utf-8"
        )

        self.assertIn("Generated automatically.", export)
        self.assertIn("Report preview", export)


if __name__ == "__main__":
    unittest.main()
