# Label Auto Inspection Tool V1.9.5

## V1.9.5 Golden Completeness + Standard Library + Golden-assisted Manual Review

This release keeps the validated Legacy CAM / Image inspection engines unchanged and extends only the Dynamic Golden/Profile preparation and human-review workflow.

### Dynamic Golden workflow
1. Import the controlled Golden DOC/DOCX.
2. Numbered Request-Form items are extracted one-by-one. Items that cannot be classified are kept as `Needs Review`; they are never silently dropped.
3. Checkbox selections (`■ Yes`, `■ No`, selected alternatives) are preserved.
4. Profile Manager shows Golden items first. Existing Legacy checks are available under `Add Item > From Standard Library` instead of being pre-populated in the table.
5. Engineer may edit Golden rows, add Standard Library checks, or add a custom item. Any edit returns the profile to `DRAFT`.
6. `Validate Profile` blocks unresolved required items or required Artwork that has no Legacy mapping/template.
7. The resulting profile is consumed by the existing Legacy CAM / Image inspection engine.

### Manual Review
For eligible visual items, `Confirm Selected as PASS` now opens an Actual-vs-Golden comparison window before the operator confirms PASS. Automatic evidence/result remains preserved in logs and reports.

### Regression protection
V1.9.5 does not modify these validated Legacy core engines: `multi_image_inspection.py`, `live_engine.py`, `smart_lock.py`, `engine.py`, `artwork_presence.py`, `parser.py`, `rules.py`, `decoder.py`.

GitHub Actions uses Python 3.11, workspace cleanup, release gate, Ruff F821, compile check, unit tests, PyInstaller build, and packaged EXE OCR/Artwork/Multi-image smoke tests.
