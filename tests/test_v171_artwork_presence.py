import unittest, json
from pathlib import Path
import cv2
import numpy as np
from label_tool.core.artwork_presence import ArtworkPresenceDetector, bundled_artwork_dir

class V171ArtworkPresenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))
        cls.detector=ArtworkPresenceDetector(cls.profile)

    def _synthetic_frame_with_templates(self):
        frame=np.full((720,1280,3),235,dtype=np.uint8)
        positions=[(80,90,0.9),(650,420,1.25),(820,420,0.75),(1000,390,1.10)]
        for cfg,(x,y,scale) in zip(self.detector.symbols,positions):
            templ=self.detector.templates[cfg["item"]]
            w=max(8,int(templ.shape[1]*scale)); h=max(8,int(templ.shape[0]*scale))
            rs=cv2.resize(templ,(w,h),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_CUBIC)
            patch=cv2.cvtColor(rs,cv2.COLOR_GRAY2BGR)
            frame[y:y+h,x:x+w]=np.minimum(frame[y:y+h,x:x+w],patch)
        return frame

    def test_golden_templates_exist(self):
        root=bundled_artwork_dir()
        for name in ["comtrend_logo.png","recycling_mark.png","ce_mark.png","weee_mark.png"]:
            self.assertTrue((root/"grg4297u_inner_box"/name).exists())

    def test_legacy_synthetic_shape_detects_but_requires_label_alignment(self):
        frame=self._synthetic_frame_with_templates()
        rows,dets=self.detector.evaluate(frame)
        self.assertEqual(len(rows),4)
        self.assertTrue(all(r.status=="WARN" for r in rows))
        self.assertTrue(all(not d.label_aligned for d in dets))
        self.assertTrue(all("ALIGN LABEL" in r.message for r in rows))

    def test_absent_symbols_fail(self):
        frame=np.full((720,1280,3),235,dtype=np.uint8)
        rows,_=self.detector.evaluate(frame)
        self.assertTrue(all(r.status=="WARN" for r in rows))

    def test_profile_ignores_size_but_judges_shape_and_position(self):
        judged=self.profile["artwork_verification"]["judged_dimensions"]
        self.assertTrue(judged["category_presence"])
        self.assertTrue(judged["shape"])
        self.assertTrue(judged["position"])
        self.assertFalse(judged["size"])
        self.assertFalse(judged["spacing"])

if __name__=="__main__":
    unittest.main()
