import json
from pathlib import Path
import unittest
import cv2
from label_tool.core.artwork_presence import ArtworkPresenceDetector

class V177ComtrendCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))

    def test_inner_box_comtrend_has_field_calibration(self):
        s=next(x for x in self.profile['artwork_verification']['symbols'] if x['id']=='comtrend_logo')
        self.assertEqual(s['shape_threshold'],0.30)
        self.assertEqual(s['shape_fail_threshold'],0.22)
        self.assertNotIn('expected_center',s)
        self.assertNotIn('search_roi_expand',s)

    def test_field_final_pass_replay_if_fixture_available(self):
        fixture=Path('tests/fixtures/v177_inner_box_final_pass.jpg')
        if not fixture.exists():
            self.skipTest('field replay fixture not packaged')
        img=cv2.imread(str(fixture))
        rows,_=ArtworkPresenceDetector(self.profile).evaluate(img,['Artwork: COMTREND Logo'])
        self.assertEqual(rows[0].status,'PASS',rows[0].message)

if __name__=='__main__': unittest.main()
