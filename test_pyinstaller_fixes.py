#!/usr/bin/env python3
"""
Test script for PyInstaller compatibility functions.
This tests the core fixes without requiring GUI libraries.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

# Add the current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_frozen_detection():
    """Test the is_frozen function."""
    # Mock PyInstaller environment
    original_frozen = getattr(sys, 'frozen', None)
    original_meipass = getattr(sys, '_MEIPASS', None)
    
    try:
        # Test non-frozen
        if hasattr(sys, 'frozen'):
            delattr(sys, 'frozen')
        if hasattr(sys, '_MEIPASS'):
            delattr(sys, '_MEIPASS')
        
        # Import after clearing attributes
        import pdf_merger_simple
        # Reload to get fresh state
        import importlib
        importlib.reload(pdf_merger_simple)
        
        assert not pdf_merger_simple.is_frozen(), "Should not be frozen in normal environment"
        print("✓ Non-frozen detection works")
        
        # Test frozen
        sys.frozen = True
        sys._MEIPASS = '/tmp/test'
        importlib.reload(pdf_merger_simple)
        
        assert pdf_merger_simple.is_frozen(), "Should be frozen with mocked attributes"
        print("✓ Frozen detection works")
        
    finally:
        # Restore original values
        if original_frozen is not None:
            sys.frozen = original_frozen
        elif hasattr(sys, 'frozen'):
            delattr(sys, 'frozen')
            
        if original_meipass is not None:
            sys._MEIPASS = original_meipass
        elif hasattr(sys, '_MEIPASS'):
            delattr(sys, '_MEIPASS')


def test_subprocess_flags():
    """Test subprocess creation flags."""
    import pdf_merger_simple
    
    # Test Windows + frozen
    original_platform = sys.platform
    original_frozen = getattr(sys, 'frozen', None)
    
    try:
        sys.platform = 'win32'
        sys.frozen = True
        sys._MEIPASS = '/tmp/test'
        
        import importlib
        importlib.reload(pdf_merger_simple)
        
        flags = pdf_merger_simple.get_subprocess_creation_flags()
        if hasattr(subprocess, 'CREATE_NO_WINDOW'):
            assert flags == subprocess.CREATE_NO_WINDOW, f"Expected CREATE_NO_WINDOW, got {flags}"
            print("✓ Windows subprocess flags work")
        else:
            print("⚠ CREATE_NO_WINDOW not available (non-Windows system)")
        
        # Test non-Windows
        sys.platform = 'linux'
        importlib.reload(pdf_merger_simple)
        
        flags = pdf_merger_simple.get_subprocess_creation_flags()
        assert flags == 0, f"Expected 0 for non-Windows, got {flags}"
        print("✓ Non-Windows subprocess flags work")
        
    finally:
        sys.platform = original_platform
        if original_frozen is not None:
            sys.frozen = original_frozen
        elif hasattr(sys, 'frozen'):
            delattr(sys, 'frozen')


def test_resource_paths():
    """Test resource path detection."""
    import pdf_merger_simple
    import importlib
    
    # Test normal mode
    if hasattr(sys, 'frozen'):
        delattr(sys, 'frozen')
    if hasattr(sys, '_MEIPASS'):
        delattr(sys, '_MEIPASS')
        
    importlib.reload(pdf_merger_simple)
    
    normal_path = pdf_merger_simple.get_resource_path()
    expected_normal = Path(__file__).parent / "assets"
    
    # The paths should be equivalent (may differ in resolution)
    assert normal_path.name == "assets", f"Expected assets dir, got {normal_path}"
    print("✓ Normal resource path works")
    
    # Test frozen mode
    with tempfile.TemporaryDirectory() as temp_dir:
        sys.frozen = True
        sys._MEIPASS = temp_dir
        
        importlib.reload(pdf_merger_simple)
        
        frozen_path = pdf_merger_simple.get_resource_path()
        expected_frozen = Path(temp_dir) / "assets"
        
        assert str(frozen_path) == str(expected_frozen), f"Expected {expected_frozen}, got {frozen_path}"
        print("✓ Frozen resource path works")
        
    # Cleanup
    if hasattr(sys, 'frozen'):
        delattr(sys, 'frozen')
    if hasattr(sys, '_MEIPASS'):
        delattr(sys, '_MEIPASS')


def main():
    """Run all tests."""
    print("Testing PyInstaller compatibility functions...")
    print("=" * 50)
    
    try:
        test_frozen_detection()
        test_subprocess_flags()
        test_resource_paths()
        
        print("=" * 50)
        print("✓ All tests passed!")
        return 0
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())