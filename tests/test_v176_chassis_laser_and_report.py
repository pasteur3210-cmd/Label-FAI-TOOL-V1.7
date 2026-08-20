import json, unittest
from pathlib import Path
from label_tool.core.production_zone_ocr import MultiFieldZoneOCR
from label_tool.core.inspection_report import create_inspection_report

class V176ChassisLaserAndReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))

    def test_chassis_has_normalized_laser_target(self):
        targets=self.profile['live'].get('normalized_text_targets',[])
        laser=next(x for x in targets if x['item']=='Fixed: CLASS 1 LASER PRODUCT')
        self.assertEqual(laser['expected'],'CLASS 1 LASER PRODUCT')
        self.assertLessEqual(float(laser['threshold']),0.80)
        self.assertEqual(len(laser['target_rect']),4)

    def test_inner_box_does_not_enable_laser_target(self):
        p=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))
        self.assertFalse(p.get('live',{}).get('normalized_text_targets'))

    def test_report_accepts_incomplete_chassis_session(self):
        out=Path('test_v176_incomplete_report.xlsx')
        payload={
          'overall':'INCOMPLETE','software_version':'1.7.6.1','profile':'Chassis Label',
          'model':'GRG-4297u','label_type':'Chassis Label','label_pn':'680010-378',
          'spec_version':'V3.0','source_spec':'test','session_id':'TEST','started_at':'2026-08-20T18:00:00',
          'completed_at':'2026-08-20T18:01:00','elapsed_sec':60,'locked_count':31,'required_count':32,
          'work_order':{'pn':'738125-001','made_in':'China'},
          'locks':{'Fixed: CLASS 1 LASER PRODUCT':{'state':'LOCK','locked_value':'Present','last_message':'Normalized-label OCR similarity=0.95'},
                   'Artwork: COMTREND Logo':{'state':'SCANNING','locked_value':'','last_message':'VERIFY'}},
          'expected_map':{},'zone_stats':{},'unlocked_items':['Artwork: COMTREND Logo'],'confirmed_fail_items':[]
        }
        try:
            create_inspection_report(out,payload)
            self.assertTrue(out.exists() and out.stat().st_size>1000)
        finally:
            if out.exists(): out.unlink()

if __name__=='__main__': unittest.main()
