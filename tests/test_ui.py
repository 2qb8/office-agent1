from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from docx import Document

from agent import ai_config, desktop, ui
from agent.llm import LLM
from agent.registry import build_registry
from agent.runtime import AgentRuntime


SPEC = """\
steps:
  - id: write
    tool: text
    action: write
    arguments:
      output_path: output/quick.txt
      content: hi
"""

# What the stub model replies with when it is asked to plan prose.
AI_PLAN = {
    "goal": "write a note",
    "steps": [
        {
            "id": "write",
            "description": "write the note",
            "tool": "text",
            "action": "write",
            "arguments": {
                "output_path": "output/ai-note.txt",
                "content": "planned by the stub",
            },
            "depends_on": [],
        }
    ],
}

PROSE = "Write a short note to output/ai-note.txt."


class StubPlanner(LLM):
    """A plan-returning model with no network behind it."""

    def __init__(self, payload: dict = AI_PLAN) -> None:
        self.payload = payload
        self.prompts: list = []

    def generate(self, prompt, temperature=0.0, max_tokens=None) -> str:
        self.prompts.append(prompt)

        return json.dumps(self.payload)


class UnusedPlanner:
    """A client factory that fails the test if the planner asks for one."""

    def __init__(self) -> None:
        self.called = False

    def __call__(self):
        self.called = True
        raise AssertionError(
            "the AI planner must not run when the instruction has a spec"
        )


def prompt_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt

    return "\n".join(
        str(message.get("content", "")) for message in prompt
    )


def write_docx(path: Path, lines) -> Path:
    document = Document()

    for line in lines:
        document.add_paragraph(line)

    document.save(path)

    return path


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

    def test_ai_settings_round_trip(self):
        values = {
            "provider": "ollama",
            "base_url": "http://localhost:11434/v1",
            "model": "qwen2.5:3b",
            "api_key": "secret",
        }

        with mock.patch.dict(
            os.environ, {ui.SETTINGS_ENV: str(self.path)}
        ):
            ui.save_ai(values)

            self.assertEqual(ui.remembered_ai(), values)

            if os.name == "posix":
                self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_missing_ai_settings_are_empty(self):
        with mock.patch.dict(
            os.environ, {ui.SETTINGS_ENV: str(self.path)}
        ):
            self.assertEqual(ui.remembered_ai(), {})


class AiEnvironmentTests(unittest.TestCase):
    def test_values_reach_the_planner_and_clear_again(self):
        with mock.patch.dict(os.environ, {},
                             clear=False):
            ai_config.apply_environment(
                {
                    "provider": "ollama",
                    "base_url": "http://localhost:11434/v1",
                    "model": "qwen2.5:3b",
                    "api_key": "",
                }
            )

            self.assertEqual(os.environ["LLM_PROVIDER"], "ollama")
            self.assertNotIn("LLM_API_KEY", os.environ)
            self.assertTrue(ai_config.configured())

            ai_config.apply_environment({})

            self.assertNotIn("LLM_PROVIDER", os.environ)
            self.assertFalse(ai_config.configured())

    def test_from_values_strips_whitespace(self):
        config = ai_config.from_values(
            {
                "provider": " OpenAI ",
                "base_url": " https://api.openai.com/v1 ",
                "model": " gpt-4o-mini ",
                "api_key": " key ",
            }
        )

        self.assertEqual(config.provider, "openai")
        self.assertEqual(config.model, "gpt-4o-mini")
        self.assertEqual(config.api_key, "key")


class RegistryTests(unittest.TestCase):
    def test_default_registry_has_every_tool(self):
        self.assertEqual(
            build_registry().list_tools(),
            ["excel", "filesystem", "screenshot", "table", "text", "word"],
        )


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


