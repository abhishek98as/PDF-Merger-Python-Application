# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

block_cipher = None

# Define data files to include
datas = []

# Include assets directory if it exists
assets_dir = Path('./assets')
if assets_dir.exists():
    datas.append(('assets', 'assets'))

# Include poppler binaries if they exist locally
poppler_dir = Path('./poppler-23.11.0')
if poppler_dir.exists():
    datas.append(('poppler-23.11.0', 'poppler'))

a = Analysis(
    ['pdf_merger_simple.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pdf2image.pdf2image',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'pypdf',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets'
    ],
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
    name='PDF_Merger_Simple',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico' if Path('assets/app_icon.ico').exists() else None,
)