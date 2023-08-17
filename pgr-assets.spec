# -*- mode: python ; coding: utf-8 -*-

import os
import importlib

package_imports = [['UnityPy', ['resources/uncompressed.tpk']]]

datas = []
for package, files in package_imports:
    proot = os.path.dirname(importlib.import_module(package).__file__)
    datas.extend((
        os.path.join(proot, f), 
        os.path.join(package, os.path.dirname(f)).strip('/')
    ) for f in files)


block_cipher = None


a = Analysis(
    ['pgr-assets.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
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
    name='pgr-assets',
    debug=False,
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
