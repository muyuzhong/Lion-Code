# -*- mode: python ; coding: utf-8 -*-
"""Windows x64 sidecar 的 PyInstaller onedir 布局。"""

from pathlib import Path

repo_root = Path(SPECPATH).parent

analysis = Analysis(
    [str(repo_root / "scripts" / "lion_sidecar_entry.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
python_archive = PYZ(analysis.pure)
executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="lion-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="lion-sidecar",
)
