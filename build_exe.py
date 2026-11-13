"""
Build single-file executables with PyInstaller.

    python -m pip install pyinstaller
    python build_exe.py

Two artifacts are produced:

* ``office-agent``       command line (``office-agent run <job-folder>``)
* ``office-agent-gui``   desktop window, double-click to start

On Windows they are ``.exe`` files. The GUI build needs Tkinter, which the
python.org Windows installer includes by default; it is skipped when the
interpreter has no Tkinter.

PyInstaller does not cross-compile: run this on the operating system you
want the executables for. To get the Windows files without a Windows
machine, run the GitHub Actions workflow in ``.github/workflows/build-exe.yml``
and download its artifact or release assets.
"""

from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

BUILDS = (
    ("officeagent.spec", "office-agent"),
    ("officeagent-gui.spec", "office-agent-gui"),
)


def has_tkinter() -> bool:
    return importlib.util.find_spec("tkinter") is not None


def build(spec_name: str) -> int:
    spec = ROOT / spec_name

    if not spec.exists():
        print(f"Missing build spec: {spec}")
        return 1

    return subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            str(spec),
        ],
        cwd=ROOT,
    ).returncode


def main() -> int:
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

    suffix = ".exe" if system == "Windows" else ""

    built: list[Path] = []

    for spec_name, name in BUILDS:
        if name == "office-agent-gui" and not has_tkinter():
            print()
            print("Skipping the GUI build: Tkinter is not available.")
            print("  Debian/Ubuntu: sudo apt install python3-tk")
            continue

        print()
        print(f"Building {name} ...")

        if build(spec_name) != 0:
            print(f"Build failed for {name}.")
            return 1

        artifact = ROOT / "dist" / f"{name}{suffix}"

        if not artifact.exists():
            print(f"Build finished but {artifact} is missing.")
            return 1

        built.append(artifact)

    print()

    for artifact in built:
        size_mb = artifact.stat().st_size / (1024 * 1024)
        print(f"Built: {artifact}  ({size_mb:.1f} MiB)")

    if built:
        print()
        print("Command line:  office-agent tools")
        print("Desktop app:   double-click office-agent-gui")

    if not has_tkinter():
        print()
        print(
            "The desktop build was skipped here; the Windows workflow "
            "builds it with Tkinter included."
        )

    return 0 if built else 1


if __name__ == "__main__":
    raise SystemExit(main())
