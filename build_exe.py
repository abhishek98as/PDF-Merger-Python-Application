#!/usr/bin/env python3
"""
Build script for PDF Merger application.
Creates a standalone executable using PyInstaller.
"""

import os
import sys
import subprocess
import shutil
import pathlib
from typing import List, Optional

def run_command(cmd: List[str], description: str) -> bool:
    """Run a command and return True if successful."""
    print(f"\n🔨 {description}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if result.stdout.strip():
            print(f"✅ Output: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        if e.stdout:
            print(f"stdout: {e.stdout}")
        if e.stderr:
            print(f"stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"❌ Command not found: {cmd[0]}")
        return False

def check_python_version() -> bool:
    """Check if Python version is compatible."""
    version = sys.version_info
    if version.major != 3 or version.minor < 8:
        print(f"❌ Python {version.major}.{version.minor} detected. Python 3.8+ is required.")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} detected.")
    return True

def install_dependencies() -> bool:
    """Install required dependencies."""
    print("\n📦 Installing dependencies...")
    
    # Upgrade pip first
    if not run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], 
                      "Upgrading pip"):
        return False
    
    # Install requirements
    if not run_command([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      "Installing requirements"):
        return False
    
    return True

def generate_icon() -> bool:
    """Generate application icon if it doesn't exist."""
    icon_path = pathlib.Path("assets/app_icon.png")
    
    if icon_path.exists():
        print(f"✅ Icon already exists: {icon_path}")
        return True
    
    print("\n🎨 Generating application icon...")
    try:
        # Import and run icon generation
        from pdf_merger_simple import generate_icon, ICON_PATH
        generate_icon(ICON_PATH)
        print(f"✅ Icon generated: {ICON_PATH}")
        return True
    except Exception as e:
        print(f"❌ Failed to generate icon: {e}")
        return False

def clean_build_directories() -> None:
    """Clean up previous build artifacts."""
    print("[CLEAN] Cleaning build directories...")
    
    dirs_to_clean = ['build', 'dist', '__pycache__']
    files_to_clean = ['*.pyc', '*.pyo']
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
            print(f"Removed: {dir_name}")
    
    # Clean pyc files
    for root, dirs, files in os.walk('.'):
        for file in files:
            if file.endswith(('.pyc', '.pyo')):
                os.remove(os.path.join(root, file))

def build_executable() -> bool:
    """Build the executable using PyInstaller."""
    print("\n🔧 Building executable...")
    
    # Use spec file for better control
    cmd = [sys.executable, "-m", "PyInstaller", "--clean", "pdf_merger.spec"]
    
    return run_command(cmd, "Building with PyInstaller")

def test_executable() -> bool:
    """Test if the executable was created successfully."""
    print("[TEST] Testing executable...")
    
    exe_path = pathlib.Path("dist/PDFMerger.exe")
    if not exe_path.exists():
        print(f"[ERROR] Executable not found: {exe_path}")
        return False
    
    file_size = exe_path.stat().st_size / (1024 * 1024)  # MB
    print(f"✅ Executable created: {exe_path} ({file_size:.1f} MB)")
    
    return True

def main():
    """Main build process."""
    print("PDF Merger - Build Script")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Clean previous builds
    clean_build_directories()
    
    # Install dependencies
    if not install_dependencies():
        print("❌ Failed to install dependencies")
        return False
    
    # Generate icon
    if not generate_icon():
        print("⚠️  Warning: Icon generation failed, continuing without icon")
    
    # Build executable
    if not build_executable():
        print("❌ Failed to build executable")
        return False
    
    # Test executable
    if not test_executable():
        print("[ERROR] Executable test failed")
        return False
    
    print("[OK] Build completed successfully!")
    print("[INFO] Check the 'dist' folder for your executable.")
    
    # Show final instructions
    print("[INFO] Final steps:")
    print("1. Test the executable by running it")
    print("2. The executable is portable and includes all dependencies")
    print("3. No console window will appear when running the executable")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

