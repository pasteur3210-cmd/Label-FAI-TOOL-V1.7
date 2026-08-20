# Label Auto Inspection Tool V1.7.3

GitHub Build Ready repository.

## Profiles
- Chassis Label
- Inner Box Label

Both profiles support Artwork shape + relative-position verification.
Artwork printed size is intentionally not judged.

## Build
GitHub Actions workflow: `.github/workflows/build.yml`

V1.7.3 adds:
- robust Golden Artwork runtime resource discovery;
- external `golden_artwork` copy beside packaged EXE;
- packaged EXE Artwork resource smoke test;
- Chassis Label Artwork checks: COMTREND, Recycling, RoHS, CE, WEEE;
- Inner Box Label Artwork checks: COMTREND, Recycling, CE, WEEE;
- profile dropdown names simplified to `Chassis Label` and `Inner Box Label`;
- fix: empty Artwork request no longer evaluates all Artwork.
