# Label Auto Inspection Tool V1.9.3

## Dynamic Golden Profile Engine

V1.9.3 keeps the validated V1.8.2 incremental image cache and Manual Review workflow, and adds external Golden-driven profiles so a new label can be introduced without editing Python or rebuilding the EXE.

### New workflow
1. Select the closest existing profile as a baseline.
2. Click **Import Golden** and choose DOC / DOCX / PNG / JPG.
3. The tool extracts Golden text/media and creates an external `profiles/<name>.json` DRAFT profile next to the EXE.
4. Review **Summary / Inspection Items** in **Profile Manager**. Raw JSON is moved to an Advanced tab for engineering-only changes.
5. Test known-good label images and click **Validate Profile** after engineering confirmation.
6. Future runs load the external profile directly; no GitHub rebuild is required for profile changes.

Legacy `.doc` import uses Microsoft Word COM on Windows to convert the file to DOCX. DOCX and image import do not require Word.

### Safety / traceability
- Imported Golden SHA-256 and timestamps are saved in the profile.
- Dynamic Profile name/file identity is generated from the imported Golden Model + Label Type + P/N; seed profile names cannot leak into a new Model.
- Identity mismatch blocks Save/Validate. Legacy malformed V1.9.0/V1.9.1 dynamic profiles are skipped and should be re-imported from Golden.
- Profile edits change the cache context hash, so stale image evidence is not reused.
- Dynamic Golden fixed-text checks run from profile data using fuzzy OCR similarity.
- `dynamic_variable_fields` may define profile-only regex checks without changing source code.
- Dynamic profiles start as **DRAFT** and become **VALIDATED** only after explicit engineering confirmation.
- Existing Chassis / Inner Box profiles remain bundled and regression protected.

### Performance
V1.8.2 incremental behavior remains: previously analyzed photos are cache hits; only new/unresolved evidence is analyzed. `Force Re-analyze All` remains available for engineering verification.
