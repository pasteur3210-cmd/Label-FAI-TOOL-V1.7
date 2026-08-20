import unittest
from pathlib import Path
import json

class FastMachineArchitectureTests(unittest.TestCase):
    def test_fast_reader_is_full_frame_single_decode_path(self):
        src = Path("label_tool/core/fast_machine_reader.py").read_text(encoding="utf-8")
        self.assertIn("zxingcpp.read_barcodes(rgb)", src)
        self.assertNotIn("detect_label(", src)
        self.assertNotIn("barcode_variants", src)
        self.assertNotIn("OCR", src.split("class FastMachineReader")[1].split("def read")[1])

    def test_fast_reader_runs_separate_from_zone_scheduler(self):
        src = Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn("def _schedule_machine_read", src)
        self.assertIn("def _schedule_live", src)
        self.assertIn("FastMachineReader", src)

    def test_camera_uses_proven_fqc_resolution(self):
        d = json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertEqual(d["live"]["camera_width"], 1280)
        self.assertEqual(d["live"]["camera_height"], 720)

    def test_barcode_items_removed_from_guided_ocr_zones(self):
        d = json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        zones = {z["id"]: z for z in d["live"]["zones"]}
        self.assertNotIn("Variable: S/N Barcode Format", zones["C1"]["items"])
        self.assertNotIn("Variable: MAC Barcode Format", zones["C2"]["items"])
        self.assertNotIn("Variable: GPON S/N Barcode Format", zones["C3"]["items"])
        self.assertNotIn("Variable: WiFi QR Format", zones["B"]["items"])

    def test_legacy_zone_merge_is_disabled_in_v140(self):
        src = Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn("Legacy V1.3 ROI pipeline intentionally disabled for live V1.4", src)
        self.assertIn("DirectGuidedOCR", src)

if __name__ == "__main__":
    unittest.main()
