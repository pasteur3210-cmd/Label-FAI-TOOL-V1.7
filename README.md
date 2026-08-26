# Label Auto Inspection Tool V1.9.11

## V1.9.11 Manual Review Responsive UI Hotfix
- Manual-review decision controls moved above the Actual/Golden images, so Windows taskbar/display scaling cannot hide them.
- Popup geometry is calculated from the current screen instead of fixed 1320x790.
- Confirm PASS remains visible for every item; REVIEW_ONLY items show it disabled rather than making the button disappear.
- Legacy CAM/Image detection logic and Dynamic Golden decision logic are unchanged.


## V1.9.11 Operator-Attention + Clean Golden Reload Integration

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
Automatic OCR, barcode, artwork, evidence fusion, incremental cache and automatic PASS/FAIL behavior remain covered by the existing regression suite. V1.9.11 adds dedicated tests for all-non-PASS operator attention, review-only protection, stale Golden asset removal, and Profile/Golden session invalidation.

GitHub Actions uses Python 3.11, workspace cleanup, release gate, end-to-end integration gate, Ruff F821, compile check, unit tests, PyInstaller build, and packaged EXE OCR/Artwork/Multi-image smoke tests.
