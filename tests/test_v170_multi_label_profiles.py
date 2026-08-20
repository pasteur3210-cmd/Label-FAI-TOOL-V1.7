import unittest, json
from pathlib import Path
from label_tool.core.profile_manager import discover_profiles
from label_tool.core.direct_guided_ocr import targets_from_profile
from label_tool.core.production_zone_ocr import ProductionZoneScheduler, MultiFieldZoneOCR

class _FakeOCR:
    def __init__(self,text=""): self.text=text; self.calls=0
    def read(self,image): self.calls+=1; return self.text, []

class V170MultiLabelProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json")
        cls.inner=json.loads(cls.path.read_text(encoding="utf-8"))

    def test_inner_box_profile_identity(self):
        self.assertEqual(self.inner["profile_name"],"GRG-4297u-TSL-P1 - Inner Box Label")
        self.assertEqual(self.inner["label_type"],"Inner Box Label")
        self.assertEqual(self.inner["label_pn"],"680010-353")
        self.assertEqual(self.inner["blank_label_pn"],"502109-180")

    def test_inner_box_has_three_production_zones(self):
        sched=ProductionZoneScheduler.from_profile(self.inner)
        self.assertEqual([z.id for z in sched.zones],["A","B","C"])

    def test_doc_link_custom_target_is_profile_driven(self):
        targets={t.item:t for t in targets_from_profile(self.inner)}
        self.assertIn("Fixed: DoC Link",targets)
        self.assertEqual(targets["Fixed: DoC Link"].mode,"fuzzy")
        self.assertIn("download.comtrend.com",targets["Fixed: DoC Link"].expected)

    def test_zone_ocr_can_evaluate_custom_doc_link(self):
        import numpy as np
        backend=_FakeOCR("DoC link: http://download.comtrend.com/DoC/GRG-4297u-TSL.html")
        ocr=MultiFieldZoneOCR(self.inner,ocr_backend=backend)
        zone=ProductionZoneScheduler.from_profile(self.inner).zones[2]
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        frame[400:680:2,100:1200:2]=255
        result=ocr.analyze(frame,zone,{},{"made_in":"China"},min_sharpness=0,requested_items=["Fixed: DoC Link"])
        rows=[r for r in result.rows if r.name=="Fixed: DoC Link"]
        self.assertEqual(backend.calls,1)
        self.assertTrue(rows)
        self.assertEqual(rows[0].status,"PASS")

    def test_artwork_candidates_are_registered(self):
        art=self.inner["artwork_verification"]
        ids={x["id"] for x in art["symbols"]}
        self.assertTrue({"comtrend_logo","recycling_mark","ce_mark","weee_mark"} <= ids)
        # Whether these candidates are blocking is version-specific and is
        # verified by the active-version tests.

if __name__=="__main__":
    unittest.main()
