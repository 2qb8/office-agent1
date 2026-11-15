"""The summary has to be honest when the suite fails, not just when it passes.

CI commits docs/tests-windows.txt and docs/tests-linux.txt so a signed-out
reader can see what ran. A report that still said PASS on a red run would be
worse than no report at all, and only the green path had ever run — so this
runs the real script against a suite that fails on purpose.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "test_summary.py"
)

FAILING_SUITE = '''\
import unittest


class DeliberatelyBrokenTests(unittest.TestCase):
    def test_this_one_fails(self):
        self.assertEqual(1, 2, "the summary must report this")

    def test_this_one_passes(self):
        self.assertTrue(True)
'''


class FailingSummaryTests(unittest.TestCase):
    def run_summary(self, project: Path, summary: Path):
        """Run the script in a throwaway project holding a failing suite."""

        (project / "scripts").mkdir()
        (project / "tests").mkdir()

        # The suite is discovered as the package "tests", which needs this.
        (project / "tests" / "__init__.py").write_text("", encoding="utf-8")

        shutil.copy(SCRIPT, project / "scripts" / "test_summary.py")
        (project / "tests" / "test_broken.py").write_text(
            FAILING_SUITE,
            encoding="utf-8",
        )

        return subprocess.run(
            [
                sys.executable,
                "scripts/test_summary.py",
                "--label",
                "Fixture",
                "--out",
                str(summary),
            ],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_a_failing_suite_still_writes_a_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            summary_path = project / "docs" / "tests-fixture.txt"

            completed = self.run_summary(project, summary_path)

            self.assertNotEqual(
                completed.returncode,
                0,
                f"a failing suite must exit non-zero:\n{completed.stderr}",
            )

            self.assertTrue(
                summary_path.is_file(),
                f"no summary was written:\n{completed.stdout}\n{completed.stderr}",
            )

            summary = summary_path.read_text(encoding="utf-8")

            self.assertIn("Result:  FAIL", summary)
            self.assertIn("test_this_one_fails", summary)
            self.assertIn("Fail:    1", summary)
            self.assertIn("Pass:    1", summary)
            self.assertIn("Suite:   2 tests", summary)

            # Only what went wrong is named; a passing test is not noise.
            self.assertNotIn("test_this_one_passes", summary)

    def test_the_log_still_looks_like_unittest(self):
        """The failure-report steps grep this log, so its shape matters."""

        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            summary_path = project / "docs" / "tests-fixture.txt"

            completed = self.run_summary(project, summary_path)
            output = completed.stdout + completed.stderr

            self.assertIn("FAIL: test_this_one_fails", output)
            self.assertIn("FAILED (failures=1)", output)
            self.assertIn("Ran 2 tests", output)
