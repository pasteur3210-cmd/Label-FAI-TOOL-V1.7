import json
import unittest
from pathlib import Path
from label_tool.core.artwork_presence import ArtworkPresenceDetector


class V175AlignmentStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chassis=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))
        cls.inner=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))

    def test_chassis_uses_broad_anchor_guide(self):
        art=self.chassis['artwork_verification']
        self.assertEqual(art['guide_mode'],'outer_anchors')
        self.assertEqual(len(art['guide_anchors']),3)
        self.assertAlmostEqual(art['guide_aspect_ratio'],1.67,places=2)
        self.assertLessEqual(art['guide_width_ratio'],0.80)

    def test_artwork_registration_does_not_change_existing_ocr_vision(self):
        # V1.7.5 keeps the known-working V1.7.4 registration calibration while
        # isolating it in Artwork configuration; OCR/Barcode profile remains untouched.
        self.assertEqual(
            self.chassis['vision']['label_long_short_ratio'],
            self.chassis['artwork_verification']['registration_vision']['label_long_short_ratio']
        )

    def test_position_deadband(self):
        det=ArtworkPresenceDetector(self.chassis)
        expected=(0.5,0.5)
        cfg={'position_tolerance':[0.10,0.10]}
        self.assertEqual(det._position_state((0.58,0.5),expected,cfg)[0],'PASS')
        self.assertEqual(det._position_state((0.60,0.5),expected,cfg)[0],'VERIFY')
        self.assertEqual(det._position_state((0.62,0.5),expected,cfg)[0],'FAIL')

    def test_shape_deadband_chassis(self):
        det=ArtworkPresenceDetector(self.chassis)
        cfg={}
        self.assertEqual(det._shape_result(0.41,0.40,cfg),'PASS')
        self.assertEqual(det._shape_result(0.35,0.40,cfg),'VERIFY')
        self.assertEqual(det._shape_result(0.30,0.40,cfg),'FAIL')

    def test_recorded_v174_boundary_observations_become_verify_not_false_ng(self):
        det=ArtworkPresenceDetector(self.chassis)
        # From field log: COMTREND shape 0.341/0.40 and position error 1.03
        # oscillated around the old binary boundary. V1.7.5 must hold VERIFY.
        self.assertEqual(det._shape_result(0.341,0.40,{}),'VERIFY')
        expected=(0.5,0.5)
        cfg={'position_tolerance':[0.10,0.10]}
        state,_=det._position_state((0.603,0.5),expected,cfg)
        self.assertEqual(state,'VERIFY')

    def test_inner_and_chassis_size_judgment_remains_disabled(self):
        for p in (self.chassis,self.inner):
            self.assertFalse(p['artwork_verification']['judged_dimensions']['size'])

if __name__=='__main__':
    unittest.main()

class V175NoArtworkFastPathTests(unittest.TestCase):
    def test_empty_artwork_request_skips_registration(self):
        from unittest.mock import patch
        import numpy as np
        profile=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))
        det=ArtworkPresenceDetector(profile)
        frame=np.zeros((120,200,3),dtype=np.uint8)
        with patch('label_tool.core.artwork_presence.detect_label', side_effect=AssertionError('must not run')):
            rows,dets=det.evaluate(frame,requested_items=[])
        self.assertEqual(rows,[])
        self.assertEqual(dets,[])
