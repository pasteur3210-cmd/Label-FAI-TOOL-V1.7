import unittest, json
from pathlib import Path
from label_tool.core.rules import validate

class V171ProfileAwareRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inner=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1_inner_box.json").read_text(encoding="utf-8"))

    def test_inner_box_validate_has_no_ssid_prefix_keyerror(self):
        fields={
            "sn_text":"2654297UF-AA000029","sn_barcode":"2654297UF-AA000029",
            "mac_text":"1C6A99AFB4A7","mac_barcode":"1C6A99AFB4A7",
            "gpon_sn_text":"434D544499AFB4A7","gpon_sn_barcode":"434D544499AFB4A7",
            "mac":"1C6A99AFB4A7","gpon_sn":"434D544499AFB4A7",
            "pn":"738125-001","made_in":"China","model":"GRG-4297u",
            "has_gateway_text":True,
        }
        rows=validate(fields,self.inner,{"pn":"738125-001","made_in":"China"})
        names={r.name for r in rows}
        self.assertNotIn("Variable: SSID Format",names)
        self.assertNotIn("Rule: SSID = MAC Last 6",names)
        self.assertNotIn("Variable: Password Format",names)
        self.assertNotIn("Variable: WiFi QR Format",names)
        self.assertIn("Rule: GPON S/N = Prefix + MAC Last 8",names)

    def test_inner_box_required_items_have_no_wifi_rules(self):
        req=set(self.inner["live"]["required_items"])
        self.assertNotIn("Rule: SSID = MAC Last 6",req)
        self.assertNotIn("Consistency: QR SSID vs Printed SSID",req)
        self.assertNotIn("Consistency: QR Key vs Printed WiFi Key",req)

if __name__=="__main__":
    unittest.main()
