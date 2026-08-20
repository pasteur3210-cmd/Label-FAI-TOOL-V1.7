import unittest
from pathlib import Path

class V170ProfileTargetArchitectureTests(unittest.TestCase):
    def test_app_scheduler_uses_profile_targets(self):
        src=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn("GuidedItemScheduler(targets_from_profile(data))",src)

    def test_zone_ocr_uses_profile_target_map(self):
        src=Path("label_tool/core/production_zone_ocr.py").read_text(encoding="utf-8")
        self.assertIn("targets_from_profile(profile)",src)
        self.assertIn("self._target_by_item.get(item)",src)

    def test_report_contains_label_type_and_artwork_status(self):
        src=Path("label_tool/core/inspection_report.py").read_text(encoding="utf-8")
        self.assertIn('"Label Type"',src)
        self.assertIn('"Artwork Verification"',src)
        self.assertIn('"Source Spec"',src)

if __name__=="__main__":
    unittest.main()
