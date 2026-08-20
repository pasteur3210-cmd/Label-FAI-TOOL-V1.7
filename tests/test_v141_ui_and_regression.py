import unittest
import hashlib
from pathlib import Path
import json
import numpy as np

from label_tool.core.direct_guided_ocr import DEFAULT_TARGETS, crop_relative


PROTECTED_HASHES = {
    # Populated by release generator from V1.4.0 baseline.
}


class V141UIAndRegressionTests(unittest.TestCase):
    def test_all_single_line_targets_are_centered(self):
        for t in DEFAULT_TARGETS:
            if t.mode=="address":
                continue
            x1,y1,x2,y2=t.target_rect
            self.assertAlmostEqual((x1+x2)/2,0.5,places=3)
            self.assertAlmostEqual((y1+y2)/2,0.5,places=3)
            self.assertLess(y2-y1,0.22)

    def test_address_target_centered_and_taller(self):
        t=[x for x in DEFAULT_TARGETS if x.mode=="address"][0]
        x1,y1,x2,y2=t.target_rect
        self.assertAlmostEqual((x1+x2)/2,0.5,places=3)
        self.assertAlmostEqual((y1+y2)/2,0.5,places=3)
        self.assertGreater(y2-y1,0.30)

    def test_target_crop_does_not_modify_full_frame(self):
        frame=np.random.default_rng(1).integers(0,255,(720,1280,3),dtype=np.uint8)
        before=frame.copy()
        t=DEFAULT_TARGETS[0]
        roi=crop_relative(frame,t.target_rect)
        self.assertGreater(roi.size,0)
        self.assertTrue(np.array_equal(frame,before))

    def test_fast_machine_still_reads_full_raw_frame(self):
        src=Path("label_tool/core/fast_machine_reader.py").read_text(encoding="utf-8")
        self.assertIn("zxingcpp.read_barcodes(rgb)",src)
        self.assertNotIn("crop_relative",src)
        self.assertNotIn("target_rect",src)

    def test_app_has_target_zoom_and_crosshair(self):
        src=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn("_update_target_zoom",src)
        self.assertIn("_draw_target_overlay",src)
        self.assertIn("cv2.line",src)
        self.assertIn("OCR Target Zoom",src)

    def test_profile_marks_barcode_pipeline_protected(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertTrue(d["live"]["barcode_pipeline_protected"])
        self.assertTrue(d["live"]["center_scan_window"])
        self.assertTrue(d["live"]["target_zoom_enabled"])


if __name__=="__main__":
    unittest.main()
