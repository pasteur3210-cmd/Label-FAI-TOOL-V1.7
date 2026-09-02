# Label Auto Inspection Tool V1.9.19

## V1.9.19 Program-Plan Alignment (CMP-001 / CMP-002 / CMP-003 / CMP-008)

- CMP-001: Dynamic Golden now distinguishes shipped Chassis Label inspection scope from process/reference or lower production/test zones. Excluded rows remain traceable in Profile Manager as `REFERENCE_ONLY` but do not become runtime requirements.
- CMP-002 / CMP-003: Password and WiFi Key remain **length-only** checks as requested; no MAC/SN substring exclusion is added in this release.
- CMP-008: Request-Form notch/cut-corner text (e.g. top-left) becomes `Geometry: Label Notch Direction`. The full-label image uses a conservative automatic geometry check; uncertain cases remain Manual Review, never bypassed.
- Legacy CAM/Image OCR, Barcode/QR, evidence fusion and Manual Review paths remain protected by regression gates.


## V1.9.18 Factory Golden locator + Image field-log verification

- Manual Review now uses an arrow/callout as the primary locator on the complete Final Golden. Small corner ticks are only an approximate aid, avoiding misleading large rectangles when ROI geometry is slightly off.
- Barcode/consistency review is field-safe: GPON S/N, MAC and S/N select their own machine-code candidate by payload semantics / exact actual value / nearest field label and never default to the first barcode.
- V1.9.17 Image field logs were reviewed as a release baseline: both Chassis and Inner Box sessions kept Identity=PASS and completed as PASS_WITH_MANUAL_REVIEW after traceable operator decisions.
- CAM behavior is intentionally unchanged and remains covered by the existing regression/smoke gates; the user's current field log covered Image mode only.


## V1.9.18 Factory Manual Completion + Password Rule Hotfix

- Fix Golden Request Form `Password: Random N characters` parsing; GRG-4297u now derives `password_length=8` instead of 0.
- Existing external V1.9.16 Dynamic Profiles are migrated at runtime: an invalid/missing password length is re-derived from numbered Golden form items, so re-import is not required.
- Every non-PASS inspection item has a traceable Manual PASS path. Automatic result/evidence is preserved in `manual_overrides`, Excel/JSON and execution/test/debug logs.
- Cross-image identity mismatch now exposes a manual completion path while preserving `automatic_overall=IDENTITY_MISMATCH`.
- COMTREND Golden marker padding is calculated from the detected logo box instead of full-image dimensions to reduce visible ROI offset.
- Validate Profile remains manual-first: AUTO or MANUAL is accepted as a handling path; missing handling path alone blocks validation.

## V1.9.18 Deterministic Golden Reference + Manual-First Validation

- Numbered Request-Form items are bound to Manual Review by exact form item ID; numbered forms no longer use fuzzy cross-item lookup.
- Legacy DOC -> DOCX VML image references after `Label Example` are recognized, and the exact Final Label image is persisted in the Profile.
- Old external Dynamic Profiles are migrated once at runtime to remove stale support/password Golden Text requirements left by earlier releases.
- `Validate Profile` now accepts MANUAL REVIEW as a first-class traceable handling path. Validation blocks only a missing Golden item or a Required item with neither AUTO nor MANUAL handling.
- Validation confirmation shows AUTO / MANUAL / Disabled / Missing counts before changing DRAFT to VALIDATED.
- Existing CAM/Image automatic decision engines remain unchanged by this release.

## V1.9.18 Form-Driven Multi-Golden Factory Release

- Controlled Label Request Form numbers (1..N) are now the authoritative inspection-item list.
- Word list numbering is reconstructed after legacy DOC -> DOCX conversion, so older forms do not lose item numbers.
- Nested numbered password/rule lists remain attached to their parent item instead of becoming fake label items.
- Empty numbered items are retained as `Needs Review` and cannot be silently bypassed.
- Barcode/QR requirements are mandatory. Known S/N/MAC/GPON barcodes use field-safe mapping; undefined code semantics remain in operator review.
- Composite items such as WiFi Key + QR retain both the printed-field check and QR presence/review path.
- Final Label reference is selected structurally from the image placed after `Label Example`, preventing password/procedure screenshots from becoming the manual-review Golden image.
- Manual Review continues to show the Final Label plus the exact numbered Request-Form specification.
- Dynamic Golden remains isolated from Legacy model-specific rules; Legacy CAM/Image behavior remains under the existing regression suite.

