"""
Build a single-file executable with PyInstaller.

    python -m pip install pyinstaller
    python build_exe.py

The artifact is ``dist/office-agent`` (``dist/office-agent.exe`` on
Windows). It bundles Python, the agent packages and the docx/xlsx
dependencies, so the target machine needs no Python installation.

PyInstaller does not cross-compile: run this on the operating system you
want the executable for. To get the Windows .exe without a Windows
machine, run the GitHub Actions workflow in
``.github/workflows/build-exe.yml`` and download its artifact.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPEC = ROOT / "officeagent.spec"


def main() -> int:
    if not SPEC.exists():
        print(f"Missing build spec: {SPEC}")
        return 1

    try:
        import PyInstaller
    except ImportError:
        print(
            "PyInstaller is not installed.\n"
            "  python -m pip install pyinstaller"
        )
        return 1

    system = platform.system()

    print(
        f"Building with PyInstaller {PyInstaller.__version__} "
        f"on {system} {platform.machine()}"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(SPEC),
        ],
        cwd=ROOT,
    )

    if result.returncode != 0:
        print("Build failed.")
        return result.returncode

    name = "office-agent.exe" if system == "Windows" else "office-agent"
    artifact = ROOT / "dist" / name

    if not artifact.exists():
        print(f"Build finished but {artifact} is missing.")
        return 1

    size_mb = artifact.stat().st_size / (1024 * 1024)

    print()
    print(f"Built: {artifact}  ({size_mb:.1f} MiB)")
    print(f"Try it: {artifact} tools")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
