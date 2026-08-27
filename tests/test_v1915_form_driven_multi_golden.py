import tempfile
import unittest
import zipfile
from pathlib import Path

from label_tool.core.golden_profile_manager import (
    _rules_from_golden_text,
    _extract_docx,
    _docx_final_label_media_names,
    extract_golden_form_items,
    select_final_label_image,
)


GRG4297 = '''
Chassis Label Request Form
Label Request:
1. Comtrend logo
2. GPON VoIP Gateway
3. Model: GRG-4297u
4. P/N: 738125-00X
5. Input: 12V 1.5A
USB 2.0: 5V 500mA
6. IP Address: 192.168.1.1
7. Username: user
8. Password: Random 8 characters
詳細規則如下
1. nested password rule must remain under item 8
2. another nested rule
9. SSID=Telekom Slovenije_XXXXXX
10. WiFi Key: Random 14 碼
Barcode type：QR Code
QR Code內容: WIFI:T:WPA;S:SSID;P:WiFi Key;;
11. S/N: YYM4297UF-FFXXXXXX (18 characters)
Barcode type：Code 128
12. MAC: Comtrend mac address (一台10個MAC)
Barcode type：Code 128
13. GPON S/N: 434D5444XXXXXXXX (16 characters)
Barcode type：Code 128
14. Made in China/Taiwan
15. Comtrend Central Europe, s.r.o.
16. 安規Logo：
17.
18. 以上所有密碼規則說明，依據業務信件內附件
19. QR Code for 測試刷入使用，內容含 SN、MAC、Password、WiFi Key
20. 匯入列印方式參考
Finished Information:
'''

GRG4366 = '''
Label Request:
1. Comtrend Logo： ■ Yes □ No
2. FCC Mark：■ Yes □ No
3. WEEE Mark： ■ Yes □ No
4. CE Mark： □ Yes ■ No
5. Product (必填)：Home Gateway
6. Model Name (必填)： □ (康全) GRG-4366u ■ (客戶) GRG-4366
7. Part No.：■ Yes, 7XXXXX-XXX □ No
8. Input：12 VDC 3A
9. USB 3.0: 5V 900mA
10. S/N Number (including Barcode)：■ Comtrend (20 碼) □ Customer
Barcode Type：Code type：128 Checking code：1
11. MAC Number (including Bar code)：■ Yes □ No
Barcode Type：Code type：128 Checking code：1
12. GPON SN：CMTD + MAC 後八碼
Barcode type：Code type：128 Checking code：1
13. SSID ComtrendXXXX_2.4GHz = Comtrend + last 4 characters of MAC address_2.4GHz
14. Encryption Type = WPA2-PSK
15. WiFi Key: Random 10 digits
16. Made in Taiwan/China
17. Add IC mark
18. Add UL file listing number E203979
19. Add FCC ID: L9VGRG4366 IC ID: 4013A-GRG4366
20. QR Code：含 SN、MAC、WiFi Key for 測試刷入使用
Finished Information:
'''


class TestFormDrivenMultiGolden(unittest.TestCase):
    def test_4297_top_level_sequence_survives_nested_numbers_and_blank_item(self):
        rows = extract_golden_form_items(GRG4297)
        self.assertEqual([r['form_no'] for r in rows], list(range(1, 21)))
        self.assertIn('nested password rule', rows[7]['raw_text'])
        self.assertEqual(rows[9]['type'], 'Golden Variable')
        self.assertEqual(rows[9]['machine_code_field'], 'qr')
        self.assertIn('Variable: WiFi Key Format', rows[9]['engine_items'])
        self.assertTrue(rows[9]['presence_item'])
        self.assertEqual(rows[10]['machine_code_field'], 'sn')
        self.assertEqual(rows[11]['machine_code_field'], 'mac')
        self.assertEqual(rows[12]['machine_code_field'], 'gpon_sn')
        self.assertEqual(rows[15]['type'], 'Golden Artwork')
        self.assertEqual(rows[16]['type'], 'Needs Review')  # blank #17 retained
        self.assertEqual(rows[18]['type'], 'Golden QR')
        self.assertFalse(rows[18]['machine_code_rule_known'])  # Password => manual review
        self.assertEqual(rows[18]['engine_items'], [])


    def test_4297_field_safe_barcode_rules(self):
        from label_tool.core.parser import parse_decoded_fields
        rules = _rules_from_golden_text(GRG4297)
        self.assertEqual(rules.get('gpon_prefix'), '434D5444')
        self.assertIn('{18}', rules.get('sn_regex',''))
        profile={'dynamic_profile':True,'rules':rules}
        fields=parse_decoded_fields(['434D544499AFB49D'],profile=profile)
        self.assertEqual(fields.get('gpon_sn_barcode'),'434D544499AFB49D')
        self.assertNotIn('sn_barcode',fields)

    def test_4366_checkbox_and_machine_codes(self):
        rows = extract_golden_form_items(GRG4366)
        self.assertEqual([r['form_no'] for r in rows], list(range(1, 21)))
        self.assertTrue(rows[0]['required'])
        self.assertFalse(rows[3]['required'])  # CE selected No
        self.assertEqual(rows[9]['machine_code_field'], 'sn')
        self.assertEqual(rows[10]['machine_code_field'], 'mac')
        self.assertEqual(rows[11]['machine_code_field'], 'gpon_sn')
        self.assertEqual(rows[19]['type'], 'Golden QR')
        self.assertTrue(rows[19]['machine_code_rule_known'])

    def test_structural_word_numbering_and_final_label_marker(self):
        # Minimal DOCX where visible 1/2 are stored only in w:numPr, and the
        # final image is referenced after the Label Example marker.
        doc_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <w:body>
            <w:p><w:r><w:t>Label Request:</w:t></w:r></w:p>
            <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr></w:pPr><w:r><w:t>Comtrend logo</w:t></w:r></w:p>
            <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr></w:pPr><w:r><w:t>MAC: Comtrend mac address</w:t></w:r></w:p>
            <w:p><w:r><w:t>Label Example:</w:t></w:r></w:p>
            <w:p><w:r><w:drawing><a:blip r:embed="rId9"/></w:drawing></w:r></w:p>
          </w:body></w:document>'''
        rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
          <Relationship Id="rId9" Type="x" Target="media/final.png"/>
        </Relationships>'''
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            docx = td / 'x.docx'
            with zipfile.ZipFile(docx, 'w') as z:
                z.writestr('word/document.xml', doc_xml)
                z.writestr('word/_rels/document.xml.rels', rels)
                z.writestr('word/media/final.png', b'fake')
            out = td / 'out'
            text, images = _extract_docx(docx, out)
            self.assertIn('1. Comtrend logo', text)
            self.assertIn('2. MAC: Comtrend mac address', text)
            self.assertEqual(_docx_final_label_media_names(docx), ['final.png'])
            # Structural preference must win even with no OCR runtime.
            best, score, reason = select_final_label_image(images, [], [], ['final.png'])
            self.assertIsNotNone(best)
            self.assertGreater(score, 50)
            self.assertIn('Label Example', reason)


if __name__ == '__main__':
    unittest.main()
