# Root Cause / Verification - V1.7.2

## Root-cause conclusion
The field behavior is isolated to the Artwork path. Fixed text, barcode and other already-locked fields use separate OCR/decoder paths. V1.7.1 Artwork recognition relied on correlation of thresholded full-frame images and did not normalize the whole label for relative-position judgment.

## Verification performed in development environment
- Full Python test suite: PASS.
- Total tests: 137 passed.
- V1.7.2 artwork targeted tests: PASS.
- Operator COMTREND camera screenshot regression: PASS for shape detection.
- Golden Label Example camera-frame simulation: COMTREND / Recycling / CE / WEEE all PASS shape + relative-position evaluation after label normalization.
- Build resource configuration review: `label_tool/golden_artwork` remains included by PyInstaller `build.spec`, therefore `golden_layout.png` and symbol templates are packaged with the Windows build.
- Python byte-code compile check: PASS.

## Production check required after GitHub Windows build
Because this environment cannot access the user's physical camera or exact production lighting, final release validation must include the actual Inner Box Label on the Windows production PC:
1. Keep the entire label visible in Zone C.
2. Confirm all four artwork items reach PASS 1/2 then LOCK.
3. Confirm a deliberately moved/wrong-position symbol does not LOCK.
4. Confirm changing camera distance does not cause FAIL solely because artwork pixel size changed.
5. Attach the generated session `execution.log`, `test.log`, and `debug.log` if any artwork remains SCANNING.
