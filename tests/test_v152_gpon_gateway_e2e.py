import unittest, json
from pathlib import Path
from label_tool.core.direct_guided_ocr import DirectGuidedOCR, DEFAULT_TARGETS
from label_tool.core.smart_lock import SmartLockEngine

class V152GPONGatewayE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        profile=json.loads(
            Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8")
        )
        cls.target=next(x for x in DEFAULT_TARGETS if x.item=="Fixed: GPON VoIP Gateway")
        cls.ocr=DirectGuidedOCR(profile, ocr_backend=object())

    def test_gateway_exact_text_rule_passes(self):
        rows,expected,score=self.ocr._evaluate(self.target,"GPON VoIP\nGateway",{}, {})
        self.assertTrue(any(r.status=="PASS" for r in rows))
        self.assertGreaterEqual(score,self.target.threshold)

    def test_gateway_volp_confusion_rule_passes(self):
        rows,expected,score=self.ocr._evaluate(self.target,"GPON VolP\nGateway",{}, {})
        self.assertTrue(any(r.status=="PASS" for r in rows))
        self.assertGreaterEqual(score,self.target.threshold)

    def test_two_passes_reach_lock(self):
        locks=SmartLockEngine(["Fixed: GPON VoIP Gateway"],2,3,12.0)
        value="GPON VoIP Gateway"
        s1=locks.offer(
            "Fixed: GPON VoIP Gateway",value,"PASS","score=1.000",
            source="Direct Guided OCR"
        )
        self.assertEqual(locks.status_text("Fixed: GPON VoIP Gateway"),"PASS 1/2")
        self.assertNotEqual(s1,"LOCK")
        s2=locks.offer(
            "Fixed: GPON VoIP Gateway",value,"PASS","score=1.000",
            source="Direct Guided OCR"
        )
        self.assertEqual(s2,"LOCK")
        self.assertTrue(locks.is_locked("Fixed: GPON VoIP Gateway"))

if __name__=="__main__":
    unittest.main()
