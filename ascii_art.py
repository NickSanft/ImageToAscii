#!/usr/bin/env python3
"""
ASCII Art Generator
Converts an image to ASCII art, with optional background removal to isolate
the subject before conversion.

Usage:
    python ascii_art.py <image> [options]

Requirements (Python 3.12):
    pip install Pillow rembg numpy
    scipy is used for --edge-strength (installed automatically with rembg)
"""

import argparse
import html as html_module
import re
import sys
from pathlib import Path


# Character sets ordered from lightest (empty) to darkest (full)
CHAR_SETS = {
    "standard":  ' .\'`^",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$',
    "dense":     ' .:-=+*#%@',
    "block":     ' ░▒▓█',
    "minimal":   ' .:+#@',
}

# ── ANSI → HTML ──────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"(\x1b\[[0-9;]*m)")


def ansi_to_html(text: str) -> str:
    """Convert ANSI 24-bit colour escapes to HTML <span> elements."""
    parts = _ANSI_RE.split(text)
    out: list[str] = []
    open_span = False
    for part in parts:
        if part.startswith("\x1b["):
            codes = part[2:-1]
            if codes in ("0", ""):
                if open_span:
                    out.append("</span>")
                    open_span = False
            elif codes.startswith("38;2;"):
                if open_span:
                    out.append("</span>")
                r, g, b = codes[5:].split(";")
                out.append(f'<span style="color:rgb({r},{g},{b})">')
                open_span = True
        else:
            out.append(html_module.escape(part))
    if open_span:
        out.append("</span>")
    return "".join(out)


def ascii_to_html_document(ascii_text: str) -> str:
    """Wrap ASCII art in a self-contained HTML document, preserving ANSI colour."""
    body = ansi_to_html(ascii_text)
    css = (
        "body { background: #0f0f0f; margin: 0; padding: 16px; }\n"
        "pre  { font-family: 'Courier New', Courier, monospace;\n"
        "       font-size: 12px; line-height: 1.15;\n"
        "       color: #cccccc; white-space: pre; }"
    )
    return (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="utf-8">\n<title>ASCII Art</title>\n'
        f'<style>\n{css}\n</style>\n'
        f'</head>\n<body><pre>{body}</pre></body>\n</html>\n'
    )


