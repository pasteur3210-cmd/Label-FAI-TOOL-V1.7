# Label Auto Inspection Tool V1.9.1

## Dynamic Golden Profile Engine

V1.9.1 keeps the validated V1.8.2 incremental image cache and Manual Review workflow, and adds external Golden-driven profiles so a new label can be introduced without editing Python or rebuilding the EXE.

### New workflow
1. Select the closest existing profile as a baseline.
2. Click **Import Golden** and choose DOC / DOCX / PNG / JPG.
3. The tool extracts Golden text/media and creates an external `profiles/<name>.json` DRAFT profile next to the EXE.
4. Review the generated JSON in **Profile Manager**. Fixed text candidates, thresholds, required items, model/P/N metadata and artwork configuration are data in the profile, not source code.
5. Test known-good label images and click **Validate Profile** after engineering confirmation.
6. Future runs load the external profile directly; no GitHub rebuild is required for profile changes.

Legacy `.doc` import uses Microsoft Word COM on Windows to convert the file to DOCX. DOCX and image import do not require Word.

### Safety / traceability
- Imported Golden SHA-256 and timestamps are saved in the profile.
- Profile edits change the cache context hash, so stale image evidence is not reused.
- Dynamic Golden fixed-text checks run from profile data using fuzzy OCR similarity.
- `dynamic_variable_fields` may define profile-only regex checks without changing source code.
- Dynamic profiles start as **DRAFT** and become **VALIDATED** only after explicit engineering confirmation.
- Existing Chassis / Inner Box profiles remain bundled and regression protected.

### Performance
V1.8.2 incremental behavior remains: previously analyzed photos are cache hits; only new/unresolved evidence is analyzed. `Force Re-analyze All` remains available for engineering verification.
