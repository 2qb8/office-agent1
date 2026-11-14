"""One run at a time in a job folder.

Two windows on the same instruction would both write ``report.json``,
``state.json``, ``run.log`` and ``output/``, and the result would be a mix
of two runs. The lock is a file created with ``O_EXCL``, so it is atomic on
every platform, and it is removed when the run ends.

A lock left behind by a crashed run is ignored after
:data:`STALE_AFTER_SECONDS`; process IDs are not consulted because checking
one is not portable (``os.kill`` on Windows terminates the process).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

LOCK_NAME = ".running"

STALE_AFTER_SECONDS = 12 * 60 * 60


class JobBusyError(RuntimeError):
    """Another window is running this job folder right now."""


class JobLock:
    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / LOCK_NAME

        self._held = False

    def __enter__(self) -> "JobLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise JobBusyError(f"Cannot use {self.path.parent}: {exc}")

        if self._acquire():
            self._held = True
            return self

        if self._stale():
            try:
                self.path.unlink()
            except OSError:
                pass

            if self._acquire():
                self._held = True
                return self

        raise JobBusyError(
            f"{self.path.parent} is already running in another window."
        )

    def __exit__(self, *exc_info) -> None:
        if not self._held:
            return

        self._held = False

        try:
            self.path.unlink()
        except OSError:
            pass

    def _acquire(self) -> bool:
        try:
            handle = os.open(
                str(self.path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            return False
        except OSError:
            return False

        try:
            os.write(handle, f"{os.getpid()}\n".encode("utf-8"))
        finally:
            os.close(handle)

        return True

    def _stale(self) -> bool:
        try:
            age = time.time() - self.path.stat().st_mtime
        except OSError:
            return True

        return age > STALE_AFTER_SECONDS
