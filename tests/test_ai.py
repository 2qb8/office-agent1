from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from agent import ai_config
from agent.llm import LLM, LLMError, OpenAICompatibleLLM
from agent.llm_factory import create_llm, try_create_llm
from agent.runtime import AgentRuntime
from agent.spec import SpecError
from run import build_registry


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


def completion(content="OK"):
    return {"choices": [{"message": {"content": content}}]}


class LlmClientTests(unittest.TestCase):
    def client(self, **overrides):
        options = {
            "base_url": "https://example.test/v1",
            "api_key": "test-key",
            "model": "test-model",
            "timeout": 5,
            "max_attempts": 1,
            "retry_base_seconds": 0,
            "retry_max_seconds": 0,
        }
        options.update(overrides)

        return OpenAICompatibleLLM(**options)

    def test_message_list_is_sent_unchanged(self):
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "USER"},
        ]

        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeResponse(200, completion("done")),
        ) as post:
            reply = self.client().generate(messages)

        self.assertEqual(reply, "done")

        payload = post.call_args.kwargs["json"]

        self.assertEqual(payload["messages"], messages)
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )

    def test_string_prompt_becomes_a_user_message(self):
        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeResponse(200, completion("hi")),
        ) as post:
            self.client().generate("Hello")

        payload = post.call_args.kwargs["json"]

        self.assertEqual(
            payload["messages"],
            [{"role": "user", "content": "Hello"}],
        )

    def test_sampling_parameters_are_sent(self):
        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeResponse(200, completion("ok")),
        ) as post:
            self.client().generate(
                "Hello",
                temperature=0.25,
                max_tokens=16,
            )
        payload = post.call_args.kwargs["json"]

        self.assertEqual(payload["temperature"], 0.25)
        self.assertEqual(payload["max_tokens"], 16)

    def test_local_client_sends_no_authorization_header(self):
        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeResponse(200, completion("hi")),
        ) as post:
            self.client(api_key="").generate("Hello")

        headers = post.call_args.kwargs["headers"]

        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_retryable_status_is_retried(self):
        responses = [
            FakeResponse(429, text="slow down"),
            FakeResponse(200, completion("retried")),
        ]

        with mock.patch(
            "agent.llm.requests.post",
            side_effect=responses,
        ) as post:
            reply = self.client(max_attempts=2).generate("Hello")

        self.assertEqual(reply, "retried")
        self.assertEqual(post.call_count, 2)

    def test_permanent_status_is_not_retried(self):
        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeResponse(401, text="bad key"),
        ) as post:
            with self.assertRaises(LLMError) as caught:
                self.client(max_attempts=3).generate("Hello")

        self.assertIn("401", str(caught.exception))
        self.assertEqual(post.call_count, 1)

    def test_fallback_model_is_used(self):
        responses = [
            FakeResponse(500, text="boom"),
            FakeResponse(200, completion("from fallback")),
        ]

        with mock.patch(
            "agent.llm.requests.post",
            side_effect=responses,
        ) as post:
            reply = self.client(
                fallback_models=["backup-model"],
            ).generate("Hello")

        self.assertEqual(reply, "from fallback")
        self.assertEqual(
            post.call_args.kwargs["json"]["model"],
            "backup-model",
        )


class LlmFactoryTests(unittest.TestCase):
    def test_ollama_preset_needs_no_key(self):
        with mock.patch.dict(
            os.environ,
            {"LLM_PROVIDER": "ollama"},
            clear=True,
        ):
            client = create_llm()

        self.assertEqual(
            client.base_url,
            "http://localhost:11434/v1",
        )
        self.assertEqual(client.model, "qwen2.5:3b")
        self.assertEqual(client.api_key, "")

    def test_cloud_provider_without_key_explains_setup(self):
        with mock.patch.dict(
            os.environ,
            {"LLM_PROVIDER": "openai"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as caught:
                create_llm()

        self.assertIn("ai setup", str(caught.exception))

    def test_try_create_llm_returns_none_when_unconfigured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(try_create_llm())

    def test_custom_endpoint_overrides_presets(self):
        with mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "custom",
                "LLM_BASE_URL": "http://127.0.0.1:8080/v1",
                "LLM_MODEL": "tiny-model",
            },
            clear=True,
        ):
            client = create_llm()

        self.assertEqual(
            client.base_url,
            "http://127.0.0.1:8080/v1",
        )
        self.assertEqual(client.model, "tiny-model")


