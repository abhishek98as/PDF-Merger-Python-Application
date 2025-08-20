"""Convert PNG icon to ICO format.

This script takes the generated PNG app_icon from assets folder
and converts it to an ICO file with multiple sizes for Windows.
"""
import os
import sys
from pathlib import Path
from PIL import Image


def png_to_ico(png_path, ico_path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    """Convert PNG to ICO with multiple sizes."""
    if not os.path.exists(png_path):
        print(f"Error: Source PNG file not found at {png_path}")
        return False
    
    img = Image.open(png_path)
    # Convert to RGBA if not already
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    try:
        # Create scaled versions
        icon_sizes = []
        for size in sizes:
            try:
                # Use LANCZOS for better quality if available (Pillow 9.1.0+)
                resample = getattr(Image, "Resampling", Image).LANCZOS
            except AttributeError:
                # Fallback for older Pillow versions
                resample = getattr(Image, "LANCZOS", getattr(Image, "ANTIALIAS", 1))
            
            scaled_img = img.resize((size, size), resample)
            icon_sizes.append(scaled_img)
        
        # Save as ICO with all sizes
        img.save(ico_path, format='ICO', sizes=[(s.width, s.height) for s in icon_sizes])
        print(f"Created ICO file: {ico_path}")
        return True
    except Exception as e:
        print(f"Error creating ICO file: {e}")
        # Fallback - try simpler approach with fewer sizes
        try:
            img.save(ico_path, format='ICO')
            print(f"Created simple ICO file: {ico_path}")
            return True
        except Exception as e2:
            print(f"Failed to create even simple ICO: {e2}")
            return False


if __name__ == "__main__":
    # Get directory where script is located
    base_dir = Path(__file__).resolve().parent
    assets_dir = base_dir / "assets"
    
    # Source and destination paths
    png_path = assets_dir / "app_icon.png"
    ico_path = assets_dir / "app_icon.ico"
    
    # Ensure assets directory exists
    assets_dir.mkdir(exist_ok=True)
    
    # If PNG doesn't exist, try to generate it first
    if not png_path.exists():
        print("PNG icon not found, generating it first...")
        sys.path.append(str(base_dir / "src"))
        try:
            from main import generate_icon
            generate_icon(png_path)
        except ImportError:
            print("Error: Couldn't import icon generator")
            sys.exit(1)
    
    # Convert PNG to ICO
    if png_to_ico(png_path, ico_path):
        print("Successfully converted PNG to ICO with multiple sizes")
    else:
        print("Failed to create ICO file")
        sys.exit(1)
