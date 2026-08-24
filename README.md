# Label Auto Inspection Tool V1.7.7.1

Windows GUI label inspection tool for GRG-4297u Chassis Label and Inner Box Label.

## V1.7.7.1 main changes

- Adds **Image Label Inspection** production mode.
- Users can select multiple JPG/JPEG/PNG/BMP images in one batch.
- Per-item evidence fusion keeps the best usable image for each required check.
- Blurry/unreadable observations become `NEED_MORE_IMAGE` instead of automatic NG.
- `Add Images / Recheck Unresolved` can supplement the same inspection session.
- S/N, MAC and GPON S/N are used as cross-image identity consistency gates.
- Conflicting high-quality PASS/FAIL evidence is surfaced as `CONFLICT` and is not silently overwritten.
- Multi-image sessions save `execution.log`, `test.log`, `debug.log`, `result.json`, source images and an Excel report under `image_records/`.
- Inner Box COMTREND Artwork threshold band was field-calibrated from the 2026-08-24 live log. Replay predicts the two required PASS observations around the earlier valid cycles instead of waiting until the final 58-second borderline period.
- Existing Live Camera / Smart Lock flow remains separate and unchanged except for the COMTREND profile calibration.

## Build

Upload the contents of this repository to GitHub and run the Windows Actions workflow. The workflow installs dependencies, runs Ruff F821, compile checks, full unit/regression tests, then builds the PyInstaller Windows package and runs packaged OCR/Artwork smoke tests.

## Runtime records

Live Camera sessions: `live_records/`

Multi-image sessions: `image_records/`

Each multi-image session contains source images, per-image diagnostic outputs, `execution.log`, `test.log`, `debug.log`, `result.json`, and `Label_Image_Inspection_Report_*.xlsx`.


## V1.7.7.1 hotfix

- Fixes GitHub Ruff F821 failure in multi-image `Add Images` UI path display.
- Reuses the already imported `os.path.basename()` instead of the undefined `Path` symbol.
- Adds a regression test for this exact failure.
- No inspection algorithm, Artwork, OCR, Barcode, Camera, Smart Lock, or report logic was changed.
