"""The bundled model is a prototype, so its failure modes matter more than
its happy path: no flag, no binary, a bad download. Each of those has to end
in a sentence a user can act on, and none of them may leave rubbish behind.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent import bundled


class BundledModelTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)

        self.folder = Path(self._temp.name)
        self.payload = b"a pretend gguf file" * 100
        self.source = self.folder / "source.gguf"
        self.source.write_bytes(self.payload)

        digest = hashlib.sha256(self.payload).hexdigest()

        patches = {
            "OFFICE_AGENT_MODELS": str(self.folder / "models"),
            "OFFICE_AGENT_LLAMA_SERVER": "",
        }

        self._env = mock.patch.dict(os.environ, patches)
        self._env.start()
        self.addCleanup(self._env.stop)

        self._url = mock.patch.object(
            bundled, "MODEL_URL", self.source.as_uri()
        )
        self._url.start()
        self.addCleanup(self._url.stop)

        self._hash = mock.patch.object(bundled, "MODEL_SHA256", digest)
        self._hash.start()
        self.addCleanup(self._hash.stop)

    def test_the_flag_is_off_unless_it_is_set(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(bundled.enabled())

        with mock.patch.dict(
            os.environ, {"OFFICE_AGENT_BUNDLED_MODEL": "1"}
        ):
            self.assertTrue(bundled.enabled())

        with mock.patch.dict(
            os.environ, {"OFFICE_AGENT_BUNDLED_MODEL": "0"}
        ):
            self.assertFalse(bundled.enabled())

    def test_asking_for_it_while_off_says_which_flag(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(bundled.BundledError) as caught:
                bundled.create_client()

        self.assertIn("OFFICE_AGENT_BUNDLED_MODEL=1", str(caught.exception))

    def test_a_first_download_is_kept_and_not_repeated(self):
        path = bundled.ensure_model()

        self.assertEqual(path.name, bundled.MODEL_FILE)
        self.assertEqual(path.read_bytes(), self.payload)

        with mock.patch.object(
            bundled.urllib.request,
            "urlopen",
            side_effect=AssertionError("downloaded twice"),
        ):
            again = bundled.ensure_model()

        self.assertEqual(again, path)

    def test_a_bad_checksum_leaves_nothing_behind(self):
        with mock.patch.object(bundled, "MODEL_SHA256", "0" * 64):
            with self.assertRaises(bundled.BundledError) as caught:
                bundled.ensure_model()

        self.assertIn("checksum", str(caught.exception))
        self.assertFalse(bundled.model_path().exists())
        self.assertEqual(
            list(bundled.models_dir().glob("*.part")),
            [],
        )

    def test_a_corrupt_file_on_disk_is_replaced(self):
        bundled.model_path().parent.mkdir(parents=True, exist_ok=True)
        bundled.model_path().write_bytes(b"half a download")

        path = bundled.ensure_model()

        self.assertEqual(path.read_bytes(), self.payload)

    def test_progress_is_reported_with_the_total(self):
        seen: list[tuple[int, int]] = []

        bundled.ensure_model(progress=lambda done, total: seen.append((done, total)))

        self.assertTrue(seen)
        self.assertEqual(seen[-1], (len(self.payload), len(self.payload)))

    def test_the_server_is_told_where_the_model_is(self):
        command = bundled.server_command(
            "/opt/llama-server", Path("/models/m.gguf"), 9123
        )

        self.assertEqual(command[0], "/opt/llama-server")
        self.assertEqual(command[command.index("--model") + 1], "/models/m.gguf")
        self.assertEqual(command[command.index("--port") + 1], "9123")
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")

    def test_a_missing_binary_is_explained(self):
        with mock.patch.object(bundled.shutil, "which", return_value=None):
            self.assertIsNone(bundled.find_server())

            with mock.patch.dict(
                os.environ, {"OFFICE_AGENT_BUNDLED_MODEL": "1"}
            ):
                server = bundled.BundledServer(port=9111)

                with self.assertRaises(bundled.BundledError) as caught:
                    server.start()

        self.assertIn("llama-server was not found", str(caught.exception))

    def test_an_explicit_binary_path_that_does_not_exist_is_ignored(self):
        with mock.patch.dict(
            os.environ,
            {"OFFICE_AGENT_LLAMA_SERVER": str(self.folder / "nope")},
        ):
            self.assertIsNone(bundled.find_server())

    def test_describe_is_one_line(self):
        line = bundled.describe()

        self.assertIn("Bundled model: off", line)
        self.assertNotIn("\n", line)
