#!/bin/bash

echo "PDF Merger - Unix Build Script"
echo "================================"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed or not in PATH"
    echo "Please install Python 3.8+ from your package manager or https://python.org"
    exit 1
fi

# Run the build script
echo "Starting build process..."
python3 build_exe.py

# Check if build was successful
if [ $? -eq 0 ]; then
    echo
    echo "Build completed successfully!"
    echo "The executable is located in the 'dist' folder."
    echo
    
    # Try to open the dist folder
    if command -v xdg-open &> /dev/null; then
        echo "Opening dist folder..."
        xdg-open dist
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        echo "Opening dist folder..."
        open dist
    fi
else
    echo
    echo "Build failed! Check the error messages above."
    exit 1
fi
