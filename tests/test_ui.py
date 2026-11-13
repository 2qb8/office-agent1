from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from docx import Document

from agent import ui
from agent.runtime import AgentRuntime
from run import build_registry


SPEC = """\
steps:
  - id: write
    tool: text
    action: write
    arguments:
      output_path: output/quick.txt
      content: hi
"""


class LanguageTests(unittest.TestCase):
    def test_every_language_defines_the_same_strings(self):
        english = set(ui.STRINGS["en"])

        for code in ui.LANGUAGES:
            self.assertEqual(set(ui.STRINGS[code]), english, code)

    def test_russian_strings_are_not_empty(self):
        for key, value in ui.STRINGS["ru"].items():
            self.assertTrue(value.strip(), key)

    def test_text_falls_back_to_english(self):
        self.assertEqual(ui.text("de", "run"), "Run")
        self.assertEqual(ui.text("en", "missing_key"), "missing_key")

    def test_text_formats_values(self):
        self.assertIn("3", ui.text("en", "done", count=3))
        self.assertIn("3", ui.text("ru", "done", count=3))


class PathTests(unittest.TestCase):
    def test_output_folder_sits_beside_the_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"

            instruction = job / "instruction.docx"

            self.assertEqual(
                ui.instruction_job_dir(instruction),
                job.resolve(),
            )
            self.assertEqual(
                ui.default_output_dir(instruction),
                (job / "output").resolve(),
            )

    def test_instruction_suffixes(self):
        for name in ("a.docx", "b.txt", "c.md", "d.DOCX"):
            self.assertTrue(ui.is_instruction_file(Path(name)), name)

        self.assertFalse(ui.is_instruction_file(Path("a.xlsx")))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()

        self.path = Path(self._temp.name) / "settings.json"

    def tearDown(self):
        self._temp.cleanup()

    def test_settings_round_trip(self):
        with mock.patch.dict(
            os.environ, {ui.SETTINGS_ENV: str(self.path)}
        ):
            ui.save_settings(language="ru")

            self.assertEqual(ui.load_settings()["language"], "ru")
            self.assertEqual(ui.remembered_language(), "ru")

    def test_unknown_language_is_ignored(self):
        with mock.patch.dict(
            os.environ, {ui.SETTINGS_ENV: str(self.path)}
        ):
            self.path.write_text(
                '{"language": "de"}',
                encoding="utf-8",
            )

            self.assertEqual(ui.remembered_language(), "en")

    def test_missing_settings_file_is_empty(self):
        with mock.patch.dict(
            os.environ, {ui.SETTINGS_ENV: str(self.path)}
        ):
            self.assertEqual(ui.load_settings(), {})


class DescribeStateTests(unittest.TestCase):
    def test_reports_success_and_failure(self):
        class Result:
            def __init__(self, success, message, error=None):
                self.success = success
                self.message = message
                self.error = error

        class State:
            results = {
                "first": Result(True, "Wrote a.txt"),
                "second": Result(False, "Failed", "boom"),
            }

        self.assertEqual(
            ui.describe_state(State()),
            ["[OK] first: Wrote a.txt", "[FAILED] second: boom"],
        )


class ExplicitInstructionTests(unittest.TestCase):
    def test_runs_one_chosen_document_among_several(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)

            instruction = Document()

            for line in SPEC.strip().splitlines():
                instruction.add_paragraph(line)

            instruction.save(job / "instruction.docx")

            other = Document()
            other.add_paragraph("Unrelated notes")
            other.save(job / "other.docx")

            runtime = AgentRuntime(
                job,
                build_registry(),
                instruction_path=job / "instruction.docx",
            )

            with redirect_stdout(io.StringIO()):
                state = runtime.run()

            self.assertEqual(state.status.value, "success")
            self.assertTrue((job / "output" / "quick.txt").is_file())

    def test_folder_with_several_documents_needs_a_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory)

            for name in ("a.docx", "b.docx"):
                document = Document()
                document.add_paragraph("text")
                document.save(job / name)

            with self.assertRaises(RuntimeError):
                AgentRuntime(job, build_registry())


class GuiModuleTests(unittest.TestCase):
    def test_gui_module_compiles(self):
        source = Path(__file__).resolve().parent.parent / "gui.py"

        compile(
            source.read_text(encoding="utf-8"),
            str(source),
            "exec",
        )

    def test_gui_window_class_exists(self):
        if importlib.util.find_spec("tkinter") is None:
            self.skipTest("tkinter is not installed")

        import gui

        self.assertTrue(hasattr(gui, "OfficeAgentWindow"))
        self.assertTrue(callable(gui.main))


class GuiWindowTests(unittest.TestCase):
    """Build the real window; skipped where Tk or a display is missing."""

    def setUp(self):
        if importlib.util.find_spec("tkinter") is None:
            self.skipTest("tkinter is not installed")

        self._settings = tempfile.TemporaryDirectory()
        self.addCleanup(self._settings.cleanup)

        patcher = mock.patch.dict(
            os.environ,
            {
                ui.SETTINGS_ENV: str(
                    Path(self._settings.name) / "settings.json"
                )
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        import tkinter as tk

        try:
            self.root = tk.Tk()
        except Exception as exc:
            self.skipTest(f"no display: {exc}")

        self.root.withdraw()

        import gui

        self.window = gui.OfficeAgentWindow(self.root)
        self.root.update_idletasks()

        self.addCleanup(self._destroy)

    def _destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def test_instruction_fills_the_output_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            job.mkdir(parents=True)

            instruction = job / "instruction.docx"
            instruction.write_bytes(b"placeholder")

            self.window.use_instruction(instruction)

            self.assertIn(
                "instruction.docx",
                self.window.instruction_var.get(),
            )
            self.assertEqual(
                self.window.output_var.get(),
                str((job / "output").resolve()),
            )

    def test_language_switch_translates_the_window(self):
        self.window.language_combo.set("Русский")
        self.window.on_language()

        self.assertEqual(self.window.language, "ru")
        self.assertEqual(
            self.window.run_button.cget("text"),
            ui.text("ru", "run"),
        )
        self.assertEqual(
            self.window.instruction_label.cget("text"),
            ui.text("ru", "instruction"),
        )

    def test_run_without_instruction_explains(self):
        self.window.instruction_var.set("")
        self.window.run_job()

        self.assertEqual(
            self.window.status_var.get(),
            ui.text(self.window.language, "no_instruction"),
        )
