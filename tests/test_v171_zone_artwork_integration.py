import unittest, json
from pathlib import Path
import cv2
import numpy as np
from label_tool.core.production_zone_ocr import ProductionZoneScheduler, MultiFieldZoneOCR

class _FakeOCR:
    def read(self,image):
        return "DoC link: http://download.comtrend.com/DoC/GRG-4297u-TSL.html\nMade in China",[]

class V171ZoneArtworkIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))

    def test_zone_c_contains_four_artwork_required_items(self):
        z=ProductionZoneScheduler.from_profile(self.profile).zones[2]
        arts=[x for x in z.items if x.startswith("Artwork: ")]
        self.assertEqual(len(arts),4)
        req=set(self.profile["live"]["required_items"])
        self.assertTrue(set(arts)<=req)

    def test_artwork_outside_expected_label_position_does_not_pass(self):
        ocr=MultiFieldZoneOCR(self.profile,ocr_backend=_FakeOCR())
        frame=np.full((720,1280,3),235,dtype=np.uint8)
        templ=ocr.artwork.templates["Artwork: CE Mark"]
        t=cv2.cvtColor(templ,cv2.COLOR_GRAY2BGR)
        h,w=t.shape[:2]
        frame[20:20+h,20:20+w]=np.minimum(frame[20:20+h,20:20+w],t)
        z=ProductionZoneScheduler.from_profile(self.profile).zones[2]
        result=ocr.analyze(frame,z,{},{"made_in":"China"},min_sharpness=0,requested_items=["Artwork: CE Mark"])
        row=next(r for r in result.rows if r.name=="Artwork: CE Mark")
        self.assertEqual(row.status,"FAIL")
        self.assertIn("pos=FAIL",row.message)

if __name__=="__main__":
    unittest.main()
