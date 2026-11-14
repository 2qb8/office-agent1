from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import requests
from docx import Document

from agent import ai_config, desktop, ui
from agent.llm import LLM, LLMError
from agent.llm_factory import resolve_settings
from agent.registry import build_registry
from agent.runtime import AgentRuntime


# Set to 1 where the window must really be exercised (the Windows build):
# a missing Tk or display then fails the test instead of skipping it.
REQUIRE_GUI_ENV = "OFFICE_AGENT_REQUIRE_GUI"


def gui_is_required() -> bool:
    value = os.environ.get(REQUIRE_GUI_ENV, "").strip().lower()

    return value in {"1", "true", "yes", "on"}


def unavailable_gui(test: unittest.TestCase, reason: str) -> None:
    """Skip the window test, or fail it when this run must cover it."""

    if gui_is_required():
        test.fail(
            "this run must exercise the desktop window, but "
            f"{reason}. Set {REQUIRE_GUI_ENV}=0 to allow skipping."
        )

    test.skipTest(reason)


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

# What the planner must see after the window saves this selection: OpenAI's
# preset endpoint and model, plus the key typed into the window.
OPENAI_ENV = {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_key": "test-key",
}


def planner_settings() -> dict[str, str]:
    """The configuration the planner would read in this process."""

    settings = resolve_settings()

    return {
        "provider": settings["provider"],
        "base_url": settings["base_url"],
        "model": settings["model"],
        "api_key": settings["api_key"],
    }


class StubPlanner(LLM):
    """A plan-returning model with no network behind it."""

    def __init__(self, payload: dict = AI_PLAN) -> None:
        self.payload = payload
        self.prompts: list = []

    def generate(self, prompt, temperature=0.0, max_tokens=None) -> str:
        self.prompts.append(prompt)

        return json.dumps(self.payload)


class ConfigCheckingFactory:
    """Stands in for try_create_llm without ignoring the wiring.

    The real factory builds a client from the environment the window wrote,
    so this one refuses to hand out the stub unless the planner sees exactly
    the provider, endpoint, model and key the window selected. A window that
    stops saving its settings makes the run fail here instead of quietly
    passing the test.
    """

    def __init__(self, client: LLM, expected: dict[str, str]) -> None:
        self.client = client
        self.expected = expected
        self.calls = 0

    def __call__(self) -> LLM:
        self.calls += 1

        actual = planner_settings()

        if actual != self.expected:
            raise AssertionError(
                "the window's AI settings never reached the planner:\n"
                f"  expected: {self.expected}\n"
                f"  actual:   {actual}"
            )

        return self.client


class UnusedPlanner:
    """A client factory that fails the test if the planner asks for one."""

    def __init__(self) -> None:
        self.called = False

    def __call__(self):
        self.called = True
        raise AssertionError(
            "the AI planner must not run when the instruction has a spec"
        )


class FakeHttpResponse:
    """The shape requests.post returns, without a socket."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def chat_reply(content: str = "OK") -> dict:
    return {"choices": [{"message": {"content": content}}]}


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


THREE_STEPS = """\
steps:
  - id: first
    tool: text
    action: write
    arguments:
      output_path: output/a.txt
      content: one
  - id: second
    tool: text
    action: write
    arguments:
      output_path: output/b.txt
      content: two
  - id: third
    tool: text
    action: write
    arguments:
      output_path: output/c.txt
      content: three
