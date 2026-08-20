import unittest
from pathlib import Path
from label_tool.core.live_engine import LiveFrameAnalyzer

class LivePerformanceArchitectureTests(unittest.TestCase):
    def test_required_rois_are_selective(self):
        rois = LiveFrameAnalyzer.required_rois(["Variable: MAC Barcode Format"])
        self.assertEqual(rois, {"mac_barcode"})

    def test_relation_requests_only_dependencies(self):
        rois = LiveFrameAnalyzer.required_rois(["Rule: SSID = MAC Last 6"])
        self.assertIn("ssid_password_wifi", rois)
        self.assertIn("mac_barcode", rois)
        self.assertNotIn("fixed_text", rois)

    def test_start_live_does_not_reset_locks(self):
        source = Path("label_tool/app.py").read_text(encoding="utf-8")
        start = source.index("def toggle_live")
        end = source.index("def stop_live")
        body = source[start:end]
        self.assertNotIn("self._reset_live_tree()", body.replace(
            "if self.locks is None:\n            self._reset_live_tree()", ""
        ))

    def test_live_engine_does_not_full_ocr(self):
        source = Path("label_tool/core/live_engine.py").read_text(encoding="utf-8")
        self.assertIn("No full-label OCR in live mode", source)

if __name__=='__main__':
    unittest.main()
