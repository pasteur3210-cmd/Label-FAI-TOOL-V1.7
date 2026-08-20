import json
import unittest
from pathlib import Path

import cv2
import numpy as np

from label_tool.core.artwork_presence import ArtworkPresenceDetector


class V172ArtworkShapePositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))
        cls.detector = ArtworkPresenceDetector(cls.profile)

    def test_profile_enables_shape_position_but_ignores_size(self):
        judged = self.profile['artwork_verification']['judged_dimensions']
        self.assertTrue(judged['shape'])
        self.assertTrue(judged['position'])
        self.assertFalse(judged['size'])

    def test_expected_centers_are_calibrated_from_golden_layout(self):
        self.assertEqual(len(self.detector.expected_centers), 4)
        # Source-spec layout order: COMTREND upper-left; the three compliance marks lower-right.
        c = self.detector.expected_centers['Artwork: COMTREND Logo']
        r = self.detector.expected_centers['Artwork: Recycling Mark']
        ce = self.detector.expected_centers['Artwork: CE Mark']
        w = self.detector.expected_centers['Artwork: WEEE Mark']
        self.assertLess(c[0], r[0]); self.assertLess(c[1], r[1])
        self.assertLess(r[0], ce[0]); self.assertLess(ce[0], w[0])

    def test_position_gate_passes_expected_and_rejects_wrong_area(self):
        cfg = self.detector.symbols[0]
        expected = self.detector.expected_centers[cfg['item']]
        ok, err = self.detector._position_result(expected, expected, cfg)
        self.assertTrue(ok); self.assertAlmostEqual(err, 0.0)
        wrong = (min(0.99, expected[0] + 0.35), min(0.99, expected[1] + 0.35))
        ok, _ = self.detector._position_result(wrong, expected, cfg)
        self.assertFalse(ok)

    def test_multiscale_match_does_not_use_scale_as_acceptance(self):
        cfg = next(x for x in self.detector.symbols if x['item'] == 'Artwork: COMTREND Logo')
        templ = self.detector.templates[cfg['item']]
        # Same shape at two very different pixel sizes. Both must remain detectable.
        for scale in (0.65, 1.35):
            frame = np.full((300, 900, 3), 255, dtype=np.uint8)
            rs = cv2.resize(templ, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            h, w = rs.shape[:2]
            patch = cv2.cvtColor(rs, cv2.COLOR_GRAY2BGR)
            frame[80:80+h, 120:120+w] = np.minimum(frame[80:80+h, 120:120+w], patch)
            score, best_scale, _loc, _size = self.detector._best_match(frame, templ, self.detector.DEFAULT_SCALES)
            self.assertGreater(score, 0.55)
            self.assertGreater(best_scale, 0.0)

    def test_real_operator_screenshot_comtrend_shape_is_detectable(self):
        # Optional local regression fixture copied by release build; skipped in repository-only CI.
        fixture = Path('sample/operator_comtrend_camera_crop.png')
        if not fixture.exists():
            self.skipTest('operator screenshot fixture not included')
        frame = cv2.imread(str(fixture))
        templ = self.detector.templates['Artwork: COMTREND Logo']
        score, _scale, _loc, _size = self.detector._best_match(frame, templ, self.detector.DEFAULT_SCALES)
        self.assertGreaterEqual(score, 0.58)


if __name__ == '__main__':
    unittest.main()
