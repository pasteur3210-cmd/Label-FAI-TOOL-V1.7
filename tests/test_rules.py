import unittest
from label_tool.core.rules import validate, overall_status

PROFILE = {
    "fixed_fields": {"model":"GRG-4297u", "ip":"192.168.1.1", "username":"user"},
    "rules": {
        "pn_regex": r"738125-00\d", "pn_display":"738125-00X",
        "sn_regex": r"\d{2}[1-9A-C]4297UF-[A-Z0-9]{2}\d{6}",
        "sn_display":"YYM4297UF-FFXXXXXX (18 chars)",
        "mac_regex": r"[0-9A-F]{12}",
        "gpon_regex": r"434D5444[0-9A-F]{8}",
        "ssid_prefix":"Telekom Slovenije_", "gpon_prefix":"434D5444",
        "password_length":8, "wifi_key_length":14,
        "made_in_allowed":["China","Taiwan"]
    }
}

def good():
    return {
        "model":"GRG-4297u", "ip":"192.168.1.1", "username":"user",
        "has_gateway_text":True, "has_input_text":True, "has_usb_text":True,
        "has_comtrend_address":True, "has_laser_text":True,
        "pn":"738125-001", "made_in":"China",
        "sn_text":"2644297UF-AA000028", "sn_barcode":"2644297UF-AA000028", "sn":"2644297UF-AA000028",
        "mac_text":"1C6A99AFB49D", "mac_barcode":"1C6A99AFB49D", "mac":"1C6A99AFB49D",
        "gpon_sn_text":"434D544499AFB49D", "gpon_sn_barcode":"434D544499AFB49D", "gpon_sn":"434D544499AFB49D",
        "ssid":"Telekom Slovenije_AFB49D", "password":"483WzX8e", "wifi_key":"MMBbgVzJUrvn8Z",
        "wifi_qr":"WIFI:T:WPA;S:Telekom Slovenije_AFB49D;P:MMBbgVzJUrvn8Z;;",
        "qr_ssid":"Telekom Slovenije_AFB49D", "qr_wifi_key":"MMBbgVzJUrvn8Z"
    }

class RuleTests(unittest.TestCase):
    def test_good_no_fail(self):
        rr=validate(good(),PROFILE)
        self.assertFalse(any(x.status=="FAIL" for x in rr))

    def test_fixed_value_compares_to_spec(self):
        f=good(); f["model"]="WRONG"
        rr=validate(f,PROFILE)
        self.assertTrue(any(x.name=="Fixed: model" and x.status=="FAIL" for x in rr))

    def test_variable_sn_checks_format_not_spec_sample(self):
        f=good(); f["sn_text"]="2644297UF-AA123456"; f["sn_barcode"]="2644297UF-AA123456"; f["sn"]=f["sn_barcode"]
        rr=validate(f,PROFILE)
        self.assertTrue(any(x.name=="Variable: S/N Human Readable Format" and x.status=="PASS" for x in rr))

    def test_bad_variable_sn_format_fails(self):
        f=good(); f["sn_text"]="BADSN"; f["sn_barcode"]="BADSN"; f["sn"]="BADSN"
        rr=validate(f,PROFILE)
        self.assertTrue(any(x.name=="Variable: S/N Human Readable Format" and x.status=="FAIL" for x in rr))

    def test_ssid_relation(self):
        f=good(); f["ssid"]="Telekom Slovenije_000000"
        rr=validate(f,PROFILE)
        self.assertTrue(any(x.name=="Rule: SSID = MAC Last 6" and x.status=="FAIL" for x in rr))

    def test_gpon_relation(self):
        f=good(); f["gpon_sn"]="434D544400000000"
        rr=validate(f,PROFILE)
        self.assertTrue(any(x.name=="Rule: GPON S/N = Prefix + MAC Last 8" and x.status=="FAIL" for x in rr))

    def test_missing_actual_is_warn_not_false_fail(self):
        f=good(); f["made_in"]=""
        rr=validate(f,PROFILE,{"made_in":"China"})
        self.assertFalse(any(x.name=="Variable: Made in Format" and x.status=="FAIL" for x in rr))

    def test_image_gate_overrides(self):
        self.assertEqual(overall_status(validate(good(),PROFILE),False),"IMAGE_NG")

if __name__=="__main__": unittest.main()
