import unittest, json
from pathlib import Path

class V171BuildArtworkTests(unittest.TestCase):
    def test_build_spec_bundles_golden_artwork(self):
        src=Path("build.spec").read_text(encoding="utf-8")
        self.assertIn("label_tool/golden_artwork",src)

    def test_inner_artwork_is_enabled_blocking_presence_only(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))
        a=d["artwork_verification"]
        self.assertTrue(a["enabled"])
        self.assertTrue(a["blocking"])
        self.assertEqual(a["mode"],"shape_position")
        self.assertEqual(a["status"],"ENABLED_SHAPE_POSITION")

    def test_four_artwork_items_are_required(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))
        req=set(d["live"]["required_items"])
        self.assertTrue({
            "Artwork: COMTREND Logo","Artwork: Recycling Mark",
            "Artwork: CE Mark","Artwork: WEEE Mark"
        }<=req)

if __name__=="__main__":
    unittest.main()
