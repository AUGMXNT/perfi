# -*- mode: python ; coding: utf-8 -*-


block_cipher = None

added_files = [
    ( 'perfi.schema.sql', '.' ),
    ( 'cache.schema.sql', '.' ),
    ( 'README.md', '.' ),
    ( 'frontend', 'frontend' ),
]

hidden_imports = [
    # 'uvicorn.logging',
    # 'uvicorn.loops',
    # 'uvicorn.loops.auto',
    # 'uvicorn.protocols',
    # 'uvicorn.protocols.http',
    # 'uvicorn.protocols.http.auto',
    # 'uvicorn.protocols.websockets',
    # 'uvicorn.protocols.websockets.auto',
    # 'uvicorn.lifespan',
    # 'uvicorn.lifespan.on',
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
    [],
    exclude_binaries=True,
    name='perfi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='perfi',
)
