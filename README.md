# Label Auto Inspection Tool V1.7.4

GitHub Build Ready repository.

## Profiles
- Chassis Label
- Inner Box Label

Both profiles support Artwork shape + relative-position verification. Printed Artwork size is intentionally **not** an acceptance criterion.

## V1.7.4 main changes
- Artwork processing runs only when the active Production Zone contains `Artwork:` items. Earlier OCR/Barcode zones stay on the fast path.
- Registered ROI Artwork inspection: full label registration first, then each symbol is searched only near its Golden expected position.
- Golden ghost/contour overlay for operator alignment; overlay size is guidance only and is not used for PASS/FAIL.
- Incomplete/poor label alignment returns `WARN / ALIGN LABEL` and does not accumulate FAIL confirmations.
- Inner Box COMTREND threshold recalibrated from Golden + field evidence; ROI restriction reduces false-positive risk.
- Unicode/space-safe PNG loading using `numpy.fromfile + cv2.imdecode`.
- Each Golden Artwork file is resolved independently; a stale/partial root can no longer hide a valid copy.
- Manual Previous/Next Zone is held and is not immediately overwritten by auto-scheduler.
- Retry Zone clears only unfinished candidate/fail state and preserves existing LOCK results.
- Auto Focus commands are serialized on the Camera capture thread and use OFF -> ON re-trigger.
- Resource errors are shown/logged as `RESOURCE ERROR`, not endless `SCANNING`.
- GitHub Actions adds packaged EXE Artwork smoke tests from both normal and Unicode/space paths.

## Build
GitHub Actions workflow: `.github/workflows/build.yml`

Upload the contents of `01_GITHUB_UPLOAD` to the repository root. The engineering documents in `02_ENGINEERING_DOCUMENTS` do not need to be uploaded to GitHub.
