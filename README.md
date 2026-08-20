# Label Auto Inspection Tool V1.7.2

Default OCR Mode: Production 4-Zone.

- Zone A: Basic Information
- Zone B: Wi-Fi Information
- Zone C: Device Identity
- Zone D: Compliance / Bottom Label

Each zone shows every field with LOCK / PASS 1/2 / Searching status. Fields lock independently. When all fields in a zone lock, the program advances automatically.

Use `Manual Item Debug` when engineering needs the old V1.5.3 one-item target workflow.

After Overall PASS the session folder contains:
- result.json
- Label_Inspection_Report_<session>.xlsx
- execution.log / test.log / debug.log / performance.log / lock_history.log
- images/ and target_ocr/

## V1.7.2 Artwork update
Inner Box Artwork inspection now judges **shape + relative position** after full-label normalization. Printed artwork size is intentionally ignored. Keep the entire Inner Box Label visible in Zone C so relative position can be evaluated. Detailed Artwork diagnostics are recorded in session debug/test logs.
