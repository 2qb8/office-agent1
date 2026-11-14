"""Write the Windows version resource PyInstaller embeds in the executables.

``python build_exe.py`` calls this first, so Explorer's file properties show
a product name, a version and a description instead of a blank Details tab.

The generated files are build output, not source: they are regenerated from
``agent/__version__`` on every build and are git-ignored.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import __version__  # noqa: E402

TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numbers},
    prodvers={numbers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Office Agent'),
        StringStruct('FileDescription', '{description}'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{name}'),
        StringStruct('OriginalFilename', '{name}.exe'),
        StringStruct('ProductName', 'Office Agent'),
        StringStruct('ProductVersion', '{version}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

TARGETS = (
    ("version_info_gui.txt", "office-agent-gui", "Office Agent desktop app"),
    ("version_info_cli.txt", "office-agent", "Office Agent command line"),
)


def numbers(version: str) -> tuple[int, ...]:
    """``1.3.1`` becomes the ``(1, 3, 1, 0)`` PyInstaller wants."""

    parts = [int(part) for part in re.findall(r"\d+", version)][:4]

    return tuple(parts + [0] * (4 - len(parts)))


def write_all(directory: Path | None = None) -> list[Path]:
    target = Path(directory) if directory else ROOT / "assets"

    target.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    for filename, name, description in TARGETS:
        path = target / filename

        path.write_text(
            TEMPLATE.format(
                numbers=numbers(__version__),
                version=__version__,
                name=name,
                description=description,
            ),
            encoding="utf-8",
        )

        written.append(path)

    return written


if __name__ == "__main__":
    for written_path in write_all():
        print(f"wrote {written_path}")
