import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from label_tool.core.artwork_presence import ArtworkPresenceDetector, _imread_gray_unicode
from label_tool.core.production_zone_ocr import MultiFieldZoneOCR, ProductionZoneScheduler


class _FakeOCR:
    def read(self, image):
        return "DoC link: http://download.comtrend.com/DoC/GRG-4297u-TSL.html\nMade in China", []


class V174ArtworkRegisteredROITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))
        cls.detector = ArtworkPresenceDetector(cls.profile)

    def test_resources_all_resolve(self):
        status = self.detector.resource_status()
        self.assertEqual(status['missing'], [])
        self.assertTrue(status['golden_layout_loaded'])
        self.assertEqual(len(status['loaded']), 4)

    def test_unicode_space_path_image_load(self):
        src = Path(self.detector.template_paths['Artwork: COMTREND Logo'])
        with tempfile.TemporaryDirectory() as td:
            dst_dir = Path(td) / 'AI 小程式' / 'TEST TOOL'
            dst_dir.mkdir(parents=True)
            dst = dst_dir / '康全 logo.png'
            dst.write_bytes(src.read_bytes())
            img = _imread_gray_unicode(dst)
            self.assertIsNotNone(img)
            self.assertGreater(img.size, 0)

    def test_empty_requested_items_does_not_run_artwork_or_registration(self):
        d = ArtworkPresenceDetector(self.profile)
        frame = np.full((720,1280,3),255,dtype=np.uint8)
        with patch.object(d, '_normalize_label', side_effect=AssertionError('must not run')):
            rows, detections = d.evaluate(frame, [])
        self.assertEqual(rows, [])
        self.assertEqual(detections, [])

    def test_golden_layout_passes_all_inner_box_artwork_when_registered(self):
        d = ArtworkPresenceDetector(self.profile)
        golden = cv2.cvtColor(d.golden_layout, cv2.COLOR_GRAY2BGR)
        with patch.object(d, '_normalize_label', return_value=(golden, True, 1.0, np.array([[0,0],[100,0],[100,50],[0,50]]))):
            rows, _ = d.evaluate(golden)
        self.assertTrue(all(r.status == 'PASS' for r in rows), [(r.name,r.status,r.message) for r in rows])

    def test_not_aligned_is_warn_and_cannot_accumulate_ng(self):
        d = ArtworkPresenceDetector(self.profile)
        frame = np.full((720,1280,3),255,dtype=np.uint8)
        with patch.object(d, '_normalize_label', return_value=(frame, False, 0.0, None)):
            rows, _ = d.evaluate(frame, ['Artwork: CE Mark'])
        self.assertEqual(rows[0].status, 'WARN')
        self.assertEqual(rows[0].actual, '')
        self.assertEqual(rows[0].error_code, 'ART-LABEL-NOT-ALIGNED')

    def test_non_artwork_zone_does_not_invoke_artwork_detection(self):
        ocr = MultiFieldZoneOCR(self.profile, ocr_backend=_FakeOCR())
        zone_a = ProductionZoneScheduler.from_profile(self.profile).zones[0]
        frame = np.full((720,1280,3),255,dtype=np.uint8)
        with patch.object(ocr.artwork, 'evaluate', wraps=ocr.artwork.evaluate) as spy:
            ocr.analyze(frame, zone_a, {}, {}, min_sharpness=0, requested_items=['Fixed: model'])
            args = spy.call_args.args
            self.assertEqual(args[1], [])

    def test_overlay_uses_cached_registration_and_preserves_frame_size(self):
        d = ArtworkPresenceDetector(self.profile)
        frame = np.full((720,1280,3),255,dtype=np.uint8)
        before = frame.shape
        out = d.draw_alignment_overlay(frame.copy())
        self.assertEqual(out.shape, before)
        # Simulate a cached registered quadrilateral; preview must not invoke detect_label.
        with d._overlay_lock:
            d._last_alignment_box = np.array([[120,120],[1120,120],[1120,600],[120,600]],dtype=np.float32)
            d._last_alignment_score = 0.9
            import time as _time
            d._last_alignment_at = _time.time()
        with patch.object(d, '_normalize_label', side_effect=AssertionError('preview must not register')):
            out2 = d.draw_alignment_overlay(frame.copy())
        self.assertEqual(out2.shape, before)


if __name__ == '__main__':
    unittest.main()