class DesktopRunPathTests(unittest.TestCase):
    """The body of the window's Run button, without opening a window."""

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.job = Path(self._temp.name) / "job"
        self.job.mkdir(parents=True)

        patcher = mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "",
                "LLM_BASE_URL": "",
                "LLM_MODEL": "",
                "LLM_API_KEY": "",
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_provider(self) -> None:
        ai_config.apply_environment(
            {
                "provider": "openai",
                "base_url": "https://example.test/v1",
                "model": "stub-model",
                "api_key": "test-key",
            }
        )

    def test_prose_instruction_is_planned_by_the_configured_model(self):
        instruction = write_docx(self.job / "instruction.docx", [PROSE])

        self.use_provider()

        stub = StubPlanner()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=stub,
        ):
            with redirect_stdout(io.StringIO()):
                kind, state, outputs = desktop.run_instruction(
                    instruction
                )

        self.assertEqual(kind, "done")
        self.assertEqual(state.status.value, "success")

        note = self.job / "output" / "ai-note.txt"

        self.assertEqual(
            note.read_text(encoding="utf-8").strip(),
            "planned by the stub",
        )
        self.assertEqual(outputs, [str(note.resolve())])

        self.assertEqual(len(stub.prompts), 1)
        self.assertIn(PROSE, prompt_text(stub.prompts[0]))

    def test_spec_instruction_never_calls_the_model(self):
        instruction = write_docx(
            self.job / "instruction.docx",
            SPEC.strip().splitlines(),
        )

        self.use_provider()

        factory = UnusedPlanner()

        with mock.patch("agent.runtime.try_create_llm", factory):
            with redirect_stdout(io.StringIO()):
                kind, state, outputs = desktop.run_instruction(
                    instruction
                )

        self.assertFalse(factory.called)
        self.assertEqual(kind, "done")
        self.assertEqual(
            (self.job / "output" / "quick.txt")
            .read_text(encoding="utf-8")
            .strip(),
            "hi",
        )

    def test_prose_without_a_provider_reports_the_missing_spec(self):
        instruction = write_docx(self.job / "instruction.docx", [PROSE])

        with redirect_stdout(io.StringIO()):
            kind, payload, outputs = desktop.run_instruction(instruction)

        self.assertEqual(kind, "nospec")
        self.assertIsNone(payload)
        self.assertEqual(outputs, [])


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
                ),
                "LLM_PROVIDER": "",
                "LLM_BASE_URL": "",
                "LLM_MODEL": "",
                "LLM_API_KEY": "",
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

    def test_ai_section_opens_on_a_preset(self):
        self.assertIn(
            self.window.provider_var.get(),
            self.window.provider_by_label,
        )
        self.assertTrue(self.window.ai_status_var.get().strip())

    def _wait_for_run(self, timeout: float = 25.0) -> bool:
        """Pump the window until the worker thread reports back."""

        deadline = time.time() + timeout

        while time.time() < deadline:
            self.root.update()

            if not self.window.running:
                return True

            time.sleep(0.02)

        return False

    def _use_openai(self) -> None:
        self.window.provider_var.set("OpenAI")
        self.window.on_provider_change()
        self.window.api_key_var.set("test-key")

    def test_run_plans_prose_with_the_configured_model(self):
        job = Path(self._settings.name) / "ai-job"
        job.mkdir()

        instruction = write_docx(job / "instruction.docx", [PROSE])

        self.window.use_instruction(instruction)
        self._use_openai()

        stub = StubPlanner()

        with mock.patch(
            "agent.runtime.try_create_llm",
            return_value=stub,
        ):
            self.window.run_job()

            self.assertTrue(self._wait_for_run(), "the run never finished")

        self.assertEqual(len(stub.prompts), 1)
        self.assertIn(PROSE, prompt_text(stub.prompts[0]))

        self.assertEqual(
            self.window.status_var.get(),
            ui.text(self.window.language, "done", count=1),
        )
        self.assertIn("[OK] write", self.window.log.get("1.0", "end"))
        self.assertTrue((job / "output" / "ai-note.txt").is_file())

    def test_run_keeps_the_spec_when_a_provider_is_configured(self):
        job = Path(self._settings.name) / "spec-job"
        job.mkdir()

        instruction = write_docx(
            job / "instruction.docx",
            SPEC.strip().splitlines(),
        )

        self.window.use_instruction(instruction)
        self._use_openai()

        factory = UnusedPlanner()

        with mock.patch("agent.runtime.try_create_llm", factory):
            self.window.run_job()

            self.assertTrue(self._wait_for_run(), "the run never finished")

        self.assertFalse(factory.called)
        self.assertEqual(
            self.window.status_var.get(),
            ui.text(self.window.language, "done", count=1),
        )
        self.assertTrue((job / "output" / "quick.txt").is_file())

    def test_ai_choice_is_saved_and_becomes_usable(self):
        self.window.provider_var.set("Ollama (local)")
        self.window.on_provider_change()
        self.window._persist_ai()

        saved = ui.remembered_ai()

        self.assertEqual(saved["provider"], "ollama")
        self.assertEqual(saved["base_url"], "http://localhost:11434/v1")
        self.assertEqual(saved["model"], "qwen2.5:3b")
        self.assertTrue(ai_config.configured())
