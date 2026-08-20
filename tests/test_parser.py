import unittest
from label_tool.core.parser import parse_fields

class ParserTests(unittest.TestCase):
    def test_variable_actual_values_from_ocr_and_barcode(self):
        text="""GPON VoIP Gateway Model: GRG-4297u P/N: 738125-001 Input: 12V 1.5A USB 2.0: 5V 500mA
        IP address: 192.168.1.1 Username: user Password: 483WzX8e WiFi Key: MMBbgVzJUrvn8Z
        SSID: Telekom Slovenije_AFB49D S/N: 2644297UF-AA000028 MAC: 1C6A99AFB49D
        GPON S/N: 434D544499AFB49D Made in China Comtrend Central Europe, s.r.o. Jankovcova 1518/2
        CLASS 1 LASER PRODUCT"""
        decoded=["2644297UF-AA000028","1C6A99AFB49D","434D544499AFB49D",
        "WIFI:T:WPA;S:Telekom Slovenije_AFB49D;P:MMBbgVzJUrvn8Z;;"]
        f=parse_fields(text,decoded)
        self.assertEqual(f["sn"],"2644297UF-AA000028")
        self.assertEqual(f["mac"],"1C6A99AFB49D")
        self.assertEqual(f["gpon_sn"],"434D544499AFB49D")
        self.assertEqual(f["qr_ssid"],"Telekom Slovenije_AFB49D")

    def test_roi_text_priority(self):
        f=parse_fields("noise",[],{"sn_text":"S/N: 2644297UF-AA999999"})
        self.assertEqual(f["sn_text"],"2644297UF-AA999999")

if __name__=="__main__": unittest.main()