## V1.9.18 Final Label + Item Specification Manual Review Fix

This release fixes a factory-review regression where MAC, Made-in and other Golden items could show an unrelated embedded support screenshot (for example a password proposal) as the Golden reference. Manual Review now separates the controlled document into two references:

1. **Final Label / Full Golden** – the embedded image that best matches a printed label, selected by label-field anchors and QR/barcode evidence rather than file size.
2. **Golden Item Specification** – the exact numbered Request-Form item text for the field being reviewed.

Focus Item is restricted to OCR/code geometry from the selected Final Label image only. Support screenshots are never eligible for field focus. If a reliable Final Label ROI cannot be located, the full Final Label remains visible instead of showing a guessed crop.

Legacy CAM/Image automatic inspection modules are unchanged from V1.9.13; this release changes Golden import/review selection and Manual Review presentation only.

## V1.9.18 Factory Validation Release

This release freezes the validated Legacy CAM/Image decision engines and completes the Manual Review Golden-reference workflow. The complete Golden label is always the initial view, and the currently reviewed item is highlighted when a reliable location can be derived. Golden Text and machine-code items use their typed ROI; COMTREND/WEEE and other known artwork use conservative review-only locators without changing automatic PASS/FAIL. `Full Golden / 完整Golden` now actively resets and fits the complete Golden with the current-item highlight, while `Focus Item / 項目放大` is enabled only for a reliable focus ROI. Suggested-only artwork areas remain highlighted on Full Golden but cannot be focused, preventing a misleading crop.

Release gates cover Dynamic Golden completeness, mandatory Barcode/QR non-bypass, stale-profile isolation, QR fusion, operator-attention traceability, Python 3.11 compatibility, package hygiene, and the V1.9.18 strict Artwork ROI safety regression.

## V1.9.18 Manual Review Responsive UI Hotfix
- Manual-review decision controls moved above the Actual/Golden images, so Windows taskbar/display scaling cannot hide them.
- Popup geometry is calculated from the current screen instead of fixed 1320x790.
- Confirm PASS remains visible for every item; REVIEW_ONLY items show it disabled rather than making the button disappear.
- Legacy CAM/Image detection logic and Dynamic Golden decision logic are unchanged.


## V1.9.18 Operator-Attention + Clean Golden Reload Integration

This release keeps the validated automatic CAM/Image decision rules intact while hardening the Dynamic Golden integration and making manual review usable as a production fallback.

### Dynamic Golden / Profile isolation
1. Import Golden always starts from a clean generic engine template; model-specific required items, expected text, artwork and rules are not inherited from the previously selected profile.
2. Re-importing the same Model / Label P/N uses transactional asset replacement. Previous embedded Golden images are removed only after the new profile passes structure/identity checks.
3. Switching Profile/Golden invalidates the previous Image result and Manual Review list. Loaded photos may remain selected, but they must be analyzed again under the new profile before results can be used.
4. Dynamic profile UI identity remains unique by Label P/N.

### Manual Review / operator attention
- Every required item whose automatic result is not PASS/MANUAL_PASS appears in the Manual Review list.
- `OVERRIDE_ALLOWED`: visual/Golden/fixed-text/artwork items can become `MANUAL_PASS` only after Actual-vs-Golden comparison.
- `REVIEW_ONLY`: identity, barcode, QR/consistency and other traceability-sensitive items are still shown, but a single visual click cannot change the machine result to PASS.
- Review-only actions (`KEEP_AUTO`, `CONFIRM_FAIL`, `REQUEST_RECHECK`) are recorded.
- Manual PASS and review actions are written to execution/test/debug logs, `result.json`, and the Excel `Manual_Review_Log` sheet.
- One item is reviewed at a time so the displayed Actual/Golden pair always corresponds to the decision being recorded.

### Regression protection
Automatic OCR, barcode, artwork, evidence fusion, incremental cache and automatic PASS/FAIL behavior remain covered by the existing regression suite. V1.9.18 adds dedicated tests for all-non-PASS operator attention, review-only protection, stale Golden asset removal, and Profile/Golden session invalidation.

GitHub Actions uses Python 3.11, workspace cleanup, release gate, end-to-end integration gate, Ruff F821, compile check, unit tests, PyInstaller build, and packaged EXE OCR/Artwork/Multi-image smoke tests.