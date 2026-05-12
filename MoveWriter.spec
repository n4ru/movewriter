# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec. Builds:
#   - Windows / Linux:  onefile  → dist/MoveWriter[.exe]
#   - macOS:            onedir + .app bundle → dist/MoveWriter.app
#
# macOS doesn't play well with onefile + windowed .app bundles (sandbox /
# code-signing edge cases, plus PyInstaller emits a deprecation warning).
# Use onedir there and ship the .app as a zipped folder.

import sys


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('nativeapp', 'nativeapp'), ('resources', 'resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    # onedir layout — EXE wraps only the entry binary; COLLECT bundles libs/data
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='MoveWriter',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=['images/movewriter-logo.png'],
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='MoveWriter',
    )
    app = BUNDLE(
        coll,
        name='MoveWriter.app',
        icon='images/movewriter-logo.png',
        bundle_identifier='com.movewriter.app',
        info_plist={
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
        },
    )
else:
    # onefile — single self-extracting executable
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='MoveWriter',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=['images/movewriter-logo.png'],
    )