class AiConfigTests(unittest.TestCase):
    def test_write_config_merges_and_keeps_other_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / ".env"
            path.parent.mkdir()

            path.write_text(
                "# keep me\nOTHER=value\nLLM_PROVIDER=old\n",
                encoding="utf-8",
            )

            ai_config.write_config(
                {
                    "LLM_PROVIDER": "openai",
                    "LLM_API_KEY": "secret-value",
                },
                path=path,
            )

            text = path.read_text(encoding="utf-8")

            self.assertIn("# keep me", text)
            self.assertIn("OTHER=value", text)
            self.assertIn("LLM_PROVIDER=openai", text)
            self.assertIn("LLM_API_KEY=secret-value", text)
            self.assertEqual(text.count("LLM_PROVIDER="), 1)

    def test_write_config_rejects_line_breaks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"

            with self.assertRaises(ValueError):
                ai_config.write_config(
                    {"LLM_API_KEY": "bad\nvalue"},
                    path=path,
                )

    def test_describe_never_prints_the_key(self):
        with mock.patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openai",
                "LLM_BASE_URL": "https://example.test/v1",
                "LLM_MODEL": "test-model",
                "LLM_API_KEY": "super-secret-key",
            },
            clear=True,
        ):
            output = ai_config.describe()

        self.assertNotIn("super-secret-key", output)
        self.assertIn("api key  : set", output)
        self.assertIn("status   : ready", output)

    def test_connection_failure_is_reported(self):
        config = ai_config.AiConfig(
            provider="openai",
            base_url="https://example.test/v1",
            model="test-model",
            api_key="test-key",
        )

        with mock.patch(
            "agent.llm.requests.post",
            return_value=FakeResponse(401, text="denied"),
        ):
            ok, detail = ai_config.test_connection(config)

        self.assertFalse(ok)
        self.assertIn("401", detail)


AI_PLAN = {
    "goal": "Write an AI note",
    "steps": [
        {
            "id": "write",
            "description": "Write the note",
            "tool": "text",
            "action": "write",
            "arguments": {
                "output_path": "output/ai.txt",
                "content": "from ai",
            },
        }
    ],
}


class AiSetupTests(unittest.TestCase):
    def run_setup(self, provider: str, ambient_key: str) -> str:
        import run

        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            os.chdir(directory)

            try:
                arguments = argparse.Namespace(
                    action="setup",
                    provider=provider,
                    base_url=None,
                    model=None,
                    no_test=True,
                )

                with mock.patch.dict(
                    os.environ,
                    {"LLM_API_KEY": ambient_key},
                    clear=False,
                ):
                    with mock.patch.object(
                        sys.stdin,
                        "isatty",
                        return_value=False,
                    ):
                        with redirect_stdout(io.StringIO()):
                            status = run.ai_setup(arguments)

                self.assertEqual(status, 0)

                return (
                    Path("config") / ".env"
                ).read_text(encoding="utf-8")
            finally:
                os.chdir(previous)

    def test_local_setup_does_not_copy_an_ambient_key(self):
        text = self.run_setup("ollama", "ambient-cloud-key")

        self.assertIn("LLM_PROVIDER=ollama", text)
        self.assertNotIn("ambient-cloud-key", text)
        self.assertIn("LLM_API_KEY=\n", text + "\n")

    def test_cloud_setup_reuses_the_environment_key(self):
        text = self.run_setup("openai", "env-key")

        self.assertIn("LLM_PROVIDER=openai", text)
        self.assertIn("LLM_API_KEY=env-key", text)


class StaticLLM(LLM):
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def generate(self, prompt, temperature=0.0, max_tokens=None):
        self.prompts.append(prompt)

        return json.dumps(self.payload)


class AiPlanningTests(unittest.TestCase):
    def make_job(self, directory: str) -> Path:
        job = Path(directory) / "ai-job"
        (job / "inputs").mkdir(parents=True)

        (job / "instruction.txt").write_text(
            "Please write a short note to output/ai.txt.",
            encoding="utf-8",
        )

        return job

    def test_prose_instruction_uses_configured_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.make_job(directory)

            runtime = AgentRuntime(job, build_registry())
            llm = StaticLLM(AI_PLAN)

            with mock.patch(
                "agent.runtime.try_create_llm",
                return_value=llm,
            ):
                with redirect_stdout(io.StringIO()):
                    state = runtime.run()

            self.assertEqual(state.status.value, "success")
            self.assertEqual(
                (job / "output" / "ai.txt").read_text(
                    encoding="utf-8"
                ).strip(),
                "from ai",
            )
            self.assertEqual(len(llm.prompts), 1)
            self.assertEqual(llm.prompts[0][0]["role"], "system")

    def test_no_ai_flag_requires_a_spec(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.make_job(directory)
            runtime = AgentRuntime(job, build_registry())

            with self.assertRaises(SpecError):
                with redirect_stdout(io.StringIO()):
                    runtime.create_plan(
                        runtime.read_instruction(),
                        use_ai=False,
                    )

    def test_ai_flag_without_configuration_explains_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            job = self.make_job(directory)
            runtime = AgentRuntime(job, build_registry())

            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError) as caught:
                    with redirect_stdout(io.StringIO()):
                        runtime.run(use_ai=True)

            self.assertIn("ai setup", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
