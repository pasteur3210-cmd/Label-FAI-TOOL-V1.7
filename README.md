# Label Auto Inspection Tool V1.8.2

## V1.8.2 - Performance Stage-2 / Incremental Image Analysis

V1.8.2 keeps the validated V1.8.1 recognition thresholds and Manual Review UI, but changes the multi-image execution architecture so adding a photo does not OCR older photos again.

Key changes:
- Session-level SHA-256 image fingerprint cache. Previously analyzed content is logged as `CACHE_HIT ... action=SKIP_OCR`.
- Incremental execution: `Run / Analyze New` reuses the existing `MultiImageResult`; only new unique images are sent to OCR/artwork analysis.
- Evidence-driven target list: after the first run, only unresolved/conflicting items are requested from additional photos.
- Early PASS: if all required evidence is already complete, newly added photos are recorded as `SKIPPED_AFTER_PASS` without OCR. Use `Force Re-analyze All` for engineering verification when intentional re-analysis is required.
- Duplicate-content protection: the same photo renamed to another filename is still a cache hit.
- Cache safety: Profile/Golden/work-order/software context changes invalidate the session instead of reusing stale evidence.
- Manual Review precedence is preserved across incremental runs. `Automatic Overall` remains the original machine decision while final `Overall` can remain `PASS_WITH_MANUAL_REVIEW`.
- V1.8.1 Compliance artwork detector cache and fixed Manual Review layout are retained.
- Regression validation: 206 tests pass.

Field benchmark reference supplied by operator: V1.8.1 five-image run ~163.2 s. V1.8.2 should be compared using `performance.log`; no unverified runtime claim is embedded in this release.

## V1.8.0 main changes
- Image Label Inspection now follows a guided five-photo evidence plan: Full Label + Basic/Logo + WiFi/User + Identity/Barcode + Compliance/Artwork.
- Partial close-ups are no longer required to pass full-label perspective registration before their text/barcode evidence can be used.
- Original-photo full-frame barcode/QR decode and OCR evidence are fused across photos, then relationship rules are re-run at session level.
- Full overview supplies artwork relative-position evidence; Basic/Compliance close-ups may supply higher-resolution artwork shape evidence.
- Additional photos can still be added with Recheck Unresolved.
- Image reports now include Photo_Roles and Session_Facts sheets.
- Live Camera / Smart Lock pipeline is not changed by this release.


Windows GUI label inspection tool for GRG-4297u Chassis Label and Inner Box Label.

## V1.8.0 main changes

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


## V1.8.0 hotfix

- Fixes GitHub Ruff F821 failure in multi-image `Add Images` UI path display.
- Reuses the already imported `os.path.basename()` instead of the undefined `Path` symbol.
- Adds a regression test for this exact failure.
- No inspection algorithm, Artwork, OCR, Barcode, Camera, Smart Lock, or report logic was changed.


## V1.8.0
- Non-blocking background worker for multi-image inspection with progress/cancel.
- Recheck Unresolved keeps prior evidence and filters new evidence to unresolved/conflict items.
- Per-image performance.log.
- COMTREND specialist detector: tighter Golden ROI + normalized gray/edge hybrid.

## V1.8.0 field hotfix
- Fixes false WiFi/WPA Key `CONFLICT` when general OCR confuses uppercase/lowercase but another photo exactly matches the decoded WiFi QR value.
- WiFi Key is still case-sensitive. Case-only ambiguity without exact evidence becomes `NEED_MORE_IMAGE`.
- Improves five-photo role assignment; compliance close-ups can be recognized from multiple compliance symbols.
- Phone-photo OCR is processed at a camera-like OCR resolution while barcode/artwork keep original resolution.

## V1.8.0 main changes
- Image Label Inspection: targeted `GPON VoIP Gateway` fixed-text rescue using fuzzy phrase confirmation and Golden-relative target OCR. This addresses the field case where OCR returned `GPON VolP Gateway` although the printed phrase was visually clear.
- Added Manual Review / visual-assist list for unresolved visual items. Eligible items can be confirmed as `MANUAL_PASS`; machine identity, barcode, and consistency items cannot be manually overridden.
- Final overall is `PASS_WITH_MANUAL_REVIEW` when automatic inspection is completed only with traceable human visual review.
- Excel/result.json now preserve automatic result, final result, manual-review flag/note, source image, and timestamp. execution/test/debug logs record every manual override.