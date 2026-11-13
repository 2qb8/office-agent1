from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from run import main


class CliTests(unittest.TestCase):
    def test_version_flag(self):
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as caught:
                main(["--version"])

        self.assertEqual(caught.exception.code, 0)
        self.assertIn("office-agent", buffer.getvalue())

    def test_bare_job_directory_is_a_run(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Path(directory) / "quick-job"
            (job / "inputs").mkdir(parents=True)

            (job / "instruction.txt").write_text(
                "steps:\n"
                "  - id: write\n"
                "    tool: text\n"
                "    action: write\n"
                "    arguments:\n"
                "      output_path: output/quick.txt\n"
                "      content: hi\n",
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()) as buffer:
                status = main([str(job)])

            self.assertEqual(status, 0)
            self.assertTrue((job / "output" / "quick.txt").is_file())
            self.assertIn("Job status: success", buffer.getvalue())

    def test_missing_job_directory_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "does-not-exist"

            with redirect_stdout(io.StringIO()) as buffer:
                status = main([str(missing)])

            self.assertEqual(status, 1)
            self.assertIn("FATAL ERROR", buffer.getvalue())
