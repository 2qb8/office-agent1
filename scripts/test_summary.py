"""Run the test suite and leave a summary a signed-out reader can open.

    python scripts/test_summary.py --label Windows --out docs/tests-windows.txt

CI run logs need a signed-in account, and "green" alone does not say how
much ran or whether the window was built at all. So each job rewrites a
small committed file instead: totals, skips with their reasons, failures by
name, and a line saying whether the Tk tests were actually exercised.

The suite is still run by unittest with the same verbose output, so the logs
keep the shape the failure-report steps look for, and the exit code is
unittest's own.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))

# Tests that need a window: every one of them calls unavailable_gui() when
# Tk or a display is missing, so counting them is what shows the GUI was
# really built. Both markers must keep matching: 16 tests in total.
WINDOW_MARKERS = ("GuiWindowTests", "test_gui_window_class_exists")

# Keep the file short: name a few, count the rest.
LIST_LIMIT = 6

PRECEDENCE = {"passed": 0, "skipped": 1, "failed": 2, "errored": 3}


class RecordingResult(unittest.TextTestResult):
    """A normal result that also remembers what happened to each test."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.outcomes: dict[str, tuple[str, str]] = {}

    def _record(self, test, outcome: str, reason: str = "") -> None:
        name = str(test)
        current = self.outcomes.get(name)

        if current is None or PRECEDENCE[outcome] > PRECEDENCE[current[0]]:
            self.outcomes[name] = (outcome, reason)

    def addSuccess(self, test) -> None:
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err) -> None:
        super().addFailure(test, err)
        self._record(test, "failed")

    def addError(self, test, err) -> None:
        super().addError(test, err)
        self._record(test, "errored")

    def addSkip(self, test, reason) -> None:
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addSubTest(self, test, subtest, err) -> None:
        super().addSubTest(test, subtest, err)

        if err is not None:
            self._record(test, "failed", str(subtest))


def window_tests(outcomes: dict[str, tuple[str, str]]) -> tuple[int, int]:
    """How many window tests ran, and how many were skipped."""

    ran = 0
    skipped = 0

    for name, (outcome, _) in outcomes.items():
        if not any(marker in name for marker in WINDOW_MARKERS):
            continue

        if outcome == "skipped":
            skipped += 1
        else:
            ran += 1

    return ran, skipped


def names_with(outcomes, outcome: str) -> list[str]:
    return sorted(
        name for name, (result, _) in outcomes.items() if result == outcome
    )


def short_names(names: list[str]) -> str:
    shown = names[:LIST_LIMIT]
    text = ", ".join(name.split(" ")[0] for name in shown)

    if len(names) > len(shown):
        text += f", and {len(names) - len(shown)} more"

    return text


def skip_reasons(outcomes) -> str:
    counts: dict[str, int] = {}

    for outcome, reason in outcomes.values():
        if outcome == "skipped":
            key = " ".join(reason.split()) or "(no reason given)"
            counts[key] = counts.get(key, 0) + 1

    if not counts:
        return "none"

    return "; ".join(
        f"{reason} ({count})" for reason, count in sorted(counts.items())
    )


def run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run = os.environ.get("GITHUB_RUN_ID", "")

    if server and repo and run:
        return f"{server}/{repo}/actions/runs/{run}"

    return "local run"


def build_summary(
    label: str,
    result: RecordingResult,
    elapsed: float,
    started: dt.datetime,
) -> str:
    outcomes = result.outcomes
    passed = len(names_with(outcomes, "passed"))
    failed = names_with(outcomes, "failed")
    errored = names_with(outcomes, "errored")
    ran, skipped = window_tests(outcomes)

    commit = os.environ.get("GITHUB_SHA", "")[:7] or "uncommitted"
    verdict = "PASS" if result.wasSuccessful() else "FAIL"

    lines = [
        f"Office Agent test summary — {label}",
        f"Run:     {run_url()}",
        f"Commit:  {commit} ({started.strftime('%Y-%m-%dT%H:%MZ')})",
        f"Python:  {platform.python_version()}, {platform.system()} "
        f"{platform.release()}",
        "",
        f"Suite:   {result.testsRun} tests in {elapsed:.1f}s",
        f"Pass:    {passed}",
        f"Skip:    {len(result.skipped)}",
        f"Fail:    {len(failed)}",
        f"Error:   {len(errored)}",
        "",
        f"Window tests (Tk): {ran} of {ran + skipped} ran, {skipped} skipped",
        f"Skipped: {skip_reasons(outcomes)}",
    ]

    if failed:
        lines.append(f"Failed:  {short_names(failed)}")

    if errored:
        lines.append(f"Errored: {short_names(errored)}")

    lines.extend(["", f"Result:  {verdict}", ""])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--label",
        default="Local",
        help="which job this is, for the first line of the summary",
    )
    parser.add_argument(
        "--out",
        default="",
        help="write the summary here; printing is skipped when it is empty",
    )
    parser.add_argument(
        "--start",
        default="tests",
        help="where to discover tests from",
    )

    arguments = parser.parse_args()

    started = dt.datetime.now(dt.timezone.utc)
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / arguments.start), top_level_dir=str(ROOT))

    runner = unittest.TextTestRunner(
        verbosity=2,
        resultclass=RecordingResult,
    )

    clock = time.monotonic()
    result = runner.run(suite)
    elapsed = time.monotonic() - clock

    summary = build_summary(arguments.label, result, elapsed, started)

    if arguments.out:
        target = Path(arguments.out)

        if not target.is_absolute():
            target = Path.cwd() / target

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(summary, encoding="utf-8")

        print(f"\nWrote {target}")
        print(summary)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
