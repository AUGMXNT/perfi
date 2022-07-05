# -*- mode: python ; coding: utf-8 -*-

# ls /Users/gabe/Library/Caches/pypoetry/virtualenvs/perfi-bXlbemU2-py3.8/lib/python3.8/site-packages/PyQt6/Qt6/lib/QtWebEngineCore.framework/Resources

from pathlib import Path
import os
from PyInstaller.utils.hooks import get_package_paths

qt_webengine_path = Path(get_package_paths('PyQt6')[1] + "/Qt6/lib/QtWebEngineCore.framework/Resources")

block_cipher = None

added_files = [
    ( 'perfi.schema.sql', '.' ),
    ( 'cache.schema.sql', '.' ),
    ( 'README.md', '.' ),
    ( 'frontend', 'frontend' ),
    ( qt_webengine_path / 'qtwebengine_resources.pak', '.' ),
    ( qt_webengine_path / 'qtwebengine_devtools_resources.pak', '.' ),
    ( qt_webengine_path / 'qtwebengine_resources_100p.pak', '.' ),
    ( qt_webengine_path / 'qtwebengine_resources_200p.pak', '.' ),
    ( qt_webengine_path / 'icudtl.dat', '.' ),
]

hidden_imports = [
    "perfi.api",
]

a = Analysis(
    ['app_main.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='perfi',
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = BUNDLE(
    exe,
    name='perfi.app',
    icon=None,
    bundle_identifier=None,
)