# ── Image loading and processing ─────────────────────────────────────────────

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
    Returns an RGB image with transparent areas composited onto white.
    """
    try:
        from rembg import remove as rembg_remove
        print("Removing background (first run downloads model ~170 MB)...", file=sys.stderr)
        result = rembg_remove(img)
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


# ── Core conversion ───────────────────────────────────────────────────────────

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
    edge_strength: float = 0.0,
    aspect: float = 0.45,
) -> str:
    """
    Convert a PIL image to an ASCII string.

    Args:
        img:            PIL Image (RGB or RGBA)
        width:          number of characters per line
        char_set:       preset name (key in CHAR_SETS) or a custom string ordered light→dark
        invert:         invert brightness mapping
        color:          wrap each character in ANSI 24-bit colour escape codes
        contrast:       auto-stretch the grayscale histogram for maximum tonal range
        sharpen:        sharpness factor applied after resize (1.0 = no change)
        gamma:          brightness gamma before char mapping (< 1.0 = brighter midtones)
        dither:         use Floyd-Steinberg dithering to simulate intermediate tones
        edge_strength:  fraction of pixels treated as directional edge characters (0.0 = off)
        aspect:         height correction for terminal/font character aspect ratio

    Returns:
        Multi-line ASCII string (with ANSI codes if color=True)
    """
    import numpy as np
    from PIL import Image, ImageEnhance, ImageOps

    # Resolve char set: preset name or literal string
    if char_set in CHAR_SETS:
        chars = CHAR_SETS[char_set]
    elif len(char_set) >= 2:
        chars = char_set
    else:
        chars = CHAR_SETS["standard"]

    n = len(chars) - 1

    # Resize with aspect-ratio correction
    img_aspect = img.height / img.width
    height = max(1, int(width * img_aspect * aspect))
    img_resized = img.resize((width, height), Image.LANCZOS)

    # Sharpen after resize to recover edge detail lost during downscaling
    if sharpen != 1.0:
        img_resized = ImageEnhance.Sharpness(img_resized).enhance(sharpen)

    rgb = img_resized.convert("RGB")
    gray = img_resized.convert("L")

    if contrast:
        gray = ImageOps.autocontrast(gray, cutoff=2)
    if invert:
        gray = ImageOps.invert(gray)

    gray_np = np.array(gray, dtype=np.float32)

    # ── Edge detection overlay ────────────────────────────────────────────
    # Uses Sobel gradients to find edge magnitude and direction, then
    # replaces the top `edge_strength` fraction of pixels with directional
    # characters (|, \, -, /) that follow the local edge angle.
    edge_mask = None
    edge_dir_chars = None
    if edge_strength > 0.0:
        try:
            from scipy.ndimage import sobel
            sx = sobel(gray_np, axis=1)  # horizontal gradient
            sy = sobel(gray_np, axis=0)  # vertical gradient
            magnitude = np.hypot(sx, sy)
            threshold = np.percentile(magnitude, (1.0 - edge_strength) * 100)
            edge_mask = magnitude >= threshold

            # Map gradient angle to the perpendicular edge character.
            # angle % 180 bins → ['|', '\', '-', '/', '|']
            angle_mod = np.degrees(np.arctan2(sy, sx)) % 180
            dir_idx = np.digitize(angle_mod, [22.5, 67.5, 112.5, 157.5])
            edge_dir_chars = np.array(['|', '\\', '-', '/', '|'])[dir_idx]
        except ImportError:
            print(
                "Warning: scipy not installed; --edge-strength requires scipy "
                "(pip install scipy).",
                file=sys.stderr,
            )

    # ── Floyd-Steinberg dithering (sequential by nature) ─────────────────
    if dither:
        gray_arr = gray_np.copy().astype(float)
        rgb_np = np.array(rgb) if color else None
        lines = []
        for y in range(height):
            row = []
            for x in range(width):
                val = float(np.clip(gray_arr[y, x], 0, 255))
                normalized = (val / 255.0) ** gamma if gamma != 1.0 else val / 255.0
                idx = max(0, min(n, int(normalized * n)))

                if edge_mask is not None and bool(edge_mask[y, x]):
                    ch = str(edge_dir_chars[y, x])
                else:
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
                    r, g_val, b_val = rgb_np[y, x]
                    row.append(f"\033[38;2;{r};{g_val};{b_val}m{ch}")
                else:
                    row.append(ch)
            lines.append("".join(row) + "\033[0m" if color else "".join(row))
        return "\n".join(lines)

    # ── Vectorised brightness mapping ─────────────────────────────────────
    normalized = gray_np / 255.0
    if gamma != 1.0:
        normalized = np.power(normalized, gamma)
    idx_arr = np.clip((normalized * n).astype(np.int32), 0, n)

    chars_arr = np.array(list(chars))
    char_grid = chars_arr[idx_arr]  # (height, width) array of characters

    if edge_mask is not None:
        char_grid = np.where(edge_mask, edge_dir_chars, char_grid)

    if not color:
        return "\n".join("".join(row) for row in char_grid)

    # Colour mode: one ANSI escape per character
    rgb_np = np.array(rgb)
    lines = []
    for y in range(height):
        row = []
        for x in range(width):
            ch = char_grid[y, x]
            r, g_val, b_val = rgb_np[y, x]
            row.append(f"\033[38;2;{r};{g_val};{b_val}m{ch}")
        lines.append("".join(row) + "\033[0m")
    return "\n".join(lines)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from a string (for saving as plain text)."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


# ── CLI ───────────────────────────────────────────────────────────────────────

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
        default="standard",
        help=(
            "Character set: standard, dense, block, minimal, "
            "or a custom string ordered light→dark (e.g. ' .:-+#@')"
        ),
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="Invert brightness (use for light subjects on dark backgrounds)",
    )
    parser.add_argument(
        "--color",
        action="store_true",
        help="Use ANSI 24-bit colour codes in terminal output",
    )
    parser.add_argument(
        "--contrast",
        action="store_true",
        help="Auto-stretch the grayscale histogram to maximise tonal range",
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
        help="Brightness gamma (< 1.0 brightens midtones, > 1.0 darkens; default: 1.0)",
    )
    parser.add_argument(
        "--dither",
        action="store_true",
        help="Apply Floyd-Steinberg dithering for smoother tonal gradients",
    )
    parser.add_argument(
        "--edge-strength",
        type=float,
        default=0.0,
        metavar="STRENGTH",
        dest="edge_strength",
        help=(
            "Fraction of pixels rendered as directional edge characters "
            "(0.0 = off, 0.1–0.3 recommended; requires scipy)"
        ),
    )
    parser.add_argument(
        "--aspect",
        type=float,
        default=0.45,
        metavar="RATIO",
        help=(
            "Height correction for terminal character aspect ratio "
            "(default: 0.45; typical range 0.40–0.55)"
        ),
    )
    parser.add_argument(
        "--output", "-o",
        help=(
            "Save output to a file. Use .txt for plain text or "
            ".html for a colour-preserving standalone HTML file."
        ),
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
        edge_strength=args.edge_strength,
        aspect=args.aspect,
    )

    print(ascii_art)

    if args.output:
        out_path = Path(args.output)
        if out_path.suffix.lower() == ".html":
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(ascii_to_html_document(ascii_art), encoding="utf-8")
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(strip_ansi(ascii_art))
        print(f"Saved to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
