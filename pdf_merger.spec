# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# Get application directory
app_dir = os.path.dirname(os.path.abspath(SPEC))

# Create runtime hook to suppress console windows
with open(os.path.join(app_dir, 'suppress_console.py'), 'w') as f:
    f.write('''
import os
import sys
import subprocess

# Override subprocess creation to hide console windows on Windows
if sys.platform.startswith('win'):
    # Store original Popen
    original_popen = subprocess.Popen
    
    # Create new Popen that always hides console windows
    class NoConsolePopen(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            # Force CREATE_NO_WINDOW flag for all Windows processes
            if sys.platform.startswith('win'):
                kwargs['creationflags'] = kwargs.get('creationflags', 0) | 0x08000000
            super().__init__(*args, **kwargs)
    
    # Replace the Popen implementation
    subprocess.Popen = NoConsolePopen
''')

# Collect data files
datas = []

# Add assets folder if it exists
assets_path = os.path.join(app_dir, 'assets')
if os.path.exists(assets_path):
    datas.append((assets_path, 'assets'))

# Add icon file specifically
icon_path = os.path.join(app_dir, 'assets', 'app_icon.png')
if os.path.exists(icon_path):
    datas.append((icon_path, '.'))

# Add Poppler binaries (critical for PDF processing)
poppler_bin_path = os.path.join(app_dir, 'poppler-25.07.0', 'Library', 'bin')
if os.path.exists(poppler_bin_path):
    print(f"Including Poppler binaries from: {poppler_bin_path}")
    datas.append((poppler_bin_path, 'poppler/bin'))
    
    # Add full poppler directory structure
    datas.append((os.path.join(app_dir, 'poppler-25.07.0'), 'poppler-25.07.0'))
    
    # Also add any required poppler data files
    poppler_share_path = os.path.join(app_dir, 'poppler-25.07.0', 'share', 'poppler')
    if os.path.exists(poppler_share_path):
        datas.append((poppler_share_path, 'poppler/share'))
else:
    print("Warning: Poppler binaries not found - PDF functionality may not work")

# Collect PyQt6 data files
try:
    datas += collect_data_files('PyQt6')
except:
    pass

# Collect pdf2image and poppler dependencies
try:
    datas += collect_data_files('pdf2image')
except:
    pass

# Hidden imports needed for the application
hiddenimports = [
    'PyQt6.QtCore',
    'PyQt6.QtGui', 
    'PyQt6.QtWidgets',
    'pypdf',
    'pdf2image',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'concurrent.futures',
    'threading',
    'pathlib',
    'tempfile',
    'logging',
    'win32gui',
    'win32con',
    'subprocess',
]

# Collect dynamic libraries
binaries = []

# Add Poppler binaries as executables
if os.path.exists(poppler_bin_path):
    # Add specific poppler executables we need
    poppler_exes = ['pdftoppm.exe', 'pdfinfo.exe', 'pdfattach.exe', 'pdfdetach.exe', 'pdftocairo.exe']
    for exe in poppler_exes:
        exe_path = os.path.join(poppler_bin_path, exe)
        if os.path.exists(exe_path):
            binaries.append((exe_path, 'poppler/bin'))
    
    # Add all DLL files that poppler needs
    for file in os.listdir(poppler_bin_path):
        if file.endswith('.dll'):
            dll_path = os.path.join(poppler_bin_path, file)
            binaries.append((dll_path, 'poppler/bin'))

try:
    binaries += collect_dynamic_libs('PyQt6')
except:
    pass

a = Analysis(
    ['pdf_merger_simple.py'],
    pathex=[app_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['suppress_console.py'],  # Add runtime hook to suppress console
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
        'unittest',
        'test',
        'tests',
        'PyQt6.QtMultimedia',
        'PyQt6.QtWebEngine',
        'PyQt6.QtNetwork',
        'PyQt6.QtPrintSupport',
        'PyQt6.QtSql',
        'PyQt6.QtTest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDFMerger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window
    disable_windowed_traceback=True,  # Suppress traceback windows
    argv_emulation=False,
    target_arch=None,
    uac_admin=False,  # Don't request admin privileges
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)