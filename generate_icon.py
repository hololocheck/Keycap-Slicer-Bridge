#!/usr/bin/env python3
"""
Generate icon.ico from keycapgeneratorIcon.svg
Run this BEFORE PyInstaller build:
  pip install cairosvg Pillow
  python generate_icon.py
"""
import os
import sys

def generate_with_cairosvg():
    """High-quality SVG → ICO using cairosvg"""
    import cairosvg
    from PIL import Image
    import io

    svg_path = os.path.join(os.path.dirname(__file__), "keycapgeneratorIcon.svg")
    if not os.path.exists(svg_path):
        print(f"Error: {svg_path} not found")
        sys.exit(1)

    with open(svg_path, 'rb') as f:
        svg_data = f.read()

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        png_data = cairosvg.svg2png(bytestring=svg_data, output_width=sz, output_height=sz)
        img = Image.open(io.BytesIO(png_data)).convert('RGBA')
        images.append(img)
        print(f"  Generated {sz}x{sz}")

    ico_path = os.path.join(os.path.dirname(__file__), "icon.ico")
    images[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"\nCreated: {ico_path}")
    return ico_path

def generate_with_pillow():
    """Fallback: PIL polygon drawing"""
    from keycap_slicer_bridge import create_keycap_icon
    from PIL import Image

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [create_keycap_icon(sz) for sz in sizes]

    ico_path = os.path.join(os.path.dirname(__file__), "icon.ico")
    images[0].save(ico_path, format='ICO', sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"Created (PIL fallback): {ico_path}")
    return ico_path

if __name__ == '__main__':
    print("Generating icon.ico...")
    try:
        generate_with_cairosvg()
    except ImportError:
        print("cairosvg not found, using PIL fallback (lower quality)")
        print("For best quality: pip install cairosvg")
        generate_with_pillow()
