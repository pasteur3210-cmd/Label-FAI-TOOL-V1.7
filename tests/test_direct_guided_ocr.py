import unittest
import numpy as np
from label_tool.core.direct_guided_ocr import (
    normalize_text, compact, similarity, best_line_similarity,
    GuidedItemScheduler, DEFAULT_TARGETS, crop_relative, DirectGuidedOCR
)
from label_tool.core.smart_lock import SmartLockEngine


class DirectGuidedOCRTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "fixed_fields":{"model":"GRG-4297u","ip":"192.168.1.1","username":"user"},
            "rules":{
                "pn_regex":r"738125-00\d","pn_display":"738125-00X",
                "password_length":8,"wifi_key_length":14,
                "ssid_prefix":"Telekom Slovenije_",
                "made_in_allowed":["China","Taiwan"],
            }
        }
        self.ocr = DirectGuidedOCR(self.profile)

    def test_target_crop_is_direct_frame_crop(self):
        img=np.zeros((100,200,3),dtype=np.uint8)
        roi=crop_relative(img,[0.25,0.25,0.75,0.75])
        self.assertEqual(roi.shape[:2],(50,100))

    def test_gateway_fuzzy_accepts_common_ocr_confusion(self):
        target=DEFAULT_TARGETS[0]
        rows,_,score=self.ocr._evaluate(target,"GPON VolP Gateway",{}, {})
        self.assertEqual(rows[0].status,"PASS")
        self.assertGreaterEqual(score,target.threshold)

    def test_model_compact_exact(self):
        target=DEFAULT_TARGETS[1]
        rows,_,_=self.ocr._evaluate(target,"Model : GRG - 4297u",{}, {})
        self.assertEqual(rows[0].status,"PASS")

    def test_sn_human_uses_barcode_ground_truth(self):
        target=[x for x in DEFAULT_TARGETS if x.mode=="sn_text"][0]
        gt="2654297UF-AA000028"
        rows,expected,_=self.ocr._evaluate(target,f"S/N: {gt}",{"sn_barcode":gt},{})
        self.assertEqual(rows[0].status,"PASS")
        self.assertEqual(expected,gt)

    def test_mac_human_waits_for_barcode_ground_truth(self):
        target=[x for x in DEFAULT_TARGETS if x.mode=="mac_text"][0]
        rows,_,_=self.ocr._evaluate(target,"MAC: 1C6A99AFB49D",{}, {})
        self.assertEqual(rows[0].status,"WARN")
        self.assertEqual(rows[0].error_code,"WAIT-BARCODE")

    def test_wifi_key_can_use_qr_ground_truth(self):
        target=[x for x in DEFAULT_TARGETS if x.mode=="wifi_key"][0]
        key="MMBbgVzJUrvn8Z"
        rows,_,_=self.ocr._evaluate(target,f"WiFi Key: {key}",{"qr_wifi_key":key},{})
        self.assertEqual(rows[0].status,"PASS")

    def test_ssid_can_use_mac_ground_truth(self):
        target=[x for x in DEFAULT_TARGETS if x.mode=="ssid"][0]
        mac="1C6A99AFB49D"
        rows,expected,_=self.ocr._evaluate(
            target,"SSID: Telekom Slovenije_AFB49D",{"mac_barcode":mac},{}
        )
        self.assertEqual(rows[0].status,"PASS")
        self.assertEqual(expected,"Telekom Slovenije_AFB49D")

    def test_scheduler_does_not_auto_rotate_on_failure(self):
        names=[t.item for t in DEFAULT_TARGETS]
        locks=SmartLockEngine(names)
        s=GuidedItemScheduler()
        first=s.current.item
        # Merely asking for current target repeatedly must not change item.
        self.assertEqual(s.select_next_incomplete(locks).item,first)
        self.assertEqual(s.select_next_incomplete(locks).item,first)

    def test_scheduler_advances_only_after_lock(self):
        names=[t.item for t in DEFAULT_TARGETS]
        locks=SmartLockEngine(names)
        s=GuidedItemScheduler()
        first=s.current.item
        locks.force_lock(first,"Present")
        self.assertTrue(s.advance_if_locked(locks))
        self.assertNotEqual(s.current.item,first)


    def test_scheduler_returns_none_when_all_guided_items_locked(self):
        names=[t.item for t in DEFAULT_TARGETS]
        locks=SmartLockEngine(names)
        s=GuidedItemScheduler()
        for name in names:
            locks.force_lock(name,"OK")
        self.assertIsNone(s.select_next_incomplete(locks))

    def test_wifi_key_ground_truth_is_case_sensitive(self):
        target=[x for x in DEFAULT_TARGETS if x.mode=="wifi_key"][0]
        expected="MMBbgVzJUrvn8Z"
        rows,_,_=self.ocr._evaluate(target,"WiFi Key: MMBBGVZJURVN8Z",{"qr_wifi_key":expected},{})
        self.assertEqual(rows[0].status,"WARN")

if __name__=="__main__":
    unittest.main()
