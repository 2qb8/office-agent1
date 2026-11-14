# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build recipe for the desktop app.
#
#   python build_exe.py
#
# Produces dist/office-agent-gui (dist\office-agent-gui.exe on Windows):
# a single windowed file with Python, Tkinter, the agent packages, the
# docx/xlsx dependencies and the window icon bundled.

from PyInstaller.utils.hooks import collect_data_files


datas = (
    collect_data_files("docx")
    + collect_data_files("openpyxl")
    + [("assets", "assets")]
)

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="office-agent-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/office-agent.ico",
)
