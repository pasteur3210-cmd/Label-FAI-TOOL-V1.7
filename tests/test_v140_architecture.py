import unittest
from pathlib import Path
import json


class V140ArchitectureTests(unittest.TestCase):
    def test_live_app_uses_direct_guided_ocr(self):
        src=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn("DirectGuidedOCR",src)
        self.assertIn("GUIDED_OCR",src)
        self.assertIn("target.target_rect",src)

    def test_live_worker_does_not_call_legacy_analyze(self):
        src=Path("label_tool/app.py").read_text(encoding="utf-8")
        a=src.index("def _guided_worker")
        b=src.index("def _merge_guided_result")
        body=src[a:b]
        self.assertIn("self.guided_ocr.analyze",body)
        self.assertNotIn("self.live_analyzer.analyze",body)

    def test_profile_disables_live_label_detection(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertFalse(d["live"]["legacy_label_detection_live_enabled"])
        self.assertTrue(d["live"]["target_equals_actual_ocr_crop"])
        self.assertFalse(d["live"]["auto_rotate_guided_items_on_failure"])

    def test_fast_machine_reader_retained(self):
        src=Path("label_tool/core/fast_machine_reader.py").read_text(encoding="utf-8")
        self.assertIn("zxingcpp.read_barcodes(rgb)",src)
        self.assertNotIn("detect_label(",src)


if __name__=="__main__":
    unittest.main()
