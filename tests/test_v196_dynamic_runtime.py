import unittest
from pathlib import Path

from label_tool.core.parser import merge_fields
from label_tool.core.rules import validate
from label_tool.core.profile_manager import _display_name
from label_tool.core.golden_profile_manager import _rules_from_golden_text


class DynamicRuntimeV196Tests(unittest.TestCase):
    def setUp(self):
        golden = '''
12. SSID
ComtrendXXXX
XXXX= last 4 digits of MAC
13. Encryption Type = WPA3 Transition
14. WiFi Key: Random 10 digits
15. Made in Taiwan/China
19. QR Code：含 SN、MAC、WiFi Key for 測試刷入使用
10. S/N Number (including Barcode)：■ Comtrend (20 碼) □ Customer
'''
        rules = _rules_from_golden_text(golden)
        self.profile = {
            'dynamic_profile': True,
            'model': 'VG-8043u',
            'model_aliases': ['VG-8043u', 'PRT-7302'],
            'fixed_fields': {'model': 'VG-8043u'},
            'rules': rules,
            'live': {'required_items': [
                'Fixed: model','Variable: P/N Format',
                'Variable: S/N Human Readable Format','Variable: S/N Barcode Format','Consistency: S/N Text vs Barcode',
                'Variable: MAC Human Readable Format','Variable: MAC Barcode Format','Consistency: MAC Text vs Barcode',
                'Variable: SSID Format','Variable: WiFi Key Format','Variable: WiFi QR Format','Variable: Made in Format',
            ]},
        }

    def test_golden_rules_from_controlled_form(self):
        r=self.profile['rules']
        self.assertEqual(r['wifi_key_length'],10)
        self.assertEqual(r['ssid_prefix'],'Comtrend')
        self.assertEqual(r['ssid_mac_suffix_length'],4)
        self.assertEqual(r['qr_payload_fields'],['sn','mac','wifi_key'])
        self.assertEqual(r['sn_regex'],'[A-Z0-9-]{20}')
        self.assertEqual(set(r['made_in_allowed']),{'China','Taiwan'})

    def test_dynamic_parser_not_hardcoded_to_grg4297(self):
        ocr=('COMTREND Home Gateway Model: PRT-7302 P/N: 740114-001 '
             'Input: 12VDC 3A USB 3.0: 5V 900mA Encryption Type = WPA3 Transition '
             'WiFi Key: KAG7dcsyJ7 SSID: Comtrend8609 '
             'S/N: 2638043UXXF-AN000038 MAC: A01842EA8609 Made in Taiwan')
        decoded=[
            'S/N: 2638043UXXF-AN000038MAC: A01842EA8609WPA: KAG7dcsyJ7',
            '2638043UXXF-AN000038','A01842EA8609','A018426A8627'
        ]
        f=merge_fields(ocr,decoded,profile=self.profile)
        self.assertEqual(f['model'],'PRT-7302')
        self.assertEqual(f['pn'],'740114-001')
        self.assertEqual(f['sn_text'],'2638043UXXF-AN000038')
        self.assertEqual(f['sn_barcode'],'2638043UXXF-AN000038')
        self.assertEqual(f['mac_text'],'A01842EA8609')
        # Important field-record regression: reject the spurious second decode.
        self.assertEqual(f['mac_barcode'],'A01842EA8609')
        self.assertEqual(f['qr_wifi_key'],'KAG7dcsyJ7')

    def test_dynamic_rules_validate_field_record(self):
        self.profile['rules']['pn_regex']=r'[0-9A-Z-]{5,32}'
        self.profile['rules']['pn_display']='Golden P/N format'
        f=merge_fields(
            'Model: PRT-7302 P/N: 740114-001 WiFi Key: KAG7dcsyJ7 SSID: Comtrend8609 '
            'S/N: 2638043UXXF-AN000038 MAC: A01842EA8609 Made in Taiwan',
            ['S/N: 2638043UXXF-AN000038MAC: A01842EA8609WPA: KAG7dcsyJ7',
             '2638043UXXF-AN000038','A01842EA8609','A018426A8627'],
            profile=self.profile)
        rows={x.name:x for x in validate(f,self.profile,{'pn':'740114-001','made_in':'Taiwan'})}
        for name in ('Fixed: model','Variable: P/N Format','Variable: S/N Human Readable Format',
                     'Variable: S/N Barcode Format','Consistency: S/N Text vs Barcode',
                     'Variable: MAC Human Readable Format','Variable: MAC Barcode Format',
                     'Consistency: MAC Text vs Barcode','Variable: SSID Format',
                     'Variable: WiFi Key Format','Variable: WiFi QR Format'):
            self.assertEqual(rows[name].status,'PASS',name)

    def test_dynamic_profiles_use_unique_ui_key(self):
        a={'profile_name':'VG-8043u Chassis Label','dynamic_profile':True,'label_pn':'680010-367'}
        b={'profile_name':'VG-8043u Chassis Label','dynamic_profile':True,'label_pn':'680010-375'}
        self.assertNotEqual(_display_name(a,Path('a.json')),_display_name(b,Path('b.json')))
        self.assertIn('680010-375',_display_name(b,Path('b.json')))


if __name__ == '__main__':
    unittest.main()