"""


class PlanAndStopTests(unittest.TestCase):
    """Reviewing a plan, and stopping before it finishes."""

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

        self.instruction = write_docx(
            self.job / "instruction.docx",
            THREE_STEPS.strip().splitlines(),
        )

    def test_planning_writes_nothing_and_lists_every_step(self):
        with redirect_stdout(io.StringIO()):
            runtime, kind, plan = desktop.plan_instruction(self.instruction)

        self.assertEqual(kind, "plan")
        self.assertIsNotNone(runtime)
        self.assertEqual(
            [(step.id, step.tool, step.action) for step in plan.steps],
            [
                ("first", "text", "write"),
                ("second", "text", "write"),
                ("third", "text", "write"),
            ],
        )
        # Validation creates the empty output folder; planning writes nothing.
        self.assertEqual(list((self.job / "output").iterdir()), [])
        self.assertFalse((self.job / "report.json").exists())

    def test_stopping_after_a_step_skips_the_rest(self):
        with redirect_stdout(io.StringIO()):
            runtime, kind, plan = desktop.plan_instruction(self.instruction)

        cancel = threading.Event()
        seen: list[tuple[int, int]] = []

        def progress(done: int, total: int, label: str) -> None:
            seen.append((done, total))

            if done == 1:
                cancel.set()

        with redirect_stdout(io.StringIO()):
            kind, state, outputs = desktop.execute_plan(
                runtime,
                plan,
                progress=progress,
                cancel=cancel,
            )

        self.assertEqual(kind, "done")
        self.assertEqual(state.status.value, "skipped")
        self.assertEqual(state.failed_steps, [])
        self.assertEqual(
            [step.status.value for step in plan.steps],
            ["success", "skipped", "skipped"],
        )
        self.assertTrue((self.job / "output" / "a.txt").is_file())
        self.assertFalse((self.job / "output" / "b.txt").exists())
        self.assertFalse((self.job / "output" / "c.txt").exists())
        self.assertEqual(outputs, [str((self.job / "output" / "a.txt").resolve())])
        self.assertEqual(seen[0], (0, 3))
        self.assertIn((1, 3), seen)

    def test_progress_counts_every_step_to_the_end(self):
        seen: list[tuple[int, int]] = []

        with redirect_stdout(io.StringIO()):
            runtime, kind, plan = desktop.plan_instruction(self.instruction)
            kind, state, outputs = desktop.execute_plan(
                runtime,
                plan,
                progress=lambda done, total, label: seen.append(
                    (done, total)
                ),
            )

        self.assertEqual(state.status.value, "success")
        self.assertEqual(seen[0], (0, 3))
        self.assertEqual(seen[-1], (3, 3))


class SelfTestTests(unittest.TestCase):
    """What `office-agent-gui.exe --self-test` reports to CI."""

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

    def test_a_successful_run_reports_zero_and_writes_what_it_did(self):
        instruction = write_docx(
            self.job / "instruction.docx",
            SPEC.strip().splitlines(),
        )

        with redirect_stdout(io.StringIO()):
            code = desktop.self_test(instruction)

        self.assertEqual(code, 0)

        report = (self.job / "self-test.txt").read_text(encoding="utf-8")

        self.assertIn("result: done", report)
        self.assertIn("status: success", report)
        self.assertIn("[OK] write: ", report)
        self.assertTrue((self.job / "output" / "quick.txt").is_file())
        self.assertIn(str(self.job / "output" / "quick.txt"), report)

    def test_a_plain_prose_instruction_without_ai_reports_failure(self):
        instruction = write_docx(
            self.job / "instruction.docx",
            [PROSE],
        )

        with redirect_stdout(io.StringIO()):
            code = desktop.self_test(instruction)

        self.assertEqual(code, 1)
        self.assertIn(
            "result: nospec",
            (self.job / "self-test.txt").read_text(encoding="utf-8"),
        )


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
        ai_config.apply_environment(OPENAI_ENV)

    def assert_done(self, kind: str, payload) -> None:
        """A failed run reports the exception, not just 'error'."""

        if kind != "done":
            raise AssertionError(
                f"the run ended as {kind!r}: {payload}"
            )

    def test_prose_instruction_is_planned_by_the_configured_model(self):
        instruction = write_docx(self.job / "instruction.docx", [PROSE])

        self.use_provider()

        stub = StubPlanner()
        factory = ConfigCheckingFactory(stub, OPENAI_ENV)

        with mock.patch("agent.runtime.try_create_llm", factory):
            with redirect_stdout(io.StringIO()):
                kind, state, outputs = desktop.run_instruction(
                    instruction
                )

        self.assert_done(kind, state)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(planner_settings(), OPENAI_ENV)
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
        self.assertEqual(planner_settings(), OPENAI_ENV)
        self.assert_done(kind, state)
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


class ConnectionTestTests(unittest.TestCase):
    """The AI panel's Test connection, through the real HTTP client."""

    def test_a_working_reply_reports_the_model_output(self):
        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeHttpResponse(200, chat_reply("OK")),
        ) as post:
            check = desktop.test_ai_connection(OPENAI_ENV)

        self.assertTrue(check.ok)
        self.assertEqual(check.summary, "OK")
        self.assertIsNone(check.status)

        url = post.call_args.args[0]
        options = post.call_args.kwargs

        self.assertEqual(
            url, "https://api.openai.com/v1/chat/completions"
        )
        self.assertEqual(
            options["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(options["json"]["model"], "gpt-4o-mini")
        self.assertEqual(options["json"]["max_tokens"], 8)

    def test_a_rejected_key_reports_the_http_status(self):
        body = '{"error": {"message": "Incorrect API key provided"}}'

        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeHttpResponse(401, text=body),
        ):
            check = desktop.test_ai_connection(OPENAI_ENV)

        self.assertFalse(check.ok)
        self.assertEqual(check.status, 401)
        self.assertEqual(
            check.detail,
            '{"error": {"message": "Incorrect API key provided"}}',
        )
        self.assertEqual(
            check.summary,
            'HTTP 401: {"error": {"message": "Incorrect API key provided"}}',
        )

    def test_an_unreachable_endpoint_reports_the_network_error(self):
        with mock.patch(
            "agent.llm.requests.post",
            side_effect=requests.exceptions.ConnectionError(
                "getaddrinfo failed"
            ),
        ):
            check = desktop.test_ai_connection(OPENAI_ENV)

        self.assertFalse(check.ok)
        self.assertIsNone(check.status)
        self.assertEqual(check.kind, "network")
        self.assertEqual(check.summary, "network error: getaddrinfo failed")


class ErrorLineTests(unittest.TestCase):
    """The short line comes from fields, never from the client's wording."""

    def test_http_status_with_the_provider_message(self):
        error = LLMError(
            "All configured LLM models failed:\n whatever",
            status=401,
            detail='{"error": "bad key"}',
        )

        self.assertEqual(error.reason, 'HTTP 401: {"error": "bad key"}')
        self.assertEqual(
            LLMError("x", status=503, detail="overloaded").reason,
            "HTTP 503: overloaded",
        )

    def test_network_failure_without_a_status(self):
        error = LLMError("wrapped text", detail="timed out", kind="network")

        self.assertEqual(error.reason, "network error: timed out")

    def test_unusable_reply_keeps_the_provider_message(self):
        error = LLMError(
            "wrapped text",
            detail="invalid successful response: no choices",
            kind="response",
        )

        self.assertEqual(
            error.reason,
            "invalid successful response: no choices",
        )


class ConfigCheckingFactoryTests(unittest.TestCase):
    def test_the_factory_refuses_a_client_for_other_settings(self):
        """Without this the window tests could pass on a broken wiring."""

        with mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "",
                "LLM_BASE_URL": "",
                "LLM_MODEL": "",
                "LLM_API_KEY": "",
            },
        ):
            factory = ConfigCheckingFactory(StubPlanner(), OPENAI_ENV)

            with self.assertRaises(AssertionError) as caught:
                factory()

        self.assertIn("never reached the planner", str(caught.exception))


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
            unavailable_gui(self, "tkinter is not installed")

        import gui

        self.assertTrue(hasattr(gui, "OfficeAgentWindow"))
        self.assertTrue(callable(gui.main))


