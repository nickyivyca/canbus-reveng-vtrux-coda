#!/usr/bin/env python3
"""CODACAN screenshot capture and OCR tool.

Replaces Claude Cowork as the visual observer for CODACAN signal validation.
Reads cowork_state.json written by cowork_replay.py to synchronize captures
with the current experiment step.

Sub-commands:

  init-layout   Build ui_layout.json from reference screenshots (offline, no hardware
                needed). Auto-detects value boxes and LED indicators. Saves annotated
                PNGs for user review. Run once before any experiments.

  calibrate     Interactive live fine-tuning of coordinates with CODACAN open.
                Walk through un-named (auto_NNN) fields to assign positions and names.

  snapshot      One-shot capture of all calibrated fields across specified tabs.
                Write a JSON report. Use during baseline/drop-id/solo-id experiments.

  watch         Continuous mode. Poll cowork_state.json and auto-capture after each
                sweep step. Merge into sweep_results.json on completion.
                Use during sweep-byte experiments.

Usage:
    python tools/codacan_capture.py init-layout
    python tools/codacan_capture.py init-layout --screenshots-dir "projects/coda/logs/codacan-screenshots"
    python tools/codacan_capture.py calibrate
    python tools/codacan_capture.py snapshot --tabs BMS,DCDC
    python tools/codacan_capture.py watch --tabs BMS --state-file cowork_state.json

Dependencies:
    Required (all sub-commands):
        pip install Pillow

    Required (calibrate, snapshot, watch):
        pip install pyautogui

    Required for OCR (snapshot, watch):
        Option A: pip install pytesseract  (+ install Tesseract binary from https://github.com/UB-Mannheim/tesseract/wiki)
        Option B: pip install easyocr      (pip-only, larger download, no separate binary needed)

See projects/coda/notes/plans/codacan-python-capture-plan.md for full workflow.
"""
import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional: pyautogui (needed for calibrate / snapshot / watch)
# ---------------------------------------------------------------------------
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    _HAVE_PYAUTOGUI = True
except ImportError:
    _HAVE_PYAUTOGUI = False

# ---------------------------------------------------------------------------
# Optional OCR engine (needed for snapshot / watch)
# ---------------------------------------------------------------------------
_OCR_ENGINE = None   # 'tesseract' | 'easyocr' | None
_EASYOCR_READER = None

try:
    import pytesseract
    # On Windows, Tesseract is often not on PATH.  Try the standard install
    # location before falling through to the PATH-based probe.
    import os as _os
    _tess_default = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if _os.path.isfile(_tess_default) and pytesseract.pytesseract.tesseract_cmd == 'tesseract':
        pytesseract.pytesseract.tesseract_cmd = _tess_default
    # Verify the binary is actually reachable.
    pytesseract.get_tesseract_version()
    _OCR_ENGINE = 'tesseract'
except Exception:
    try:
        import easyocr as _easyocr_mod
        _OCR_ENGINE = 'easyocr'
    except ImportError:
        pass

