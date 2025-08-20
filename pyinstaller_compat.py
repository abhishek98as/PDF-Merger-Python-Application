"""
PyInstaller compatibility utilities.
These functions handle the differences between running as a script vs PyInstaller executable.
"""

import os
import sys
import subprocess
import pathlib


def is_frozen():
    """Check if running in a PyInstaller bundle."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_subprocess_creation_flags():
    """Get proper subprocess creation flags for Windows PyInstaller builds."""
    if sys.platform.startswith('win') and is_frozen():
        # Hide console windows when running as exe
        # CREATE_NO_WINDOW = 0x08000000
        return getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    return 0


def get_resource_path():
    """Get the path to the resources directory, accounting for PyInstaller."""
    if is_frozen():
        # When running as PyInstaller exe, use the temporary directory
        base_path = pathlib.Path(sys._MEIPASS)
    else:
        # When running as script, use script directory
        base_path = pathlib.Path(__file__).resolve().parent
    
    assets_dir = base_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir


def get_poppler_path():
    """Get the Poppler executable path, accounting for PyInstaller."""
    if is_frozen():
        # When running as PyInstaller exe, check bundled poppler first
        base_path = pathlib.Path(sys._MEIPASS)
        bundled_poppler = base_path / "poppler" / "bin"
        if bundled_poppler.exists():
            return str(bundled_poppler)
    else:
        # When running as script, check local poppler
        base_path = pathlib.Path(__file__).resolve().parent
        local_poppler = base_path / "poppler-23.11.0" / "Library" / "bin"
        if local_poppler.exists():
            return str(local_poppler)
    
    # Try environment variable
    env_path = os.environ.get("POPPLER_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    # On Windows, try common installation locations
    if sys.platform.startswith('win'):
        common_paths = [
            r"C:\Program Files\poppler-23.11.0\Library\bin",
            r"C:\Program Files\poppler\bin",
            r"C:\poppler\bin",
            os.path.expanduser("~\\poppler\\bin")
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
                
    return None