class GuiWindowTests(unittest.TestCase):
    """Build the real window; skipped where Tk or a display is missing."""

    def setUp(self):
        if importlib.util.find_spec("tkinter") is None:
            unavailable_gui(self, "tkinter is not installed")

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
            unavailable_gui(self, f"there is no display ({exc})")

        self.root.withdraw()

        import gui

        self.window = gui.OfficeAgentWindow(self.root)
        self.root.update_idletasks()

        self.addCleanup(self._destroy)

    def _destroy(self):
        worker = getattr(self.window, "worker", None)

        if worker is not None and worker.is_alive():
            worker.join(10.0)

        # close() releases the Tk variables and the window icon before the
        # interpreter goes away, which is what crashed on Windows when they
        # were finalised after Tk had been destroyed.
        try:
            self.window.close()
        except Exception:
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

    def _wait_for_plan(self, timeout: float = 25.0):
        """Wait for the preview window, then hand it back."""

        worker = self.window.worker

        if worker is not None:
            worker.join(timeout)

            if worker.is_alive():
                return None

        deadline = time.time() + 5.0

        while time.time() < deadline:
            self.root.update()

            if self.window.plan_window is not None:
                return self.window.plan_window

            time.sleep(0.02)

        return None

    @classmethod
    def _button(cls, window, label: str):
        for child in window.winfo_children():
            try:
                if (
                    child.winfo_class() in ("Button", "TButton")
                    and child.cget("text") == label
                ):
                    return child
            except Exception:
                pass

            found = cls._button(child, label)

            if found is not None:
                return found

        return None

    def test_the_plan_is_shown_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            job.mkdir(parents=True)

            instruction = write_docx(
                job / "instruction.docx",
                SPEC.strip().splitlines(),
            )

            self.assertTrue(self.window.review_var.get())

            self.window.use_instruction(instruction)
            self.window.run_job()

            dialog = self._wait_for_plan()

            self.assertIsNotNone(dialog, "the plan preview never opened")
            self.assertFalse((job / "output" / "quick.txt").exists())

            start = self._button(
                dialog, ui.text(self.window.language, "plan_start")
            )

            self.assertIsNotNone(start, "the preview has no Run button")

            start.invoke()

            self.assertTrue(self._wait_for_run())
            self.assertTrue((job / "output" / "quick.txt").is_file())

    def test_stopping_while_the_plan_is_built_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            job.mkdir(parents=True)

            instruction = write_docx(
                job / "instruction.docx",
                THREE_STEPS.strip().splitlines(),
            )

            self.window.use_instruction(instruction)
            self.window.run_job()

            dialog = self._wait_for_plan()

            self.assertIsNotNone(dialog, "the plan preview never opened")

            self.window.stop_job()

            start = self._button(
                dialog, ui.text(self.window.language, "plan_start")
            )

            self.assertIsNotNone(start)

            start.invoke()

            self.assertFalse(self.window.running)
            self.assertEqual(
                self.window.status_var.get(),
                ui.text(self.window.language, "stopped", count=0),
            )
            self.assertFalse((job / "output" / "a.txt").exists())

    def test_review_off_runs_straight_away(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "job"
            job.mkdir(parents=True)

            instruction = write_docx(
                job / "instruction.docx",
                SPEC.strip().splitlines(),
            )

            self.window.review_var.set(False)
            self.window.use_instruction(instruction)
            self.window.run_job()

            self.assertTrue(self._wait_for_run())
            self.assertIsNone(self.window.plan_window)
            self.assertTrue((job / "output" / "quick.txt").is_file())

    def _wait_for_run(self, timeout: float = 25.0) -> bool:
        """Let the worker finish, then pump the window until it reports back.

        Joining first matters: a worker still alive when the test drops its
        last reference can collect Tk on that thread and abort the process.
        """

        worker = self.window.worker

        if worker is not None:
            worker.join(timeout)

            if worker.is_alive():
                return False

        deadline = time.time() + 5.0

        while time.time() < deadline:
            self.root.update()

            if not self.window.running and not self.window.testing:
                return True

            time.sleep(0.02)

        return False

    def _use_openai(self) -> None:
        self.window.provider_var.set("OpenAI")
        self.window.on_provider_change()
        self.window.api_key_var.set("test-key")

    def _press_test(self, timeout: float = 20.0) -> bool:
        """Click Test connection and wait for the worker's reply."""

        self.window.test_connection()

        return self._wait_for_run(timeout)

    def test_connection_button_reports_a_working_reply(self):
        self._use_openai()

        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeHttpResponse(200, chat_reply("OK")),
        ):
            self.assertTrue(
                self._press_test(),
                "the connection test never finished",
            )

        self.assertEqual(
            self.window.ai_status_var.get(),
            ui.text(self.window.language, "ai_ok", detail="OK"),
        )
        self.assertEqual(
            str(self.window.test_button.cget("state")), "normal"
        )

    def test_connection_button_reports_a_rejected_key(self):
        self._use_openai()

        body = '{"error": {"message": "Incorrect API key provided"}}'

        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeHttpResponse(401, text=body),
        ):
            self.assertTrue(
                self._press_test(),
                "the connection test never finished",
            )

        self.assertEqual(
            self.window.ai_status_var.get(),
            ui.text(
                self.window.language,
                "ai_fail",
                detail=(
                    'HTTP 401: {"error": '
                    '{"message": "Incorrect API key provided"}}'
                ),
            ),
        )

    def test_connection_button_reports_an_unreachable_endpoint(self):
        self._use_openai()

        with mock.patch(
            "agent.llm.requests.post",
            side_effect=requests.exceptions.ConnectionError(
                "getaddrinfo failed"
            ),
        ):
            self.assertTrue(
                self._press_test(),
                "the connection test never finished",
            )

        self.assertEqual(
            self.window.ai_status_var.get(),
            ui.text(
                self.window.language,
                "ai_fail",
                detail="network error: getaddrinfo failed",
            ),
        )

    def test_run_plans_prose_with_the_configured_model(self):
        job = Path(self._settings.name) / "ai-job"
        job.mkdir()

        instruction = write_docx(job / "instruction.docx", [PROSE])

        self.window.use_instruction(instruction)
        self._use_openai()

        stub = StubPlanner()
        factory = ConfigCheckingFactory(stub, OPENAI_ENV)

        with mock.patch("agent.runtime.try_create_llm", factory):
            self.window.run_job()

            self.assertTrue(self._wait_for_run(), "the run never finished")

        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(stub.prompts), 1)
        self.assertIn(PROSE, prompt_text(stub.prompts[0]))
        self.assertEqual(planner_settings(), OPENAI_ENV)

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
        self.assertEqual(planner_settings(), OPENAI_ENV)
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
