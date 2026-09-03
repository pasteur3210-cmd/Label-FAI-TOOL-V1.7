# Label Inspection Tool V1.9.24 Release Notes

This release addresses the V1.9.23 GRG-4297u Carton Label field record supplied on 2026-09-03.

## Root cause confirmed from the field record
The field `result.json` recorded `Work Order: MAC Allocation Step = NEED_MORE_IMAGE` with message `MAC not recognized` even though the Carton Label Request Form contains no MAC item. The cause was a previously selected GUI Work Order checkbox leaking into the new Dynamic Golden scope.

The report could still end as `PASS_WITH_MANUAL_REVIEW` after the operator confirmed the Golden barcode, while the pre-manual machine decision remained `NEED_MORE_IMAGE`. That difference is intentionally retained for traceability, but the previous Summary labels were easy to misread.

## V1.9.24 behavior
1. Imported Golden/Profile scope is authoritative for optional Work Order checks.
2. If MAC is absent from the form/profile, `Check MAC Range` and `Check MAC Allocation Step` are disabled and forced out of evaluation.
3. The engine independently re-applies the scope rule so a GUI-state regression cannot contaminate batch inspection.
4. Scope-sanitized values are stored in `expected_work_order`, session cache context, JSON and Excel.
5. `Inspection_Result` lists only in-scope required items.
6. Summary uses `Final Result` and `Auto Result Before Manual Review`.

For this Carton profile the expected state is therefore:
- Model: `GRG-4297u`
- Label Type: `Carton Label`
- Label P/N: `680010-354`
- MAC Range: disabled
- MAC Allocation Step: disabled
- Manual barcode review: still traceable when the Golden requires operator confirmation

## Regression / compatibility
Legacy bundled profiles without form-driven scope keep their historical optional Work Order behavior. Explicit S/N or MAC items in a Golden/Profile still enable the corresponding production checks. Existing CAM/Image OCR, Barcode/QR, Dynamic Golden, Manual Review, identity consistency, path-length hardening, and packaging rules remain covered by the regression suite.

## Verification
- pytest: 316 passed
- unittest: 202 passed
- V1.9.24 dedicated regression: 5 passed
- Integration Gate: PASS
- Release Gate after cleanup: PASS
- GitHub Actions retains Ruff F821, Python 3.11, Windows PyInstaller and packaged EXE smoke gates.
