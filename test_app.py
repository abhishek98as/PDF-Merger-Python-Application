#!/usr/bin/env python3
"""
Simple test script to validate PDF Merger application functionality.
"""

import sys
import pathlib
import tempfile
import logging
from io import StringIO

def test_imports():
    """Test that all required modules can be imported."""
    print("🧪 Testing imports...")
    
    try:
        import PyQt6.QtCore
        import PyQt6.QtGui
        import PyQt6.QtWidgets
        print("✅ PyQt6 imports successful")
    except ImportError as e:
        print(f"❌ PyQt6 import failed: {e}")
        return False
    
    try:
        import pypdf
        print("✅ pypdf import successful")
    except ImportError as e:
        print(f"❌ pypdf import failed: {e}")
        return False
    
    try:
        import pdf2image
        print("✅ pdf2image import successful")
    except ImportError as e:
        print(f"❌ pdf2image import failed: {e}")
        return False
    
    try:
        from PIL import Image, ImageDraw, ImageFont
        print("✅ PIL imports successful")
    except ImportError as e:
        print(f"❌ PIL import failed: {e}")
        return False
    
    return True

def test_application_startup():
    """Test that the application can start up without errors."""
    print("\n🧪 Testing application startup...")
    
    try:
        # Redirect stdout to capture any error messages
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        
        # Import the main application
        from pdf_merger_simple import SimpleMainWindow, ensure_icon, ICON_PATH
        from PyQt6.QtWidgets import QApplication
        
        # Restore stdout/stderr
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        
        print("✅ Application import successful")
        
        # Test icon generation
        ensure_icon()
        if ICON_PATH.exists():
            print("✅ Icon generation successful")
        else:
            print("⚠️  Icon generation failed, but this is not critical")
        
        return True
        
    except Exception as e:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        print(f"❌ Application startup test failed: {e}")
        return False

def test_worker_manager():
    """Test the WorkerManager functionality."""
    print("\n🧪 Testing WorkerManager...")
    
    try:
        from pdf_merger_simple import WorkerManager
        
        # Create a test worker manager
        manager = WorkerManager()
        
        # Test basic functionality
        test_path = pathlib.Path("test.pdf")
        
        assert not manager.is_processing_thumbnail(test_path)
        assert not manager.is_processing_pages(test_path)
        assert manager.get_cached_thumbnail(test_path) is None
        
        print("✅ WorkerManager basic functionality works")
        
        # Test cleanup
        manager.cleanup_all()
        print("✅ WorkerManager cleanup works")
        
        return True
        
    except Exception as e:
        print(f"❌ WorkerManager test failed: {e}")
        return False

def test_pdf_utilities():
    """Test PDF utility functions."""
    print("\n🧪 Testing PDF utilities...")
    
    try:
        from pdf_merger_simple import render_page_qpix
        from PyQt6.QtGui import QPixmap
        
        # Test with non-existent file (should return empty QPixmap)
        test_path = pathlib.Path("nonexistent.pdf")
        result = render_page_qpix(test_path)
        
        if isinstance(result, QPixmap):
            print("✅ render_page_qpix returns QPixmap type")
        else:
            print(f"❌ render_page_qpix returned {type(result)}, expected QPixmap")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ PDF utilities test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 PDF Merger Application Tests")
    print("=" * 40)
    
    # Suppress logging during tests
    logging.getLogger().setLevel(logging.CRITICAL)
    
    tests = [
        test_imports,
        test_application_startup,
        test_worker_manager,
        test_pdf_utilities,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                print(f"❌ Test {test.__name__} failed")
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The application is ready to build.")
        return True
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
