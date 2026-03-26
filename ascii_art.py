#!/usr/bin/env python3
"""
ASCII Art Generator
Converts an image to ASCII art, with optional background removal to isolate
the subject before conversion.

Usage:
    python ascii_art.py <image> [options]

Requirements (Python 3.12):
    pip install Pillow rembg
    pip install numpy  # optional, required for --dither
"""

import argparse
import sys
import re
from pathlib import Path


# Character sets ordered from lightest (empty) to darkest (full)
CHAR_SETS = {
    "standard":  ' .\'`^",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$',
    "dense":     ' .:-=+*#%@',
    "block":     ' ░▒▓█',
    "minimal":   ' .:+#@',
}


def load_image(path: str):
    """Load an image from disk."""
    from PIL import Image
    try:
        img = Image.open(path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        return img
    except FileNotFoundError:
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading image: {e}", file=sys.stderr)
        sys.exit(1)


def remove_background(img):
    """
    Remove the background from an image using rembg.
    Returns an RGBA image; transparent pixels become white.
    """
    try:
        from rembg import remove as rembg_remove
        print("Removing background (first run downloads model ~170 MB)...", file=sys.stderr)
        result = rembg_remove(img)  # returns RGBA
        # Composite onto white so transparent areas read as light in grayscale
        from PIL import Image
        white = Image.new("RGBA", result.size, (255, 255, 255, 255))
        white.paste(result, mask=result.split()[3])
        return white.convert("RGB")
    except ImportError:
        print("Warning: rembg not installed; skipping background removal.", file=sys.stderr)
        print("         Install with: pip install rembg", file=sys.stderr)
        return img
    except Exception as e:
        print(f"Warning: background removal failed ({e}); using original image.", file=sys.stderr)
        return img


def image_to_ascii(
    img,
    width: int = 80,
    char_set: str = "standard",
    invert: bool = False,
    color: bool = False,
    contrast: bool = False,
    sharpen: float = 1.0,
    gamma: float = 1.0,
    dither: bool = False,
) -> str:
    """
    Convert a PIL image to an ASCII string.

    Args:
        img:       PIL Image (RGB or RGBA)
        width:     number of characters per line
        char_set:  key into CHAR_SETS
        invert:    invert brightness (useful for dark subjects on white bg)
        color:     wrap each character in ANSI 24-bit color escape codes
        contrast:  auto-stretch the grayscale histogram for maximum tonal range
        sharpen:   sharpness multiplier applied after resize (1.0 = no change)
        gamma:     brightness gamma before char mapping (< 1.0 = brighter midtones)
        dither:    use Floyd-Steinberg dithering to simulate intermediate tones

    Returns:
        Multi-line ASCII string (with ANSI codes if color=True)
    """
    from PIL import Image, ImageEnhance, ImageOps

    chars = CHAR_SETS.get(char_set, CHAR_SETS["standard"])

    # Resize: terminal characters are ~0.5 wide as they are tall,
    # so we scale height down to keep proportions correct.
    aspect = img.height / img.width
    height = max(1, int(width * aspect * 0.45))
    img_resized = img.resize((width, height), Image.LANCZOS)

    # Sharpen after resize to recover edge detail lost during downscaling
    if sharpen != 1.0:
        img_resized = ImageEnhance.Sharpness(img_resized).enhance(sharpen)

    rgb = img_resized.convert("RGB")
    gray = img_resized.convert("L")

    # Stretch histogram so the full character range is used
    if contrast:
        gray = ImageOps.autocontrast(gray, cutoff=2)

    if invert:
        gray = ImageOps.invert(gray)

    n = len(chars) - 1

    # Floyd-Steinberg dithering — distributes quantization error to neighbours,
    # giving the illusion of more tones than the character set can represent.
    if dither:
        try:
            import numpy as np
            gray_arr = np.array(gray, dtype=float)
            lines = []
            for y in range(height):
                row = []
                for x in range(width):
                    val = float(np.clip(gray_arr[y, x], 0, 255))
                    normalized = (val / 255.0) ** gamma
                    idx = max(0, min(n, int(normalized * n)))
                    ch = chars[idx]
                    quant_error = val - (idx / n * 255.0)
                    if x + 1 < width:
                        gray_arr[y, x + 1] += quant_error * 7 / 16
                    if y + 1 < height:
                        if x > 0:
                            gray_arr[y + 1, x - 1] += quant_error * 3 / 16
                        gray_arr[y + 1, x] += quant_error * 5 / 16
                        if x + 1 < width:
                            gray_arr[y + 1, x + 1] += quant_error * 1 / 16
                    if color:
                        r, g, b = rgb.getpixel((x, y))
                        row.append(f"\033[38;2;{r};{g};{b}m{ch}")
                    else:
                        row.append(ch)
                lines.append("".join(row) + "\033[0m" if color else "".join(row))
            return "\n".join(lines)
        except ImportError:
            print("Warning: numpy not installed; --dither requires numpy (pip install numpy).", file=sys.stderr)

    # Standard brightness mapping with optional gamma correction
    lines = []
    for y in range(height):
        row = []
        for x in range(width):
            brightness = gray.getpixel((x, y))
            normalized = (brightness / 255.0) ** gamma
            idx = max(0, min(n, int(normalized * n)))
            ch = chars[idx]
            if color:
                r, g, b = rgb.getpixel((x, y))
                row.append(f"\033[38;2;{r};{g};{b}m{ch}")
            else:
                row.append(ch)
        lines.append("".join(row) + "\033[0m" if color else "".join(row))

    return "\n".join(lines)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string (for saving to file)."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def main():
    parser = argparse.ArgumentParser(
        description="Convert an image to ASCII art, optionally isolating the subject first."
    )
    parser.add_argument("image", help="Path to input image")
    parser.add_argument(
        "--isolate", "-i",
        action="store_true",
        help="Remove background before converting (requires rembg)",
    )
    parser.add_argument(
        "--width", "-w",
        type=int,
        default=80,
        help="Output width in characters (default: 80)",
    )
    parser.add_argument(
        "--chars", "-c",
        choices=list(CHAR_SETS.keys()),
        default="standard",
        help="Character set to use (default: standard)",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert brightness (use for light subjects on dark backgrounds)",
    )
    parser.add_argument(
        "--color",
        action="store_true",
        help="Use ANSI 24-bit color codes in terminal output",
    )
    parser.add_argument(
        "--contrast",
        action="store_true",
        help="Auto-stretch the grayscale histogram to maximize tonal range",
    )
    parser.add_argument(
        "--sharpen",
        type=float,
        default=1.0,
        metavar="FACTOR",
        help="Sharpness factor applied after resize (1.0 = unchanged, 2.0 = sharper)",
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=1.0,
        metavar="GAMMA",
        help="Brightness gamma before char mapping (< 1.0 brightens midtones, > 1.0 darkens; default: 1.0)",
    )
    parser.add_argument(
        "--dither",
        action="store_true",
        help="Apply Floyd-Steinberg dithering for smoother tonal gradients (requires numpy)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Save ASCII art to file (ANSI codes stripped automatically)",
    )
    args = parser.parse_args()

    img = load_image(args.image)
    print(f"Loaded: {args.image} ({img.width}x{img.height})", file=sys.stderr)

    if args.isolate:
        img = remove_background(img)
        print("Background removed.", file=sys.stderr)

    ascii_art = image_to_ascii(
        img,
        width=args.width,
        char_set=args.chars,
        invert=args.invert,
        color=args.color,
        contrast=args.contrast,
        sharpen=args.sharpen,
        gamma=args.gamma,
        dither=args.dither,
    )

    # Print to terminal
    print(ascii_art)

    # Save to file if requested
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(strip_ansi(ascii_art))
        print(f"Saved to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
