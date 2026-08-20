import json
import unittest
from pathlib import Path
import numpy as np
from label_tool.core.production_zone_ocr import MultiFieldZoneOCR, ProductionZoneScheduler


class _FakeOCR:
    def read(self, image):
        return "CLASS 1 LASER PRODUCT", []


class V1761FieldResultRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))

    def _make(self, aligned=True, min_sharpness=0):
        profile = json.loads(json.dumps(self.profile))
        for cfg in profile['live'].get('normalized_text_targets', []):
            if cfg.get('item') == 'Fixed: CLASS 1 LASER PRODUCT':
                cfg['min_sharpness'] = min_sharpness
                cfg['threshold'] = 0.5
        ocr = MultiFieldZoneOCR(profile, ocr_backend=_FakeOCR())
        frame = np.full((720, 1280, 3), 240, dtype=np.uint8)
        ocr.artwork._normalize_label = lambda f: (f, aligned, 1.0 if aligned else 0.2, (0, 0, f.shape[1], f.shape[0]))
        zone = next(z for z in ProductionZoneScheduler.from_profile(profile).zones if 'Fixed: CLASS 1 LASER PRODUCT' in z.items)
        return ocr, frame, zone

    def test_normalized_target_not_aligned_branch_uses_fieldresult(self):
        ocr, frame, zone = self._make(aligned=False, min_sharpness=0)
        result = ocr.analyze(frame, zone, {}, {'made_in': 'China'}, min_sharpness=0,
                             requested_items=['Fixed: CLASS 1 LASER PRODUCT'])
        row = next(r for r in result.rows if r.name == 'Fixed: CLASS 1 LASER PRODUCT')
        self.assertEqual(row.status, 'WARN')
        self.assertEqual(row.error_code, 'TXT-LABEL-NOT-ALIGNED')

    def test_normalized_target_blur_branch_uses_fieldresult(self):
        ocr, frame, zone = self._make(aligned=True, min_sharpness=999999)
        result = ocr.analyze(frame, zone, {}, {'made_in': 'China'}, min_sharpness=0,
                             requested_items=['Fixed: CLASS 1 LASER PRODUCT'])
        row = next(r for r in result.rows if r.name == 'Fixed: CLASS 1 LASER PRODUCT')
        self.assertEqual(row.status, 'WARN')
        self.assertEqual(row.error_code, 'TXT-TARGET-BLUR')

    def test_normalized_target_ocr_branch_uses_fieldresult(self):
        ocr, frame, zone = self._make(aligned=True, min_sharpness=0)
        result = ocr.analyze(frame, zone, {}, {'made_in': 'China'}, min_sharpness=0,
                             requested_items=['Fixed: CLASS 1 LASER PRODUCT'])
        row = next(r for r in result.rows if r.name == 'Fixed: CLASS 1 LASER PRODUCT')
        self.assertEqual(row.status, 'PASS')
        self.assertIn('Normalized-label OCR similarity=', row.message)


if __name__ == '__main__':
    unittest.main()
