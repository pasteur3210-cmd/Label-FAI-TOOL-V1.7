import json
import unittest
from pathlib import Path
import cv2
import numpy as np

from label_tool.core.artwork_presence import ArtworkPresenceDetector, bundled_artwork_dir


class V173ProfileArtworkAndResources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path("label_tool/profiles")
        cls.chassis = json.loads((cls.root/"grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        cls.inner = json.loads((cls.root/"grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))

    def test_dropdown_profile_names(self):
        self.assertEqual(self.chassis["profile_name"], "Chassis Label")
        self.assertEqual(self.inner["profile_name"], "Inner Box Label")

    def test_both_profiles_enable_artwork(self):
        self.assertTrue(self.chassis["artwork_verification"]["enabled"])
        self.assertTrue(self.inner["artwork_verification"]["enabled"])

    def test_chassis_five_artworks(self):
        items=[x["item"] for x in self.chassis["artwork_verification"]["symbols"] if x.get("required")]
        self.assertEqual(items, [
            "Artwork: COMTREND Logo",
            "Artwork: Recycling Mark",
            "Artwork: RoHS Mark",
            "Artwork: CE Mark",
            "Artwork: WEEE Mark",
        ])

    def test_all_templates_resolve(self):
        for profile in [self.chassis,self.inner]:
            det=ArtworkPresenceDetector(profile)
            self.assertEqual(len(det.templates), len(det.symbols),
                             [(x["item"], x["item"] in det.templates) for x in det.symbols])

    def test_empty_requested_list_means_no_artwork(self):
        det=ArtworkPresenceDetector(self.inner)
        frame=np.full((720,1280,3),235,dtype=np.uint8)
        rows,dets=det.evaluate(frame,[])
        self.assertEqual(rows,[])
        self.assertEqual(dets,[])

    def test_none_requested_means_all_artwork(self):
        det=ArtworkPresenceDetector(self.inner)
        frame=np.full((720,1280,3),235,dtype=np.uint8)
        rows,_=det.evaluate(frame,None)
        self.assertEqual(len(rows),4)

    def test_size_is_not_judged(self):
        for profile in [self.chassis,self.inner]:
            judged=profile["artwork_verification"]["judged_dimensions"]
            self.assertFalse(judged["size"])
            self.assertTrue(judged["position"])
            self.assertTrue(judged.get("shape", True))


if __name__=="__main__":
    unittest.main()
