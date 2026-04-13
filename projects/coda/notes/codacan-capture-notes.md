# CODACAN Capture Tool -- Notes

*Consolidated from: codacan-capture-dev-notes.md, codacan-python-capture-plan.md,
cowork-codacan-protocol.md (Phase 1 section). Last updated: 2026-03-03.*

---

## Background

`tools/codacan_capture.py` provides automated CODACAN display capture. It replaces an
earlier plan to use Claude Cowork (Anthropic's computer-use agent) as the observer --
Cowork operates only in web browsers and cannot interact with local desktop applications
like CODACAN.exe. The CAN replay side (`tools/cowork_replay.py`) is unchanged.

The tool exposes four sub-commands:

| Sub-command | Purpose | When to use |
|-------------|---------|-------------|
| `init-layout` | **Offline setup**: auto-detects value boxes and LED indicators from reference screenshots; writes `ui_layout.json` and annotated PNGs | Once, before experiments; no hardware or CODACAN needed |
| `calibrate` | **Live fine-tuning**: interactive mouse-position capture to correct any boxes that init-layout got wrong | Optional; only needed if specific fields are mis-detected |
| `snapshot` | **One-shot capture**: clicks each tab, OCRs all calibrated fields, writes JSON | Use after `baseline`, `drop-id`, `solo-id` replays |
| `watch` | **Continuous capture**: polls `cowork_state.json`, auto-captures at each sweep step, merges on completion | Use alongside `sweep-byte` replays |

**Python dependency:** `py -3.11-32` (default `py` = 3.9 on this machine; fails on `dataclass(slots=True)`)

**Key paths:**

| What | Path |
|------|------|
| Reference screenshots | `projects/coda/logs/codacan-screenshots/` (one PNG per tab) |
| UI layout JSON | `projects/coda/CODACAN/ui_layout.json` |
| Annotated discovery PNGs | `projects/coda/notes/artifacts/cowork-results/screenshots/ui_discovery/` |
| Sweep results output | `projects/coda/notes/artifacts/cowork-results/sweep/` |

---

## Phase 1 -- UI Discovery

**Objective:** Catalog every field label in CODACAN's 9 tabs and write `ui_layout.json`.

### Steps

1. Run `init-layout` offline (no hardware or CODACAN needed):
   ```
   py -3.11-32 tools/codacan_capture.py init-layout
   ```
   This processes reference screenshots in `projects/coda/logs/codacan-screenshots/` and writes:
   - `projects/coda/CODACAN/ui_layout.json` -- detected field boxes, initially named `auto_NNN`
   - `cowork-results/screenshots/ui_discovery/<tab>.png` -- annotated PNGs with numbered boxes

2. Open each annotated PNG alongside `ui_layout.json`. Rename `auto_NNN` fields to their
   actual CODACAN labels. Update `"type"` from `"numeric"` to `"text"` for enum string fields
   (BattPowermode, HVACHVDisableStatus, etc.).

3. Optionally run `calibrate` with CODACAN live to correct any mis-positioned boxes:
   ```
   py -3.11-32 tools/codacan_capture.py calibrate
   ```

4. Verify with a live snapshot:
   ```
   py -3.11-32 tools/codacan_capture.py snapshot --tabs BMS --output verify_bms.json
   ```

**Status:** Phase 1 complete. `ui_layout.json` is populated and labeled.

---

## `init-layout` -- Algorithm and Tuning

### Value Box Detection

LabVIEW numeric and string indicators have a pure achromatic gray background (`#d2d2d2`,
RGB 210,210,210) set against saturated colored container panels (green, pink/purple, yellow,
gray-green). The detector masks pixels where `207 <= avg(R,G,B) <= 213` AND
`max(R,G,B) - min(R,G,B) <= 8`, then finds horizontal runs of matching pixels per scanline,
merges vertically adjacent runs into boxes, and filters by size.

### Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `gray_min` | 207 | Excludes group-box frame pixels (avg ~197-205) |
| `gray_max` | 213 | Excludes brighter UI chrome |
| `achromatic_tol` | 8 | Rejects all colored backgrounds; #d2d2d2 spread = 0 |
| `gap_tolerance` | 8 | Bridges up to 8 consecutive non-gray rows (text crossing box vertically) |
| `min_fill` | 0.25 | At least 25% of bounding box must be gray -- rejects sparse car diagram in Overview |
| `hgap_tol` | 4 | Horizontal: bridges minor inter-stroke gaps in row scans |
| `min_w` (unscaled) | 35 | Smallest legitimate field at reference width |
| `max_w` (unscaled) | 260 | Accommodates wide text fields (BattPowermode ~232 px) |
| `SKIP_TOP` | `max(H x 0.14, tab_bar_y + 100)` | Excludes tab bar from box detection |
| Upscale factor | 4x | Fixes Tesseract 'm' -> 'rn' misread |
| Tesseract PSM | 6 | Best overall; PSM 7 dropped right-edge characters on label reads |
| Label height crop | `int(30 x scale)` ~= 44 px | Tall enough for uppercase; was 22 -> raised after top-clip observed |
| LED left extension | `int(220 x scale)` ~= 324 px | Captures labels left of LED; was 150 -> raised for IPK LEDs |

### Challenge Log

**Tab bar false positives:** Tab button labels matched the #d2d2d2 criteria. Fixed by raising
`SKIP_TOP` to `max(int(H x 0.14), tab_bar_y + 100)` where `tab_bar_y` is detected by scanning
for the first row with a high density of matching pixels.

**Car diagram false positive (Overview tab):** Semi-transparent car illustration had occasional
achromatic pixels that formed sparse irregular regions. Fixed with `min_fill = 0.25`.

**Missing Cell V/T boxes:** Initially undetected because `gray_min` was too low -- group-box
frame pixels (avg ~200) flooded the mask and prevented inner value boxes from forming clean
runs. Tightening to `gray_min = 207` excluded the frame pixels.

**BattPowermode text fields (most complex):** Four enum string fields (Chargemode,
KeepWakeNetworkBMS, BMSmode, HVPowermode) display strings like "No Prox" or "HV On Drive".
Character strokes (dark pixels) break horizontal runs, leaving only the empty area to the
right of the text as the detected box -- causing mis-positioned, too-narrow boxes.

**Fix -- `refine_boxes_x()`:** For each detected box with a correct y-range but wrong x-range,
walk outward column-by-column. Compute column fill = (# gray pixels in column within y-range)
/ box height. Include any column with fill >= 0.10; stop at the first column below threshold.
Through character strokes, the column still has ~30-50% gray pixels from padding rows -> included.
In the colored container background outside the box -> 0% gray -> stops. After refinement, all
four BattPowermode boxes read x = 1096-1439 (width 343 px). `max_w` was raised from 220 to 260
(unscaled) to accommodate them. The same fix resolved the HVAC "All HV Components not disable"
field which had the same failure mode.

**3x upscale 'm' -> 'rn' misread:** Tesseract at 3x misread 'm' as 'rn' on the CODACAN font
("Primary ODO (km)" -> "Primary ODO (krn)", "Interior Illum" -> "Interior Ilurn"). Fixed by
raising to 4x upscale.

**"Active" label truncation:** "High Beam Active" was consistently read as "High Beam Acti"
under PSM 7. Switching to PSM 6 (block mode) fixed right-edge character handling.

**Label crop too narrow (`x2 + 10`):** "Primary ODO (km)" was read as "Primary O" -- the
label extends past the box's right edge. Fixed by changing label crop right margin to `x2 + 100`.

**LED label clipped (`led_ext_l = 150 x scale`):** IPK LED labels run ~240 px left of LED
centre; were being clipped. Fixed by raising to `led_ext_l = 220 x scale`.

### Field Type Auto-Detection

All detected value boxes initially receive `"type": "numeric"`. Text/enum boxes are 3-5x
wider than numeric boxes. After detecting all boxes, `init-layout` computes the modal box
width per tab; any box wider than `1.8 x modal_w` is auto-assigned `"type": "text"`.

This catches all BattPowermode and HVAC string fields without manual intervention.

**Runtime fallback:** If a `"numeric"` field's OCR returns non-numeric text, `ocr_field()`
returns the raw string with `ok=True, error="type_mismatch"` rather than discarding the
value. The flag signals that `ui_layout.json` should be updated, but capture still succeeds.

### Visual Verification Overlay

`annotate_image()` draws OCR'd names in **purple** directly above each detected element.
Fields that fell back to `auto_NNN` are drawn in **orange** so unrecognised fields stand out.
A thin white shadow makes labels readable over any background. Open the annotated PNGs in
`cowork-results/screenshots/ui_discovery/` to spot mis-reads without opening the JSON.

---

## Detection Results

| Tab | Value Boxes | LEDs |
|-----|------------|------|
| BMS | 24 | 8 |
| BMS 2 | 1 (BMS Fault Severity) | 0 (all inactive) |
| DCDC | 8 | 4 |
| Charging | 25 | 12 |
| CH M/S | 28 | 4 |
| HVAC | 27 | 4 |
| Driveline | 16 | 8 |
| IPK | 4 | 3 |
| Overview | 3 | 15 |

All boxes on all tabs except BMS 2 are correctly positioned and sized.
Label recognition assigns OCR'd names to all or nearly all fields on every tab.

---

## Known Limitations

- **BMS 2 version grid cells:** Four cells per row, each ~35 px wide -- below `min_w = 51`.
  Not auto-detected. Add them manually in `ui_layout.json` during the labeling step.

- **BMS 2 fault LEDs:** All fault indicator LEDs on BMS 2 are dark/inactive in the reference
  screenshot (no faults present at capture time). The LED detector finds zero. Add manually
  if fault-state capture is needed.

- **Type corrections:** Check that all text/enum fields have `"type": "text"` in `ui_layout.json`.
  The modal-width heuristic catches most, but borderline-width fields may need manual correction.

- **Re-run after screenshot changes:** If the reference screenshots in
  `projects/coda/logs/codacan-screenshots/` are updated, re-run `init-layout` to regenerate
  the layout and verify the purple label overlay.
