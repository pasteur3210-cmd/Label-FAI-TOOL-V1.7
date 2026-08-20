import unittest, json
from pathlib import Path
import numpy as np
from label_tool.core.production_zone_ocr import MultiFieldZoneOCR, ProductionZoneScheduler, DEFAULT_PRODUCTION_ZONES

class FakeOCR:
    def __init__(self,text): self.text=text; self.calls=0
    def read(self,image): self.calls+=1; return self.text,[]

class V160ZoneOCRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))

    def test_zone_a_one_ocr_evaluates_multiple_fields(self):
        text='GPON VoIP Gateway\nModel: GRG-4297u\nP/N: 738125-001\nInput 12V 1.5A\nUSB 2.0 5V 500mA\nIP: 192.168.1.1\nUsername: user'
        o=FakeOCR(text); eng=MultiFieldZoneOCR(self.profile,o); frame=np.zeros((720,1280,3),dtype=np.uint8); frame[100:600:2,100:1100:2]=255
        r=eng.analyze(frame,DEFAULT_PRODUCTION_ZONES[0],{}, {'pn':'738125-001'},min_sharpness=0)
        self.assertEqual(o.calls,1)
        passed={x.name for x in r.rows if x.status=='PASS'}
        for item in DEFAULT_PRODUCTION_ZONES[0].items:self.assertIn(item,passed)

    def test_zone_b_one_ocr_can_pass_three_fields_with_qr_truth(self):
        text='Password: 483WzX8e\nWiFi Key: MMBbgVzJUzvn8Z\nSSID: Telekom Slovenije_AFB49D'
        o=FakeOCR(text); eng=MultiFieldZoneOCR(self.profile,o); frame=np.ones((720,1280,3),dtype=np.uint8)*127
        known={'qr_wifi_key':'MMBbgVzJUzvn8Z','qr_ssid':'Telekom Slovenije_AFB49D'}
        r=eng.analyze(frame,DEFAULT_PRODUCTION_ZONES[1],known,{},min_sharpness=0)
        self.assertEqual(o.calls,1); self.assertEqual(len([x for x in r.rows if x.status=='PASS']),3)

    def test_scheduler_has_four_zones(self):
        s=ProductionZoneScheduler.from_profile(self.profile)
        self.assertEqual([z.id for z in s.zones],['A','B','C','D'])

    def test_username_label_alternation_is_grouped(self):
        from label_tool.core.direct_guided_ocr import DirectGuidedOCR
        self.assertEqual(DirectGuidedOCR._extract_labeled_value("USERNAME: user", r"USER\s*NAME|USERNAME", r"[A-Za-z0-9_-]+"), "user")
        self.assertEqual(DirectGuidedOCR._extract_labeled_value("USER NAME: user", r"USER\s*NAME|USERNAME", r"[A-Za-z0-9_-]+"), "user")

if __name__=='__main__': unittest.main()
