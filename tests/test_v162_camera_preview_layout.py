import unittest
from pathlib import Path
import json

class V162CameraPreviewLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=Path("label_tool/app.py").read_text(encoding="utf-8")

    def test_zone_panel_is_in_right_pane_not_live_tab(self):
        self.assertIn('zone = ttk.LabelFrame(right,text="Production Zone OCR / Manual Item Debug"', self.src)
        self.assertNotIn('zone = ttk.LabelFrame(self.live_tab,text="Production Zone OCR / Manual Item Debug"', self.src)

    def test_camera_frame_expands_in_both_directions(self):
        self.assertIn('self.camera_frame.pack(fill="both",expand=True', self.src)

    def test_production_mode_hides_ocr_zoom(self):
        body=self.src[self.src.index("    def _sync_live_layout_for_mode"):self.src.index("    def _on_ocr_mode_change")]
        self.assertIn("self.ocr_zoom_frame.pack_forget()", body)
        self.assertIn("self.guided_expected_label.grid_remove()", body)
        self.assertIn("self.guided_ocr_label.grid_remove()", body)

    def test_manual_debug_restores_ocr_zoom(self):
        body=self.src[self.src.index("    def _sync_live_layout_for_mode"):self.src.index("    def _on_ocr_mode_change")]
        self.assertIn('self.ocr_zoom_frame.pack(fill="x"', body)

    def test_production_zone_items_are_compact(self):
        body=self.src[self.src.index("    def _update_zone_ui"):self.src.index("    def next_guided_item")]
        self.assertIn('"  |  ".join(parts)', body)
        self.assertNotIn('"\\n".join(lines)', body)

    def test_profile_declares_preview_priority(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertTrue(d["live"]["camera_preview_priority_layout"])
        self.assertTrue(d["live"]["production_hide_ocr_zoom"])
        self.assertTrue(d["live"]["production_compact_zone_status"])

if __name__=="__main__":
    unittest.main()
