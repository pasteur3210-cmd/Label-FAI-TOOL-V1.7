# Label Auto Inspection Tool V1.7.6.1

GitHub Build Ready repository.

## Profiles
- Chassis Label
- Inner Box Label

Both profiles support Artwork shape + relative-position verification. Printed Artwork size remains **not judged**.

## V1.7.6.1 main changes
- Artwork still runs only in the active Artwork production zone; OCR/Barcode zones remain on the original fast path.
- Chassis/Inner Box operator guide changed from many small symbol contours to a stable whole-label outline plus 3 broad anchors.
- The operator guide is static and does not jump with each registration candidate. It is placement guidance only, not a size gauge.
- Shape and position decisions now use PASS / VERIFY / FAIL dead-bands. Borderline camera jitter is held as VERIFY/WARN and does not accumulate false NG.
- Registered Golden ROI search is retained. Artwork size remains ignored for PASS/FAIL.
- Existing V1.7.4 Artwork registration calibration is preserved to avoid disturbing the proven OCR/Barcode pipeline.
- Unicode/space-safe Golden Artwork loading, resource self-test, manual zone navigation, Retry Zone, and serialized Auto Focus behavior from V1.7.4 are retained.
- New regression tests include V1.7.4 field-log boundary cases and a fast-path guard proving empty Artwork requests do not run registration.

## Build
GitHub Actions workflow: `.github/workflows/build.yml`

Upload the contents of `01_GITHUB_UPLOAD` to the repository root. `02_ENGINEERING_DOCUMENTS` is for local engineering records and does not need to be uploaded to GitHub.
