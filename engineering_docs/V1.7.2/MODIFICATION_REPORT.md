# Label Auto Inspection Tool V1.7.2 - Modification Report

## Scope
This release modifies only the Artwork inspection path for the GRG-4297u Inner Box Label. Existing OCR, barcode, HID scanner, camera, Smart Lock and work-order rules remain structurally unchanged.

## Field issue reproduced
V1.7.1 used full-frame multi-scale template matching with adaptive thresholding and presence-only acceptance. The field symptom was that fixed text locked quickly while COMTREND / Recycling / CE / WEEE remained SCANNING.

The V1.7.1 detector was also verified against the repository sample path and showed that the existing artwork matching approach was not sufficiently robust for real camera-like imagery. The supplied runtime execution/debug logs contained profile/camera/autofocus events but did not contain per-artwork score/position diagnostics.

## Root causes addressed
1. Golden symbol crops retained surrounding white margin, making correlation sensitive to camera background and exposure.
2. Adaptive thresholding was unstable for black artwork on a white label under uneven lighting.
3. V1.7.1 accepted only category presence and did not implement the requested relative-position check.
4. The detector did not normalize the complete label before comparing relative positions.
5. Runtime logs did not expose per-symbol shape score, expected/actual normalized position, position error, label-alignment status, ignored scale, or execution time.
6. Legacy artwork tests focused on synthetic template pasting and did not include the supplied operator COMTREND camera screenshot.

## V1.7.2 changes
- Artwork acceptance = Shape PASS + Relative Position PASS.
- Printed size remains ignored.
- Multi-scale matching is retained only as recognition tolerance for camera distance.
- Golden template white margins are trimmed automatically.
- Artwork preprocessing changed to Gaussian + Otsu binary segmentation.
- Complete label is detected/perspective-normalized before relative-position evaluation.
- Expected symbol positions are auto-calibrated from the supplied Golden Label Example (`golden_layout.png`) extracted from the source specification.
- Per-symbol normalized expected/actual center and tolerance are evaluated.
- Inner Box label aspect calibration set to 2.05:1 from the supplied Golden Label Example.
- COMTREND shape threshold adjusted to 0.48 after source-artwork regression; its position gate remains mandatory.
- Detailed artwork diagnostics are written into runtime debug/test logs through the existing Zone OCR logging path.
- Added operator camera screenshot regression fixture for COMTREND shape detection.

## Acceptance semantics
PASS requires:
1. Complete label alignment is available.
2. Shape score >= configured shape threshold.
3. Artwork center is within the configured tolerance of the position learned from the Golden Label Example.

Not judged:
- Printed artwork size.
- Camera pixel size.
- Best matching scale.

## Files materially changed
- `label_tool/core/artwork_presence.py`
- `label_tool/core/production_zone_ocr.py`
- `label_tool/app.py`
- `label_tool/profiles/grg4297u_tsl_p1_inner_box.json`
- `label_tool/profiles/grg4297u_tsl_p1.json`
- `label_tool/golden_artwork/grg4297u_inner_box/golden_layout.png`
- `label_tool/__init__.py`
- `.github/workflows/build.yml`
- `README.md`
- artwork/profile tests plus new `tests/test_v172_artwork_shape_position.py`
- `sample/operator_comtrend_camera_crop.png`

## Smart Lock NG behavior
V1.7.2 also prevents a valid wrong artwork from remaining in SCANNING forever:
- Complete label not aligned/visible -> continue SCANNING (no confirmed NG).
- Shape detected but wrong relative position -> stable `Shape PASS / Position NG` fail candidate.
- Complete aligned label with wrong/missing shape -> stable `Shape NG` fail candidate.
The existing `fail_confirmations` gate is retained, so a transient bad frame does not immediately become confirmed NG.
