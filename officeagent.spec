# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build recipe for the office automation agent.
#
#   python build_exe.py
#
# Produces dist/office-agent (dist\office-agent.exe on Windows): a single
# file bundling Python, the agent packages and the docx/xlsx dependencies.

from PyInstaller.utils.hooks import collect_data_files


# python-docx needs its default template; openpyxl ships a little data too.
datas = collect_data_files("docx") + collect_data_files("openpyxl")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="office-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Written by assets/make_version_info.py during the build.
    version="assets/version_info_cli.txt",
)
