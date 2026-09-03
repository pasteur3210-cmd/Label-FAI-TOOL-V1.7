# Change Log

## V1.9.24 - 2026-09-03

### Fixed
- Dynamic Golden/Profile scope now controls optional Work Order S/N/MAC checks; stale GUI checkboxes cannot add checks absent from the imported Request Form.
- GRG-4297u Carton Label automatically excludes `Work Order: MAC Range` and `Work Order: MAC Allocation Step` because the Golden form has no MAC field.
- Image engine sanitizes work-order metadata before cache context, evaluation, JSON and Excel output.
- `Inspection_Result` is generated from the same scope-controlled required-item list, eliminating hidden out-of-scope NEED_MORE_IMAGE rows.
- Excel Summary now labels the final decision as `Final Result` and the preserved pre-manual machine decision as `Auto Result Before Manual Review`.
- Retains V1.9.23 Carton identity corrections: finished Label P/N `680010-354`, Model/Label Type separation, and operator UI hierarchy.

### Packaging
- Release folder/artifact naming remains `Label_Inspection_Tool_V1.9.24`.
- Modification descriptions remain in Markdown / engineering documents instead of folder names.
