import unittest, json
from pathlib import Path

class ProfileTests(unittest.TestCase):
    def test_profile_v171(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertEqual(d["profile_version"],"1.8.2")
        self.assertIn("rois",d)
        self.assertIn("sn_barcode",d["rois"])
        self.assertEqual(d["rules"]["pn_display"],"738125-00X")
        self.assertIn("live",d)
        self.assertEqual(d["live"]["pass_confirmations"],2)
        self.assertEqual(d["live"]["fail_confirmations"],3)

if __name__=="__main__": unittest.main()
