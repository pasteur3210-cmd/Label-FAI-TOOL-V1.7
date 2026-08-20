import unittest, json
from pathlib import Path
from label_tool.core.direct_guided_ocr import targets_from_profile

class V171ManualTargetFilterTests(unittest.TestCase):
    def test_inner_manual_targets_exclude_ssid_and_wifi(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))
        names={t.item for t in targets_from_profile(d)}
        self.assertNotIn("Variable: SSID Format",names)
        self.assertNotIn("Variable: Password Format",names)
        self.assertNotIn("Variable: WiFi Key Format",names)
        self.assertIn("Fixed: DoC Link",names)

if __name__=="__main__":
    unittest.main()