# ---------------------------------------------------------------------------
# Pillow — required for everything
# ---------------------------------------------------------------------------
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("ERROR: Pillow is required. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_SCREENSHOTS_DIR = Path("projects/coda/logs/codacan-screenshots")
DEFAULT_LAYOUT_FILE     = Path("projects/coda/CODACAN/ui_layout.json")
DEFAULT_RESULTS_DIR     = Path("projects/coda/notes/artifacts/cowork-results")
DEFAULT_STATE_FILE      = Path("cowork_state.json")
DEFAULT_WINDOW_TITLE    = "CODACAN.vi"

TAB_NAMES = ["Overview", "BMS", "BMS 2", "DCDC", "Charging", "CH M/S", "HVAC", "Driveline", "IPK"]

# ---------------------------------------------------------------------------
# Layout I/O
# ---------------------------------------------------------------------------

def load_layout(path: Path) -> dict:
    if not path.exists():
        logger.error(f"Layout file not found: {path}")
        logger.error("Run 'init-layout' first to generate it.")
        sys.exit(1)
    return json.loads(path.read_text(encoding='utf-8'))


def save_layout(layout: dict, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(layout, indent=2), encoding='utf-8')
    logger.info(f"Saved layout: {path}")


# ---------------------------------------------------------------------------
# init-layout: detect boxes from reference screenshots (offline)
# ---------------------------------------------------------------------------

def scan_value_boxes(img: Image, skip_top: int, skip_bottom: int,
                     gray_min: int = 195, gray_max: int = 225,
                     achromatic_tol: int = 18,
                     min_w: int = 35, max_w: int = 220,
                     min_h: int = 13, max_h: int = 38,
                     gap_tolerance: int = 4,
                     min_fill: float = 0.40,
                     hgap_tol: int = 0) -> list:
    """
    Find LabVIEW numeric/text value boxes by detecting achromatic gray regions.

    CODACAN value boxes are #d2d2d2 (RGB 210, 210, 210) — pure achromatic gray —
    set against COLORED container backgrounds (green, pink/purple, yellow, etc.).
    The achromatic filter (max(R,G,B) - min(R,G,B) <= achromatic_tol) cleanly
    separates neutral-gray value boxes from any saturated background color.

    Returns list of (x1, y1, x2, y2) bounding boxes in image coordinates.

    Parameters:
        gray_min / gray_max: avg(R,G,B) must fall in this range (d2d2d2 ≈ 210)
        achromatic_tol: max channel spread allowed (d2d2d2 = 0; colored BGs >> 18)
        gap_tolerance: consecutive non-matching rows tolerated within an active box
                       (handles dark text strokes crossing the box interior)
        min_fill: minimum fraction of bbox pixels that must match d2d2d2 criteria.
                  Filters sparse false positives (e.g. car body photo regions in
                  Overview that contain occasional achromatic pixels).
    """
    rgb  = img.convert('RGB')
    W, H = rgb.size
    pix  = rgb.load()

    # Precompute achromatic-gray mask for the content band as a flat bytearray.
    # This avoids repeated pix[] lookups during the continuation check inner loop.
    y0 = skip_top
    y1 = H - skip_bottom
    h_content = y1 - y0
    mask = bytearray(W * h_content)   # 1 = matches, 0 = doesn't
    for yr in range(h_content):
        y    = yr + y0
        base = yr * W
        for x in range(W):
            r, g, b = pix[x, y]
            avg = (r + g + b) // 3
            if gray_min <= avg <= gray_max and max(r, g, b) - min(r, g, b) <= achromatic_tol:
                mask[base + x] = 1

    def row_runs(yr):
        """Horizontal runs of matching pixels in relative row yr.

        With hgap_tol > 0, up to hgap_tol consecutive non-matching pixels are
        bridged so that text character strokes (2-4 px) don't fragment the run.
        """
        base = yr * W
        runs = []
        start = None
        last_hit = None
        gap = 0

        for x in range(W):
            if mask[base + x]:
                if start is None:
                    start = x
                last_hit = x
                gap = 0
            else:
                if start is not None:
                    gap += 1
                    if gap > hgap_tol:
                        length = last_hit - start + 1
                        if min_w <= length <= max_w:
                            runs.append((start, last_hit))
                        start = None
                        last_hit = None
                        gap = 0

        if start is not None and last_hit is not None:
            length = last_hit - start + 1
            if min_w <= length <= max_w:
                runs.append((start, last_hit))
        return runs

    def has_match_in_range(yr, x1, x2):
        """True if any pixel in [x1, x2] on row yr matches."""
        base = yr * W
        return any(mask[base + x] for x in range(max(0, x1), min(W, x2)))

    def box_fill_ok(box_dict):
        """True if ≥ min_fill of the completed box's pixels match the d2d2d2 mask."""
        yr_s = max(0, box_dict['y_start'] - y0)
        yr_e = min(h_content, box_dict['y_last'] - y0 + 1)
        bx1  = box_dict['x1']
        bx2  = min(W, box_dict['x2'] + 1)
        n_total = (yr_e - yr_s) * (bx2 - bx1)
        if n_total == 0:
            return False
        n_match = sum(mask[yr * W + x] for yr in range(yr_s, yr_e) for x in range(bx1, bx2))
        return n_match / n_total >= min_fill

    active    = []   # list of {x1, x2, y_start, y_last, gap}  (abs y coords)
    completed = []
    seen      = set()

    for yr in range(h_content):
        y          = yr + y0
        start_runs = row_runs(yr)

        matched_active = set()
        start_run_used = set()

        for i, box in enumerate(active):
            bx1 = box['x1'] - 2
            bx2 = box['x2'] + 3
            if has_match_in_range(yr, bx1, bx2):
                # Extend x-range if any new full-width run overlaps
                for j, (rx1, rx2) in enumerate(start_runs):
                    if rx1 <= box['x2'] + 3 and rx2 >= box['x1'] - 3:
                        box['x1'] = min(box['x1'], rx1)
                        box['x2'] = max(box['x2'], rx2)
                        start_run_used.add(j)
                box['y_last'] = y
                box['gap']    = 0
                matched_active.add(i)
            else:
                box['gap'] = box.get('gap', 0) + 1
                if box['gap'] <= gap_tolerance:
                    matched_active.add(i)

        new_active = []
        for i, box in enumerate(active):
            if i in matched_active:
                new_active.append(box)
            else:
                bh = box['y_last'] - box['y_start'] + 1
                bw = box['x2']     - box['x1']     + 1
                if min_h <= bh <= max_h and min_w <= bw <= max_w and box_fill_ok(box):
                    key = (box['x1'], box['y_start'], box['x2'], box['y_last'])
                    if key not in seen:
                        seen.add(key)
                        completed.append(key)

        for j, (rx1, rx2) in enumerate(start_runs):
            if j not in start_run_used and rx2 - rx1 <= max_w:
                new_active.append({
                    'x1': rx1, 'x2': rx2,
                    'y_start': y, 'y_last': y,
                    'gap': 0
                })

        active = new_active

    for box in active:
        bh = box['y_last'] - box['y_start'] + 1
        bw = box['x2']     - box['x1']     + 1
        if min_h <= bh <= max_h and min_w <= bw <= max_w and box_fill_ok(box):
            key = (box['x1'], box['y_start'], box['x2'], box['y_last'])
            if key not in seen:
                seen.add(key)
                completed.append(key)

    def refine_boxes_x(boxes, min_col_fill: float = 0.10, expand_px: int = 350):
        """Expand each box's x1/x2 using column gray-fill within its y-range.

        Row scanning fails on text-heavy fields: character strokes (up to 16 px
        wide) create dark gaps that break horizontal runs, so the detected x1/x2
        is only a partial fragment of the true field.  Column fills rescue this:
        even through a thick stroke, the padding rows above and below the text
        keep the column's gray fraction well above min_col_fill=0.10, while the
        colored container background outside the box has 0 % gray fill.
        """
        refined = []
        for (bx1, by1, bx2, by2) in boxes:
            yr_s = max(0, by1 - y0)
            yr_e = min(h_content, by2 - y0 + 1)
            h = yr_e - yr_s
            if h <= 0:
                refined.append((bx1, by1, bx2, by2))
                continue

            def col_fill(x):
                if x < 0 or x >= W:
                    return 0.0
                return sum(mask[yr * W + x] for yr in range(yr_s, yr_e)) / h

            # Expand leftward from bx1
            new_x1 = bx1
            for x in range(bx1 - 1, max(-1, bx1 - expand_px), -1):
                if col_fill(x) >= min_col_fill:
                    new_x1 = x
                else:
                    break

            # Expand rightward from bx2
            new_x2 = bx2
            for x in range(bx2 + 1, min(W, bx2 + expand_px)):
                if col_fill(x) >= min_col_fill:
                    new_x2 = x
                else:
                    break

            new_w = new_x2 - new_x1 + 1
            if min_w <= new_w <= max_w:
                refined.append((new_x1, by1, new_x2, by2))
            else:
                # Expansion overshot (e.g. two adjacent boxes merged) — keep original
                refined.append((bx1, by1, bx2, by2))
        return refined

    completed = refine_boxes_x(completed)
    return sorted(completed, key=lambda b: (b[1], b[0]))


def modal_height_filter(boxes: list, tolerance: float = 0.30) -> tuple:
    """
    Post-filter detected value boxes to the modal (most common) height.

    In CODACAN all data-field value boxes are the same fixed pixel height (set
    by the LabVIEW developer).  This lets us:

      - Drop boxes that are too TALL  (>tolerance above modal) — these are group
        box frames or other container borders caught by the achromatic filter.
      - Snap boxes that are slightly SHORT to the canonical height — these are
        boxes whose top edge was missed due to a dark border or inside label,
        so y2 is extended to y1 + modal_h.
      - Drop boxes that are extremely short (<40 % of modal) — unreliable.

    Returns (filtered_boxes, modal_height) where modal_height is None when
    there are too few boxes to make a reliable estimate (< 3).
    """
    if len(boxes) < 3:
        return list(boxes), None

    from collections import Counter
    heights = [y2 - y1 for x1, y1, x2, y2 in boxes]
    modal_h  = Counter(heights).most_common(1)[0][0]

    hi = modal_h * (1 + tolerance)

    result = []
    for x1, y1, x2, y2 in boxes:
        h = y2 - y1
        if h > hi:
            continue        # too tall — group box frame or false positive
        if h < modal_h * 0.4:
            continue        # way too short — almost certainly wrong
        # Center-based snap: preserve the midpoint of the detected region and
        # grow equally up and down to the canonical height.  This is better than
        # extending only y2 (which drifts the box down when a label covers the
        # top of the value box, causing the detected region to start too low).
        cy = (y1 + y2) / 2
        new_y1 = round(cy - modal_h / 2)
        result.append((x1, new_y1, x2, new_y1 + modal_h))

    return result, modal_h


def scan_leds(img: Image, skip_top: int, skip_bottom: int,
              min_size: int = 8, max_size: int = 30) -> list:
    """
    Find LED indicator blobs — both active (bright green) and inactive (dark green).

    CODACAN radio indicator lights use two distinct green shades:
      Active (on):   bright green — G ≥ 120, G >> R and B
      Inactive (off): dark green  — G in [30, 120), still G > R and G > B

    Returns list of (cx, cy, radius_approx, color) tuples where color is 'on' or 'off'.
    """
    rgb  = img.convert('RGB')
    W, H = rgb.size
    pix  = rgb.load()

    def led_color(x, y):
        r, g, b = pix[x, y]
        # Active LED: bright green dominant
        if g >= 120 and g > r + 40 and g > b + 20:
            return 'on'
        # Inactive LED: dim/dark green dominant (CODACAN off-state colour ~RGB(49,82,28))
        if 30 <= g < 120 and g > r + 15 and g > b + 10:
            return 'off'
        return None

    visited = [[False] * W for _ in range(H)]
    blobs = []

    for y0 in range(skip_top, H - skip_bottom):
        for x0 in range(W):
            color = led_color(x0, y0)
            if color and not visited[y0][x0]:
                # BFS
                queue = [(x0, y0)]
                visited[y0][x0] = True
                region = [(x0, y0)]
                qi = 0
                while qi < len(queue):
                    cx, cy = queue[qi]; qi += 1
                    for nx, ny in ((cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)):
                        if 0 <= nx < W and skip_top <= ny < H - skip_bottom:
                            if not visited[ny][nx] and led_color(nx, ny) == color:
                                visited[ny][nx] = True
                                queue.append((nx, ny))
                                region.append((nx, ny))

                if len(region) < 10:
                    continue

                xs = [p[0] for p in region]
                ys = [p[1] for p in region]
                x1, x2 = min(xs), max(xs)
                y1, y2 = min(ys), max(ys)
                bw = x2 - x1 + 1
                bh = y2 - y1 + 1

                # Size and shape filters
                if not (min_size <= bw <= max_size and min_size <= bh <= max_size):
                    continue
                if max(bw, bh) / max(1, min(bw, bh)) > 2.0:
                    continue  # too elongated to be a circle
                if len(region) / (bw * bh) < 0.4:
                    continue  # not dense enough

                cx_center = (x1 + x2) // 2
                cy_center = (y1 + y2) // 2
                radius    = max(bw, bh) // 2
                blobs.append((cx_center, cy_center, radius, color))

    return blobs


def _tab_index_from_filename(path: Path) -> int | None:
    """
    Extract the numeric index from a filename like '2026-02-21 (10).png' → 10.
    Returns None if no parenthesized number is found.
    """
    m = re.search(r'\((\d+)\)', path.stem)
    return int(m.group(1)) if m else None


def find_tab_bar_y(img: Image) -> int:
    """
    Scan the image top-to-bottom to find the y-coordinate of the LabVIEW tab bar.

    The title bar and menu bar are near-white (≥240). The tab bar starts where the
    mean row brightness first drops below 230. Returns the midpoint of the tab bar
    region (used for tab click coordinates and `detect_tab_buttons`).
    """
    gray = img.convert('L')
    W, H = gray.size
    pix  = gray.load()

    margin = max(20, W // 20)
    step   = max(1, (W - 2 * margin) // 15)
    xs     = list(range(margin, W - margin, step))

    tab_start = None
    content_start = None

    for y in range(20, min(H, 300)):
        mean_v = sum(pix[x, y] for x in xs) / len(xs)
        if tab_start is None and mean_v < 230:
            tab_start = y
        if tab_start is not None and content_start is None and mean_v < 200:
            content_start = y
            break

    if tab_start is None:
        return int(H * 0.065)

    if content_start is None:
        content_start = tab_start + int(H * 0.04)

    return (tab_start + content_start) // 2


def find_content_start(img: Image) -> int:
    """
    Return the y-coordinate where the LabVIEW content area begins (below the
    tab bar, i.e. the first row that is NOT part of any tab button).

    Used as `skip_top` for the field/container scanners so that inactive tab
    buttons (which can appear as d2d2d2-coloured rectangles) are excluded.
    """
    gray = img.convert('L')
    W, H = gray.size
    pix  = gray.load()

    margin = max(20, W // 20)
    step   = max(1, (W - 2 * margin) // 15)
    xs     = list(range(margin, W - margin, step))

    tab_start     = None
    content_start = None

    for y in range(20, min(H, 400)):
        mean_v = sum(pix[x, y] for x in xs) / len(xs)
        if tab_start is None and mean_v < 230:
            tab_start = y
        if tab_start is not None and content_start is None and mean_v < 200:
            content_start = y
            break

    if content_start is None:
        content_start = (tab_start + int(H * 0.04)) if tab_start else int(H * 0.10)

    # Add a 10 px safety margin so the bottom edge of the tallest inactive tab
    # button is also excluded.
    return content_start + 10


def detect_tab_buttons(img: Image, tab_y: int | None = None) -> list:
    """
    Detect tab button x-centres in the tab bar.

    Scans a horizontal row at `tab_y` (auto-detected if None) for runs of
    pixels above a threshold. Returns list of x-centres, left to right.
    """
    if tab_y is None:
        tab_y = find_tab_bar_y(img)

    gray = img.convert('L')
    W, H = gray.size
    pix  = gray.load()

    y = min(tab_y, H - 1)
    row = [pix[x, y] for x in range(W)]

    # Tab buttons are all ≥170 brightness; gaps between them are darker.
    # Minimum tab-button width: ~3% of image width.
    THRESH    = 170
    MIN_WIDTH = max(20, W // 35)
    buttons   = []
    start     = None

    for x, v in enumerate(row):
        if v >= THRESH:
            if start is None:
                start = x
        else:
            if start is not None and x - start >= MIN_WIDTH:
                buttons.append((start + x) // 2)
            start = None
    if start is not None and W - start >= MIN_WIDTH:
        buttons.append((start + W) // 2)

    return buttons


def identify_tab_from_filename(path: Path, all_paths: list) -> str | None:
    """
    Map a screenshot file to a tab name using the numeric index in its filename.

    Filenames like '2026-02-21 (9).png' through '(17).png' are treated as a
    sequential series: the file with the smallest number maps to TAB_NAMES[0],
    the next to TAB_NAMES[1], etc.

    Falls back to pixel-based detection if no numeric index is found.
    """
    indices = [(p, _tab_index_from_filename(p)) for p in all_paths]
    valid   = [(p, i) for p, i in indices if i is not None]

    if not valid:
        return None   # caller will use pixel fallback

    # Sort by numeric index and map to tab names in order
    valid.sort(key=lambda x: x[1])
    rank = {p: pos for pos, (p, _) in enumerate(valid)}

    pos = rank.get(path)
    if pos is not None and pos < len(TAB_NAMES):
        return TAB_NAMES[pos]
    return None


def annotate_image(img: Image, boxes: list, leds: list, output_path: Path,
                   box_labels: list = None, led_labels: list = None):
    """
    Draw numbered red boxes and blue circles on the image, save to output_path.

    boxes:      list of (x1,y1,x2,y2) — drawn in red, numbered top-to-bottom
    leds:       list of (cx,cy,r,color) — drawn in blue circles
    box_labels: optional list of (name, src) parallel to boxes; src='ocr'|'auto'
    led_labels: optional list of (name, src) parallel to leds; src='ocr'|'auto'

    OCR'd labels are drawn in purple above each element so the user can
    visually verify that label recognition read the right text.
    auto_NNN labels are drawn in orange so unrecognised fields stand out.
    """
    annotated = img.copy().convert('RGB')
    draw = ImageDraw.Draw(annotated)

    PURPLE = (160,  40, 220)
    ORANGE = (255, 140,   0)
    RED    = (255,  40,  40)
    BLUE   = ( 40,  80, 255)

    def _draw_label(text: str, x: int, y: int, color: tuple):
        """Draw label with a thin white shadow for readability on any background."""
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, fill=(255, 255, 255))
        draw.text((x, y), text, fill=color)

    for i, (x1, y1, x2, y2) in enumerate(boxes, start=1):
        draw.rectangle([x1, y1, x2, y2], outline=RED, width=2)
        draw.text((x1 + 2, y1 + 1), str(i), fill=RED)
        if box_labels and i - 1 < len(box_labels):
            name, src = box_labels[i - 1]
            color = PURPLE if src == 'ocr' else ORANGE
            _draw_label(name, x1, max(0, y1 - 14), color)

    led_start = len(boxes) + 1
    for i, (cx, cy, r, color) in enumerate(leds, start=led_start):
        outline = BLUE if color == 'on' else ORANGE
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=outline, width=2)
        draw.text((cx + r + 2, cy - 6), str(i), fill=outline)
        if led_labels and i - led_start < len(led_labels):
            name, src = led_labels[i - led_start]
            lbl_color = PURPLE if src == 'ocr' else ORANGE
            _draw_label(name, cx - r, max(0, cy - r - 14), lbl_color)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    annotated.save(str(output_path))
    logger.info(f"Annotated screenshot saved: {output_path}")


def run_init_layout(args):
    """
    Process reference screenshots to build an initial ui_layout.json.

    For each PNG in the screenshots directory:
      - Identify which tab is shown
      - Detect value boxes (white rectangles) and LED indicators
      - Save annotated PNG for user review
      - Add entries to ui_layout.json with auto-generated names (auto_NNN)

    After running, user should open the annotated PNGs in
    cowork-results/screenshots/ui_discovery/ and rename auto_NNN fields in
    ui_layout.json to match the actual CODACAN field labels.
    """
    screenshots_dir = Path(args.screenshots_dir)
    output_path     = Path(args.output)
    annot_dir       = Path(args.results_dir) / "screenshots" / "ui_discovery"
    annot_dir.mkdir(parents=True, exist_ok=True)

    pngs = sorted(screenshots_dir.glob("*.png"))
    if not pngs:
        logger.error(f"No PNG files found in: {screenshots_dir}")
        sys.exit(1)
    logger.info(f"Found {len(pngs)} screenshots in {screenshots_dir}")

    layout = {
        "window_title": DEFAULT_WINDOW_TITLE,
        "reference_size": None,   # set from first screenshot
        "tabs": {}
    }

    # Tab identification: use filename numeric ordering as primary method.
    # Files named '2026-02-21 (9).png' through '(17).png' map to TAB_NAMES[0..8].
    tab_to_png = {}
    tab_bar_y  = None   # discovered from first image, reused for all

    for png in pngs:
        logger.info(f"Processing {png.name}...")
        img = Image.open(png)
        W, H = img.size

        if layout["reference_size"] is None:
            layout["reference_size"] = [W, H]
        elif [W, H] != layout["reference_size"]:
            logger.warning(f"  {png.name}: size {W}x{H} differs from reference "
                           f"{layout['reference_size']} — will need coordinate scaling")

        # Identify tab from filename order
        tab_name = identify_tab_from_filename(png, pngs)
        if tab_name is None:
            logger.warning(f"  Could not determine tab for {png.name} — skipping")
            continue
        if tab_name in tab_to_png:
            logger.warning(f"  Tab '{tab_name}' already mapped — skipping {png.name}")
            continue
        tab_to_png[tab_name] = png
        logger.info(f"  Tab: {tab_name}")

        # Find tab bar y on first image (consistent across all screenshots)
        if tab_bar_y is None:
            tab_bar_y = find_tab_bar_y(img)
            logger.info(f"  Tab bar detected at y={tab_bar_y}")

        # Scale content-area skip margins with image size.
        # Inactive tab buttons (measured ≈50 px tall at H=1372) sit in the
        # y ≈ 10–14 % zone.  Using tab_bar_y + 100 reliably clears them:
        # tab_bar_y ≈ 96 px → 96+100=196, above the measured button bottom of 187.
        # Also require at least 14 % of H as a size-independent lower bound.
        SKIP_TOP    = max(int(H * 0.14), (tab_bar_y or 0) + 100)
        SKIP_BOTTOM = int(H * 0.07)

        # Scale value-box size thresholds with image width
        # At 1300px: min_w=35, max_w=220, min_h=13, max_h=38
        # Scale linearly: ~W/1300 factor
        scale   = W / 1300
        min_w   = max(25,  int(35  * scale))
        max_w   = min(600, int(260 * scale))
        min_h   = max(10,  int(13  * scale))
        max_h   = min(120, int(38  * scale))
        led_min = max(8,   int(8   * scale))
        led_max = min(80,  int(30  * scale))
        logger.info(f"  Scale={scale:.2f}  box W={min_w}-{max_w}  H={min_h}-{max_h}  "
                    f"skip top={SKIP_TOP} bot={SKIP_BOTTOM}")

        # Detect value boxes.
        # Color bounds are tightened to exactly #d2d2d2 (avg 210 ± 3, spread ≤ 8).
        # Group box frame/border pixels sit at avg ≈ 197–205 and are excluded.
        # Group box fill backgrounds sit at avg ≈ 181 and are already excluded.
        # PNG screenshots are lossless so valid data-box pixels are exactly 210.
        # min_fill=0.25: permissive for text-heavy boxes while rejecting sparse
        # photo/gradient regions (car image in Overview, etc.).
        boxes = scan_value_boxes(img, skip_top=SKIP_TOP, skip_bottom=SKIP_BOTTOM,
                                 min_w=min_w, max_w=max_w, min_h=min_h, max_h=max_h,
                                 gap_tolerance=8, min_fill=0.25,
                                 gray_min=207, gray_max=213, achromatic_tol=8,
                                 hgap_tol=4)
        logger.info(f"  Detected {len(boxes)} value boxes (pre-height-filter)")

        # Apply modal-height filter: drop group-box frames (too tall) and snap
        # boxes detected slightly short up to the canonical data-field height.
        boxes, modal_h = modal_height_filter(boxes)
        modal_str = "n/a" if modal_h is None else f"{modal_h}px"
        logger.info(f"  After height filter: {len(boxes)} boxes  (modal_h={modal_str})")

        # Compute modal box width to auto-detect text/enum fields.
        # Numeric indicator boxes all share a similar narrow width; text enum
        # boxes (BattPowermode, HVAC string indicators) are 3–5× wider.
        # Any box wider than TEXT_WIDTH_RATIO × modal_w is tagged as 'text'.
        TEXT_WIDTH_RATIO = 1.8
        if boxes:
            from collections import Counter as _Counter
            box_widths = [x2 - x1 for x1, y1, x2, y2 in boxes]
            modal_w = _Counter(box_widths).most_common(1)[0][0]
            text_w_thresh = modal_w * TEXT_WIDTH_RATIO
        else:
            modal_w = 0
            text_w_thresh = 9999
        logger.info(f"  Modal box width={modal_w}px  text threshold={text_w_thresh:.0f}px")

        # Detect LED indicators
        leds = scan_leds(img, skip_top=SKIP_TOP, skip_bottom=SKIP_BOTTOM,
                         min_size=led_min, max_size=led_max)
        logger.info(f"  Detected {len(leds)} LED indicators")

        # Detect tab button x-centres using the tab bar y found above
        button_xs = detect_tab_buttons(img, tab_y=tab_bar_y)
        tab_clicks = {}
        for i, name in enumerate(TAB_NAMES):
            if i < len(button_xs):
                tab_clicks[name] = [button_xs[i], tab_bar_y]
            else:
                tab_clicks[name] = None

        # Build layout entry
        fields  = {}
        counter = getattr(run_init_layout, '_field_counter', 0)

        # Label recognition: OCR the region directly above each box/LED.
        # label_h = height of the search band above the element top edge.
        # led_ext_l/r = how far left/right to extend past the LED circle for
        # the label search (LEDs are small; their labels can be much wider).
        label_h   = max(20, int(30 * scale))
        led_ext_l = int(220 * scale)
        led_ext_r = int(100 * scale)

        # Deduplicate detected names within this tab.
        used_names: set = set()

        def assign_name(raw_label: 'str | None', fallback_n: int) -> tuple:
            """Return (name, label_source) using OCR label or auto_NNN fallback."""
            if raw_label:
                base = raw_label.strip()
                if base not in used_names:
                    used_names.add(base)
                    return base, 'ocr'
                suffix = 2
                while f"{base}_{suffix}" in used_names:
                    suffix += 1
                deduped = f"{base}_{suffix}"
                used_names.add(deduped)
                return deduped, 'ocr'
            auto = f"auto_{fallback_n:03d}"
            used_names.add(auto)
            return auto, 'auto'

        n_ocr, n_auto = 0, 0
        box_labels = []   # parallel to boxes — (name, src) for annotate_image
        led_labels = []   # parallel to leds  — (name, src) for annotate_image

        for box in boxes:
            x1, y1, x2, y2 = box
            counter += 1
            label = read_label_above(img, x1 - 10, x2 + 100, y1, label_h, SKIP_TOP)
            name, src = assign_name(label, counter)
            if src == 'ocr':
                n_ocr += 1
            else:
                n_auto += 1
            box_labels.append((name, src))
            # Wide boxes are text/enum indicators (e.g. BattPowermode, HVAC string fields).
            field_type = "text" if (x2 - x1) > text_w_thresh else "numeric"
            fields[name] = {
                "bbox": [x1, y1, x2, y2],
                "type": field_type,
                "label_source": src,
            }

        for cx, cy, r, color in leds:
            counter += 1
            lx1 = cx - led_ext_l
            lx2 = cx + led_ext_r
            label = read_label_above(img, lx1, lx2, cy - r - 2, label_h, SKIP_TOP)
            name, src = assign_name(label, counter)
            if src == 'ocr':
                n_ocr += 1
            else:
                n_auto += 1
            led_labels.append((name, src))
            fields[name] = {
                "bbox": [cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2],
                "type": "boolean",
                "label_source": src,
            }

        logger.info(f"  Label recognition: {n_ocr} OCR'd, {n_auto} auto_NNN")

        # Save annotated image — purple labels overlaid for visual verification
        annot_path = annot_dir / f"{tab_name.replace(' ', '_').replace('/', '_')}.png"
        annotate_image(img, boxes, leds, annot_path,
                       box_labels=box_labels, led_labels=led_labels)

        run_init_layout._field_counter = counter

        layout["tabs"][tab_name] = {
            "tab_click": tab_clicks.get(tab_name),
            "fields": fields
        }

    save_layout(layout, output_path)

    print()
    print("=" * 60)
    print("init-layout complete.")
    print()
    print(f"Annotated screenshots saved to:")
    print(f"  {annot_dir}")
    print()
    print(f"Layout saved to:")
    print(f"  {output_path}")
    print()
    print("Next steps:")
    print("  1. Open ui_layout.json and review the auto-detected field names.")
    print("     Fields labelled 'label_source: ocr' were named by OCR — verify")
    print("     they match the actual CODACAN labels and correct any mis-reads.")
    print("     Fields labelled 'label_source: auto' (auto_NNN) need manual naming.")
    print("  2. Change 'type' from 'numeric' to 'text' for string/enum fields")
    print("     (e.g. BattPowermode text indicators like Chargemode, BMSmode).")
    print("  3. Delete any entries that were false detections.")
    print("  4. Run 'snapshot --tabs BMS' with CODACAN open to verify.")


# ---------------------------------------------------------------------------
# calibrate: interactive live fine-tuning
# ---------------------------------------------------------------------------

def _require_pyautogui(sub):
    if not _HAVE_PYAUTOGUI:
        print(f"ERROR: pyautogui is required for '{sub}'. Run: pip install pyautogui",
              file=sys.stderr)
        sys.exit(1)


def find_codacan_window(title: str = DEFAULT_WINDOW_TITLE):
    """Find the CODACAN window by title. Exit with helpful message if not found."""
    matches = pyautogui.getWindowsWithTitle(title)
    if not matches:
        all_titles = sorted({w.title for w in pyautogui.getAllWindows() if w.title.strip()})
        logger.error(f"Window '{title}' not found. Open windows:")
        for t in all_titles:
            logger.error(f"  {t!r}")
        logger.error("Launch CODACAN.exe, or use --window-title to specify its exact title.")
        sys.exit(1)
    if len(matches) > 1:
        logger.warning(f"Multiple windows match '{title}' — using the first one.")
    return matches[0]


def activate_and_screenshot(win) -> Image:
    """Activate CODACAN window and capture it as a PIL Image.

    Uses Win32 AttachThreadInput + SetForegroundWindow for reliable foreground
    switching on Windows.  Plain pygetwindow .activate() frequently silently
    fails when another window holds the foreground lock.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd   = win._hWnd
        # Restore if minimised
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        # Attach to the current foreground thread so SetForegroundWindow succeeds
        fg_hwnd   = user32.GetForegroundWindow()
        fg_tid    = user32.GetWindowThreadProcessId(fg_hwnd, None)
        this_tid  = ctypes.windll.kernel32.GetCurrentThreadId()
        if fg_tid != this_tid:
            user32.AttachThreadInput(fg_tid, this_tid, True)
        user32.SetForegroundWindow(hwnd)
        if fg_tid != this_tid:
            user32.AttachThreadInput(fg_tid, this_tid, False)
    except Exception:
        win.activate()   # fallback for non-Windows
    time.sleep(0.4)      # allow window to fully render in foreground
    screenshot = pyautogui.screenshot(
        region=(win.left, win.top, win.width, win.height)
    )
    return screenshot


def poll_mouse_position(win, prompt: str) -> tuple:
    """
    Live mouse-position capture (Windows-only via msvcrt).

    Prints live (x, y) to console. Captures position on any keypress.
    Returns (x, y) relative to the CODACAN window's top-left corner.
    """
    try:
        import msvcrt
    except ImportError:
        # Non-Windows fallback: just read from input
        print(prompt)
        raw = input("Enter x y coordinates (space-separated): ").strip()
        x, y = map(int, raw.split())
        return (x, y)

    print(prompt)
    print("  (Move mouse to position, press any key to capture)")
    last_print = 0
    while True:
        ax, ay = pyautogui.position()
        rx = ax - win.left
        ry = ay - win.top
        now = time.time()
        if now - last_print > 0.15:
            print(f"\r  window-relative ({rx:4d}, {ry:4d})  abs ({ax}, {ay})   ",
                  end='', flush=True)
            last_print = now
        if msvcrt.kbhit():
            msvcrt.getch()  # consume keypress
            print(f"\n  Captured: ({rx}, {ry})")
            return (rx, ry)
        time.sleep(0.04)


def run_calibrate(args):
    """Interactive fine-tuning of layout coordinates with CODACAN live."""
    _require_pyautogui('calibrate')
    layout_path = Path(args.layout)
    layout = load_layout(layout_path)

    win = find_codacan_window(layout.get('window_title', DEFAULT_WINDOW_TITLE))
    print(f"Found window: '{win.title}' at ({win.left}, {win.top}), size {win.width}x{win.height}")

    # Save a calibration reference screenshot
    screenshot = activate_and_screenshot(win)
    ref_path = Path(args.results_dir) / "codacan_calibration_screenshot.png"
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot.save(str(ref_path))
    print(f"Reference screenshot saved: {ref_path}")

    changed = False

    for tab_name in TAB_NAMES:
        if tab_name not in layout.get('tabs', {}):
            continue

        tab_data = layout['tabs'][tab_name]

        # Find fields that still have auto-generated names or null bboxes
        pending = {k: v for k, v in tab_data.get('fields', {}).items()
                   if k.startswith('auto_') or v.get('bbox') is None}

        if not pending and tab_data.get('tab_click') is not None:
            print(f"\n[{tab_name}] All fields named and positioned — skipping.")
            continue

        print(f"\n{'='*60}")
        print(f"Tab: {tab_name}")

        # Calibrate tab click if missing
        if tab_data.get('tab_click') is None:
            print(f"Navigate CODACAN to the '{tab_name}' tab, then press any key.")
            input("  (press Enter when ready)...")
            tab_click = poll_mouse_position(win, f"Move mouse to the '{tab_name}' TAB BUTTON, press any key:")
            tab_data['tab_click'] = list(tab_click)
            changed = True

        if not pending:
            continue

        print(f"  Navigate CODACAN to the '{tab_name}' tab now.")
        input("  Press Enter when the tab is visible...")

        for field_key, field_def in list(pending.items()):
            print(f"\n  Field: {field_key!r}  (current bbox: {field_def.get('bbox')})")

            # Ask for new name
            new_name = input(f"  New field name (blank to keep '{field_key}'): ").strip()
            if new_name and new_name != field_key:
                tab_data['fields'][new_name] = tab_data['fields'].pop(field_key)
                field_key = new_name
                field_def = tab_data['fields'][field_key]
                changed = True

            # Recapture bbox?
            recapture = input("  Recapture bounding box? [y/N]: ").strip().lower()
            if recapture == 'y':
                tl = poll_mouse_position(win, "  Move to TOP-LEFT corner of value box, press any key:")
                br = poll_mouse_position(win, "  Move to BOTTOM-RIGHT corner, press any key:")
                field_def['bbox'] = [tl[0], tl[1], br[0], br[1]]
                changed = True

            # Field type
            current_type = field_def.get('type', 'numeric')
            new_type = input(f"  Field type [{current_type}] (n=numeric / t=text / b=boolean, blank to keep): ").strip().lower()
            if new_type in ('n', 'numeric'):
                field_def['type'] = 'numeric'; changed = True
            elif new_type in ('t', 'text'):
                field_def['type'] = 'text'; changed = True
            elif new_type in ('b', 'boolean'):
                field_def['type'] = 'boolean'; changed = True

        # Add new fields interactively
        while True:
            new_field = input(f"\n  Add another field in '{tab_name}'? (enter name, blank to move on): ").strip()
            if not new_field:
                break
            tl = poll_mouse_position(win, f"  Move to TOP-LEFT of '{new_field}' value box, press any key:")
            br = poll_mouse_position(win, f"  Move to BOTTOM-RIGHT, press any key:")
            ftype = input("  Type (n=numeric / t=text / b=boolean) [n]: ").strip().lower()
            ftype = {'t': 'text', 'b': 'boolean'}.get(ftype, 'numeric')
            tab_data['fields'][new_field] = {
                "bbox": [tl[0], tl[1], br[0], br[1]],
                "type": ftype
            }
            changed = True

        if changed:
            save_layout(layout, layout_path)

    if not changed:
        print("\nNo changes made.")
    else:
        save_layout(layout, layout_path)
        print("\nCalibration complete. Layout saved.")


# ---------------------------------------------------------------------------
# OCR / field extraction
# ---------------------------------------------------------------------------

def _require_ocr():
    if _OCR_ENGINE is None:
        print("ERROR: No OCR engine available. Install one of:", file=sys.stderr)
        print("  pip install pytesseract  (then install Tesseract binary)", file=sys.stderr)
        print("  pip install easyocr", file=sys.stderr)
        sys.exit(1)


def preprocess_crop(crop: Image, scale: int = 3) -> Image:
    """
    Upscale, grayscale, auto-invert dark backgrounds, binarize.
    Prepares a field crop for OCR.
    """
    w, h = crop.size
    img = crop.resize((w * scale, h * scale), Image.LANCZOS)
    img = img.convert('L')

    # If the majority of pixels are dark (LabVIEW dark-bg style), invert
    pixels = list(img.getdata())
    mean_val = sum(pixels) / max(1, len(pixels))
    if mean_val < 128:
        img = img.point(lambda p: 255 - p)

    # Binarize
    img = img.point(lambda p: 0 if p < 128 else 255)
    return img


def ocr_field(crop: Image, field_type: str) -> tuple:
    """
    Run OCR on a field crop.

    Returns (raw_str, parsed_value, ok, error_code).
    error_code is None on success, or 'ocr_empty' / 'ocr_parse_failed'.
    """
    global _EASYOCR_READER
    _require_ocr()

    img = preprocess_crop(crop)

    if _OCR_ENGINE == 'tesseract':
        config = '--psm 7'
        if field_type == 'numeric':
            config += ' -c tessedit_char_whitelist=0123456789.-+ '
        raw = pytesseract.image_to_string(img, config=config).strip()
    else:
        if _EASYOCR_READER is None:
            logger.info("Loading easyocr model (first use may be slow)...")
            _EASYOCR_READER = _easyocr_mod.Reader(['en'], gpu=False)
        results = _EASYOCR_READER.readtext(img, detail=0)
        raw = ' '.join(results).strip()

    if not raw:
        return (raw, None, False, 'ocr_empty')

    if field_type == 'numeric':
        try:
            value = float(raw.replace(' ', '').replace(',', '.'))
            return (raw, value, True, None)
        except ValueError:
            # Field typed as numeric but OCR returned non-numeric text.
            # This usually means the field is actually a text/enum indicator
            # (e.g. BattPowermode: "No Prox", "HV On Drive") but was not
            # re-typed in ui_layout.json.  Return the raw string as-is with
            # a warning flag rather than silently dropping the value.
            return (raw, raw, True, 'type_mismatch')
    else:
        # text/enum — return raw string as-is
        return (raw, raw, True, None)


def read_label_above(img: Image, x1: int, x2: int, y_top: int,
                     label_h: int, skip_top: int) -> 'str | None':
    """
    OCR the region directly above a value box or LED to read its field label.

    Looks in the band (x1, y_top-label_h) → (x2, y_top-1).  The label text
    is printed on the group-container background (light or colored) in dark
    ink — same preprocessing pipeline as ocr_field but at 4x upscale (vs 3x
    for field values) with psm 6 and no character whitelist.  4x resolves
    Tesseract 'm'→'rn' misreads and improves right-edge character accuracy.

    Returns the cleaned label string, or None when:
      - No OCR engine is available
      - The crop is too small to be meaningful
      - OCR returned empty text, text shorter than 2 chars, or text that
        contains no alphabetic characters (likely a mis-read field value
        from the element above).
    """
    if _OCR_ENGINE is None:
        return None

    ly1 = max(skip_top, y_top - label_h)
    ly2 = y_top - 1      # leave 1 px gap for the group-box border

    if ly2 - ly1 < 5:
        return None

    crop = img.crop((max(0, x1), ly1, min(img.width, x2), ly2))
    cw, ch = crop.size
    if cw < 5 or ch < 3:
        return None

    # Same preprocessing as preprocess_crop but at 4x scale.
    # 4x (vs 3x) resolves Tesseract 'm' → 'rn' misreads on the CODACAN font
    # and generally improves accuracy on fine-detail characters like 'v'/'e'.
    proc = crop.resize((cw * 4, ch * 4), Image.LANCZOS)
    proc = proc.convert('L')
    pixels = list(proc.getdata())
    mean_val = sum(pixels) / max(1, len(pixels))
    if mean_val < 128:            # dark background (e.g. dark-purple group) → invert
        proc = proc.point(lambda p: 255 - p)
    proc = proc.point(lambda p: 0 if p < 128 else 255)

    global _EASYOCR_READER
    if _OCR_ENGINE == 'tesseract':
        # psm 6 (uniform block of text) handles right-edge characters better
        # than psm 7 (single line) for both narrow box labels and wide LED labels.
        raw = pytesseract.image_to_string(proc, config='--psm 6').strip()
    else:
        if _EASYOCR_READER is None:
            logger.info("Loading easyocr model (first use may be slow)...")
            _EASYOCR_READER = _easyocr_mod.Reader(['en'], gpu=False)
        results = _EASYOCR_READER.readtext(proc, detail=0)
        raw = ' '.join(results).strip()

    if not raw:
        return None

    label = ' '.join(raw.split())   # normalize whitespace
    label = label.rstrip('.:;,')    # strip trailing punctuation from group-box borders

    # Reject results that are too short or contain no letters — these are
    # almost certainly mis-reads of a numeric field value from the box above.
    if len(label) < 2 or not any(c.isalpha() for c in label):
        return None

    return label


def detect_boolean_led(crop: Image, threshold: float = 0.25) -> bool:
    """
    Detect whether a boolean LED indicator is lit (green) or off.

    Returns True if the LED appears green/lit.
    """
    rgb    = crop.convert('RGB')
    pixels = list(rgb.getdata())
    if not pixels:
        return False
    green_count = sum(
        1 for r, g, b in pixels
        if g >= 110 and g > r + 35 and g > b + 20
    )
    return (green_count / len(pixels)) >= threshold


def _scale_bbox(bbox: list, ref_size: list, live_size: tuple) -> list:
    """Scale bbox coordinates if the live window size differs from the reference."""
    if ref_size is None or list(live_size) == ref_size:
        return bbox
    sx = live_size[0] / ref_size[0]
    sy = live_size[1] / ref_size[1]
    x1, y1, x2, y2 = bbox
    return [int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)]


def extract_field_value(screenshot: Image, field_def: dict,
                        ref_size: list = None) -> dict:
    """
    Extract a single field value from a screenshot.

    Handles coordinate scaling if the live window is a different size from the
    reference screenshots used during init-layout.
    """
    bbox = field_def.get('bbox')
    if bbox is None:
        return {"value": None, "raw": None, "type": field_def.get('type'), "ok": False, "error": "not_calibrated"}

    live_size = screenshot.size
    scaled_bbox = _scale_bbox(bbox, ref_size, live_size)
    x1, y1, x2, y2 = scaled_bbox

    # Guard against out-of-bounds.
    # Expand 1 px left to avoid clipping left-edge characters (e.g. "0" that
    # sits right at the box border after coordinate rounding).
    W, H = live_size
    x1, y1 = max(0, x1 - 1), max(0, y1)
    x2, y2 = min(W - 1, x2), min(H - 1, y2)
    if x2 <= x1 or y2 <= y1:
        return {"value": None, "raw": None, "type": field_def.get('type'), "ok": False, "error": "bbox_out_of_bounds"}

    crop = screenshot.crop((x1, y1, x2, y2))
    field_type = field_def.get('type', 'numeric')

    if field_type == 'boolean':
        value = detect_boolean_led(crop)
        return {"value": value, "raw": None, "type": "boolean", "ok": True}

    raw, value, ok, error = ocr_field(crop, field_type)
    result = {"value": value, "raw": raw, "type": field_type, "ok": ok}
    if error:
        result["error"] = error
    return result


# ---------------------------------------------------------------------------
# Tab navigation and capture
# ---------------------------------------------------------------------------

def navigate_to_tab(tab_name: str, layout: dict, win):
    """Click the tab button and wait briefly for the UI to render."""
    tab_data = layout.get('tabs', {}).get(tab_name, {})
    click_coords = tab_data.get('tab_click')
    if click_coords is None:
        logger.warning(f"No tab_click coordinates for '{tab_name}' — skipping navigation")
        return

    ref_size  = layout.get('reference_size')
    live_size = (win.width, win.height)
    if ref_size and list(live_size) != ref_size:
        sx = live_size[0] / ref_size[0]
        sy = live_size[1] / ref_size[1]
        click_coords = [int(click_coords[0] * sx), int(click_coords[1] * sy)]

    abs_x = win.left + click_coords[0]
    abs_y = win.top  + click_coords[1]
    # First click activates the window; second click selects the tab.
    pyautogui.click(abs_x, abs_y)
    time.sleep(0.15)
    pyautogui.click(abs_x, abs_y)
    time.sleep(0.35)  # wait for LabVIEW tab switch to render


def capture_tab_fields(screenshot: Image, tab_data: dict, ref_size: list) -> dict:
    """
    Extract all field values from a single tab screenshot.

    Skips fields with no bbox (not_calibrated). Returns dict of field_name -> result_dict.
    """
    results = {}
    for field_name, field_def in tab_data.get('fields', {}).items():
        results[field_name] = extract_field_value(screenshot, field_def, ref_size)
    return results


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

def run_snapshot(args):
    """One-shot capture of all calibrated fields, write JSON report."""
    _require_pyautogui('snapshot')

    layout_path = Path(args.layout)
    layout      = load_layout(layout_path)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ref_size   = layout.get('reference_size')
    win_title  = layout.get('window_title', DEFAULT_WINDOW_TITLE)
    win        = find_codacan_window(win_title)
    dwell      = getattr(args, 'dwell', 1.0)

    tabs_filter = [t.strip() for t in args.tabs.split(',')] if getattr(args, 'tabs', None) else list(layout.get('tabs', {}).keys())

    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "snapshot",
        "state": None,
        "tabs": {}
    }

    for tab_name in tabs_filter:
        if tab_name not in layout.get('tabs', {}):
            logger.warning(f"Tab '{tab_name}' not in layout — skipping")
            continue
        logger.info(f"Capturing tab: {tab_name}")
        navigate_to_tab(tab_name, layout, win)
        time.sleep(max(0, dwell - 0.35))  # extra dwell beyond tab-switch pause
        screenshot = activate_and_screenshot(win)
        tab_data   = layout['tabs'][tab_name]
        results['tabs'][tab_name] = capture_tab_fields(screenshot, tab_data, ref_size)

    output_path.write_text(json.dumps(results, indent=2), encoding='utf-8')
    logger.info(f"Snapshot written: {output_path}")

    # Summary
    total = sum(len(t) for t in results['tabs'].values())
    ok    = sum(v['ok'] for tab in results['tabs'].values() for v in tab.values())
    logger.info(f"  {ok}/{total} fields extracted successfully")


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------

def read_state_file(path: Path) -> dict | None:
    """Read cowork_state.json, returning None on any error (missing/mid-write race)."""
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.debug(f"State file read error (likely mid-write race): {e}")
        return None


def _step_output_path(results_dir: Path, state: dict) -> Path:
    """Build per-step output file path."""
    target_id = state.get('target_id', 'unknown').replace('0x', '').replace('0X', '')
    step      = state.get('step', 0)
    return results_dir / f"sweep_{target_id}_step{step:04d}.json"


def merge_sweep_results(results_dir: Path, state: dict):
    """
    Aggregate per-step JSON files for a completed sweep into sweep_results.json.

    Appends to the existing sweep_results.json if present (accumulates across sweeps).
    """
    target_id = state.get('target_id', 'unknown')
    byte_start = state.get('sweep_byte_start', state.get('sweep_byte_index', '?'))
    byte_count = state.get('sweep_byte_count', 1)
    byte_key   = f"byte_{byte_start}" if byte_count == 1 else f"bytes_{byte_start}_{byte_start + byte_count - 1}"

    # Collect step files for this sweep
    prefix = f"sweep_{target_id.replace('0x','').replace('0X','')}_step"
    step_files = sorted(results_dir.glob(f"{prefix}*.json"))

    observations = []
    for sf in step_files:
        try:
            data = json.loads(sf.read_text(encoding='utf-8'))
            obs_state = data.get('state', {})
            obs = {
                "step":          obs_state.get('step'),
                "input_value":   obs_state.get('current_value'),
                "input_hex":     obs_state.get('current_value_hex'),
                "frame_data_hex": obs_state.get('frame_data_hex'),
                "fields":        data.get('tabs', {})
            }
            observations.append(obs)
        except Exception as e:
            logger.warning(f"Could not parse step file {sf.name}: {e}")

    # Load or create sweep_results.json
    sweep_path = results_dir / "sweep_results.json"
    if sweep_path.exists():
        try:
            sweep = json.loads(sweep_path.read_text(encoding='utf-8'))
        except Exception:
            sweep = {}
    else:
        sweep = {}

    sweep.setdefault(target_id, {})[byte_key] = {
        "sweep_date":   datetime.now(timezone.utc).date().isoformat(),
        "total_steps":  state.get('total_steps'),
        "dwell_sec":    state.get('dwell_sec'),
        "observations": observations,
        "derived":      None   # filled in manually after analysis
    }

    sweep_path.write_text(json.dumps(sweep, indent=2), encoding='utf-8')
    logger.info(f"Merged {len(observations)} steps into {sweep_path}")


def run_watch(args):
    """Continuous capture synchronized with cowork_state.json."""
    _require_pyautogui('watch')

    layout_path = Path(args.layout)
    layout      = load_layout(layout_path)
    state_file  = Path(args.state_file)
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    ref_size    = layout.get('reference_size')
    win_title   = layout.get('window_title', DEFAULT_WINDOW_TITLE)
    poll_interval = getattr(args, 'poll', 0.5)

    tabs_filter = [t.strip() for t in args.tabs.split(',')] if getattr(args, 'tabs', None) else None

    win = find_codacan_window(win_title)
    logger.info(f"Watching state file: {state_file}")
    logger.info(f"Results dir: {results_dir}")
    if tabs_filter:
        logger.info(f"Monitoring tabs: {tabs_filter}")
    logger.info("Ctrl+C to stop.")

    last_step   = None
    last_status = None

    try:
        while True:
            state = read_state_file(state_file)

            if state is None:
                time.sleep(poll_interval)
                continue

            status       = state.get('status')
            current_step = state.get('step')
            mode         = state.get('mode', '')

            if mode != 'sweep-byte':
                logger.debug(f"Mode is '{mode}' (not sweep-byte) — waiting...")
                last_status = status
                time.sleep(poll_interval)
                continue

            # Capture on each new step while running
            if status == 'running' and current_step != last_step:
                dwell = state.get('dwell_sec', 3.0)
                val   = state.get('current_value_hex', state.get('current_value', '?'))
                total = state.get('total_steps', '?')
                logger.info(f"Step {current_step}/{total} — value={val} — "
                             f"waiting {dwell/2:.1f}s for CODACAN update...")
                time.sleep(dwell / 2)

                # Capture target tabs
                target_tabs = tabs_filter or list(layout.get('tabs', {}).keys())
                tab_results = {}
                for tab_name in target_tabs:
                    if tab_name not in layout.get('tabs', {}):
                        continue
                    navigate_to_tab(tab_name, layout, win)
                    screenshot = activate_and_screenshot(win)
                    tab_results[tab_name] = capture_tab_fields(
                        screenshot, layout['tabs'][tab_name], ref_size
                    )

                # Write per-step JSON immediately
                step_data = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "mode":      "watch",
                    "state":     state,
                    "tabs":      tab_results
                }
                out_path = _step_output_path(results_dir, state)
                out_path.write_text(json.dumps(step_data, indent=2), encoding='utf-8')
                logger.info(f"Written: {out_path.name}")

                last_step = current_step

            # Detect sweep completion
            if status == 'done' and last_status == 'running':
                logger.info("Sweep complete — merging step files...")
                merge_sweep_results(results_dir, state)

            last_status = status
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        logger.info("Watch stopped by user.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        description="CODACAN screenshot capture and OCR tool.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # --- init-layout ---
    p_init = sub.add_parser(
        'init-layout',
        help="Build ui_layout.json from reference screenshots (offline, no hardware needed)"
    )
    p_init.add_argument(
        '--screenshots-dir', default=str(DEFAULT_SCREENSHOTS_DIR),
        help=f"Directory containing reference PNG screenshots (default: {DEFAULT_SCREENSHOTS_DIR})"
    )
    p_init.add_argument(
        '--output', default=str(DEFAULT_LAYOUT_FILE),
        help=f"Output path for ui_layout.json (default: {DEFAULT_LAYOUT_FILE})"
    )
    p_init.add_argument(
        '--results-dir', default=str(DEFAULT_RESULTS_DIR),
        help=f"Results directory for annotated PNGs (default: {DEFAULT_RESULTS_DIR})"
    )

    # --- calibrate ---
    p_cal = sub.add_parser(
        'calibrate',
        help="Interactive live fine-tuning of coordinates with CODACAN open"
    )
    p_cal.add_argument(
        '--layout', default=str(DEFAULT_LAYOUT_FILE),
        help=f"Path to ui_layout.json (default: {DEFAULT_LAYOUT_FILE})"
    )
    p_cal.add_argument(
        '--results-dir', default=str(DEFAULT_RESULTS_DIR),
        help="Directory for calibration reference screenshot"
    )
    p_cal.add_argument(
        '--window-title', default=DEFAULT_WINDOW_TITLE,
        help=f"CODACAN window title (default: {DEFAULT_WINDOW_TITLE})"
    )

    # --- snapshot ---
    p_snap = sub.add_parser(
        'snapshot',
        help="One-shot capture of all calibrated fields, write JSON report"
    )
    p_snap.add_argument(
        '--layout', default=str(DEFAULT_LAYOUT_FILE),
        help=f"Path to ui_layout.json (default: {DEFAULT_LAYOUT_FILE})"
    )
    p_snap.add_argument(
        '--tabs', default=None,
        help="Comma-separated tab names to capture (default: all tabs)"
    )
    p_snap.add_argument(
        '--output', default=str(DEFAULT_RESULTS_DIR / "snapshot.json"),
        help="Output JSON path"
    )
    p_snap.add_argument(
        '--dwell', type=float, default=1.0,
        help="Seconds to wait after switching to each tab (default: 1.0)"
    )
    p_snap.add_argument(
        '--window-title', default=DEFAULT_WINDOW_TITLE,
        help=f"CODACAN window title (default: {DEFAULT_WINDOW_TITLE})"
    )

    # --- watch ---
    p_watch = sub.add_parser(
        'watch',
        help="Continuous capture synchronized with cowork_state.json during sweep-byte experiments"
    )
    p_watch.add_argument(
        '--layout', default=str(DEFAULT_LAYOUT_FILE),
        help=f"Path to ui_layout.json (default: {DEFAULT_LAYOUT_FILE})"
    )
    p_watch.add_argument(
        '--state-file', default=str(DEFAULT_STATE_FILE),
        help=f"Path to cowork_state.json (default: {DEFAULT_STATE_FILE})"
    )
    p_watch.add_argument(
        '--tabs', default=None,
        help="Comma-separated tab names to capture (default: all tabs)"
    )
    p_watch.add_argument(
        '--results-dir', default=str(DEFAULT_RESULTS_DIR),
        help=f"Directory for per-step JSON output (default: {DEFAULT_RESULTS_DIR})"
    )
    p_watch.add_argument(
        '--poll', type=float, default=0.5,
        help="State file poll interval in seconds (default: 0.5)"
    )
    p_watch.add_argument(
        '--window-title', default=DEFAULT_WINDOW_TITLE,
        help=f"CODACAN window title (default: {DEFAULT_WINDOW_TITLE})"
    )

    return parser


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    parser = build_parser()
    args   = parser.parse_args()

    if args.command == 'init-layout':
        run_init_layout(args)
    elif args.command == 'calibrate':
        run_calibrate(args)
    elif args.command == 'snapshot':
        run_snapshot(args)
    elif args.command == 'watch':
        run_watch(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
