#!/usr/bin/env python3
"""
Build script for PDF Merger Application using PyInstaller.
This script ensures proper configuration for Windows builds.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_dependencies():
    """Check if all required dependencies are installed."""
    try:
        import PyQt6
        import pypdf
        import pdf2image
        import PIL
        import pyinstaller
        print("✓ All required dependencies found")
        return True
    except ImportError as e:
        print(f"✗ Missing dependency: {e}")
        print("Please install dependencies with: pip install -r requirements.txt")
        return False


def generate_icon():
    """Generate app icon if it doesn't exist."""
    assets_dir = Path("assets")
    icon_path = assets_dir / "app_icon.png"
    ico_path = assets_dir / "app_icon.ico"
    
    if not icon_path.exists():
        print("Generating app icon...")
        try:
            # Import the icon generation function
            sys.path.insert(0, str(Path.cwd()))
            from pdf_merger_simple import generate_icon as gen_icon, ensure_icon
            ensure_icon()
            print("✓ App icon generated")
        except Exception as e:
            print(f"⚠ Failed to generate icon: {e}")
    
    # Convert PNG to ICO for Windows
    if icon_path.exists() and not ico_path.exists():
        try:
            from icon_converter import png_to_ico
            png_to_ico(icon_path, ico_path)
            print("✓ ICO icon created")
        except Exception as e:
            print(f"⚠ Failed to create ICO icon: {e}")


def clean_build():
    """Clean previous build artifacts."""
    dirs_to_clean = ["build", "dist", "__pycache__"]
    for dir_name in dirs_to_clean:
        if Path(dir_name).exists():
            shutil.rmtree(dir_name)
            print(f"✓ Cleaned {dir_name}")


def build_application():
    """Build the application using PyInstaller."""
    print("Building application...")
    
    # Use the spec file for more control
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "pdf_merger_simple.spec"
    ]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✓ Build completed successfully")
        
        # Check if the executable was created
        if sys.platform.startswith('win'):
            exe_path = Path("dist/PDF_Merger_Simple.exe")
        else:
            exe_path = Path("dist/PDF_Merger_Simple")
            
        if exe_path.exists():
            print(f"✓ Executable created: {exe_path}")
            print(f"Size: {exe_path.stat().st_size / (1024*1024):.1f} MB")
        else:
            print("⚠ Executable not found in expected location")
            
    except subprocess.CalledProcessError as e:
        print(f"✗ Build failed: {e}")
        if e.stdout:
            print("STDOUT:", e.stdout[-1000:])  # Last 1000 chars
        if e.stderr:
            print("STDERR:", e.stderr[-1000:])  # Last 1000 chars
        return False
    
    return True


def main():
    """Main build function."""
    print("PDF Merger Application Build Script")
    print("=" * 40)
    
    # Check dependencies
    if not check_dependencies():
        return 1
    
    # Generate icons
    generate_icon()
    
    # Clean previous builds
    clean_build()
    
    # Build application
    if build_application():
        print("\n✓ Build completed successfully!")
        print("The executable can be found in the 'dist' directory.")
        return 0
    else:
        print("\n✗ Build failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())