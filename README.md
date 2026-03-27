# ImageToAscii

Convert images to ASCII art from the command line or a local web UI.

## Requirements

Python 3.12

```bash
pip install -r requirements.txt
```

Dependencies: `Pillow`, `numpy`, `scipy` (edge detection), `rembg` (background removal), `fastapi`, `uvicorn`, `python-multipart`.

---

## Command-line usage

```bash
python ascii_art.py <image> [options]
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--width` / `-w` | `80` | Output width in characters |
| `--chars` / `-c` | `standard` | Char set preset (`standard`, `dense`, `block`, `minimal`) or a custom string ordered light→dark |
| `--invert` | off | Invert brightness mapping |
| `--color` | off | ANSI 24-bit colour output |
| `--contrast` | off | Auto-stretch grayscale histogram |
| `--sharpen FACTOR` | `1.0` | Sharpness after resize (try `2.0`) |
| `--gamma GAMMA` | `1.0` | Brightness curve — `< 1.0` brightens midtones |
| `--dither` | off | Floyd-Steinberg dithering for smoother gradients |
| `--edge-strength STRENGTH` | `0.0` | Fraction of pixels drawn as directional edge chars (`\|`, `\`, `-`, `/`); try `0.15` |
| `--aspect RATIO` | `0.45` | Height correction for terminal font aspect ratio (typical range `0.40`–`0.55`) |
| `--isolate` / `-i` | off | Remove background via rembg (~170 MB model downloaded on first run) |
| `--output` / `-o` | — | Save to `.txt` (plain text) or `.html` (colour-preserving standalone file) |

### Examples

```bash
# Basic
python ascii_art.py wolf.jpg

# High-quality photo
python ascii_art.py wolf.jpg --contrast --sharpen 2.0 --gamma 0.8 --dither --edge-strength 0.15 --width 120

# Colour output saved as HTML
python ascii_art.py wolf.jpg --color --contrast --output wolf.html

# Custom character set
python ascii_art.py photo.jpg --chars ' .:-=+*#%@'

# Isolated subject on white background
python ascii_art.py photo.jpg --isolate --invert --width 100
```

---

## Web UI

```bash
python web_ui.py
# open http://127.0.0.1:8000
```

Upload an image, adjust controls, and see ASCII art update live in the browser (300 ms debounce). All CLI options are available. In-flight requests are cancelled automatically when settings change, so results are never stale.

### Controls

| Control | Description |
|---|---|
| Width | Characters per line |
| Char set | Preset or custom string |
| Custom chars | Overrides the preset when non-empty |
| Sharpen | Post-resize sharpness |
| Gamma | Brightness curve |
| Edge strength | Directional edge overlay (0 = off) |
| Aspect ratio | Tune if output looks squashed or stretched |
| Auto contrast | Stretch histogram |
| Invert | Invert brightness |
| Dither | Floyd-Steinberg dithering |
| Colour output | Per-character colour via ANSI→HTML spans |
| Remove background | Run rembg (result cached for the session) |
| Font size | Preview zoom — no re-render |

### Output

- **Copy to clipboard** — copies plain text
- **Save .txt** — downloads plain ASCII text
- **Save .html** — downloads a self-contained HTML file that preserves colours
