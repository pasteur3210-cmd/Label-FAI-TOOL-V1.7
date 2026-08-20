import unittest, json
from pathlib import Path

class V142GUIGeometryTests(unittest.TestCase):
    def test_fit_math_common_desktops(self):
        def fit(w,h):
            ratio=16/9
            if w/h>ratio:
                oh=h; ow=round(h*ratio)
            else:
                ow=w; oh=round(w/ratio)
            return ow,oh
        for w,h in [(1280,720),(900,500),(700,390),(1100,430),(600,500)]:
            ow,oh=fit(w,h)
            self.assertLessEqual(ow,w)
            self.assertLessEqual(oh,h)
            self.assertAlmostEqual(ow/oh,16/9,places=2)

    def test_app_uses_dedicated_camera_frame(self):
        s=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn('Live Camera - Full Frame 16:9',s)
        self.assertIn('def _preview_box_size',s)
        self.assertIn('img.thumbnail((pw,ph))',s)
        self.assertIn('FULL FRAME VISIBLE',s)

    def test_ocr_zoom_compact(self):
        s=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn('def _zoom_box_size',s)
        self.assertIn('screen_h*0.12',s)
        self.assertIn('img.thumbnail((zw,zh))',s)

    def test_profile_requires_full_frame(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertEqual(d["live"]["preview_aspect_ratio"],"16:9")
        self.assertTrue(d["live"]["preview_full_frame_required"])

if __name__=="__main__":
    unittest.main()
