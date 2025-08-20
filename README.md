# PDF Merger Application

A simple PyQt6-based application for merging PDF files with thumbnail previews.

## Features

- Drag and drop PDF files
- Thumbnail previews for each PDF
- PDF preview with multiple pages
- Merge multiple PDFs into one
- Modern dark UI

## Fixes Applied

This version includes the following fixes for PyInstaller builds:

1. **Multiple Console Windows**: Fixed subprocess calls to hide console windows when running as Windows executable
2. **Slow Thumbnail Loading**: Optimized thumbnail generation with caching and sequential processing
3. **Application Hanging**: Improved threading management and resource cleanup

## Installation

1. Install Python 3.8+ 
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running from Source

```bash
python pdf_merger_simple.py
```

## Building Executable

1. Run the build script:
   ```bash
   python build.py
   ```

2. Or manually with PyInstaller:
   ```bash
   pyinstaller pdf_merger_simple.spec
   ```

The executable will be created in the `dist` directory.

## Requirements

- Python 3.8+
- PyQt6
- pypdf
- pdf2image
- Pillow
- pyinstaller (for building)
- Poppler (for PDF rendering)

### Poppler Installation

For pdf2image to work, you need Poppler:

**Windows:**
- Download Poppler from: https://github.com/oschwartz10612/poppler-windows/releases/
- Extract to `C:\poppler` or add to PATH

**Linux:**
```bash
sudo apt-get install poppler-utils
```

**macOS:**
```bash
brew install poppler
```

## Notes

- The application automatically detects PyInstaller environment and adjusts subprocess behavior
- Thumbnails are cached to improve performance
- Files are processed sequentially to prevent thread overload
- Console windows are hidden in Windows executable builds