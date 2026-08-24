import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, ImageEvidence

class _FakeQuality:
    sharpness=200.0; contrast=60.0; passed=True

class V177MultiImageTests(unittest.TestCase):
    def setUp(self):
        self.profile=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1_inner_box.json').read_text(encoding='utf-8'))
        self.eng=MultiImageInspectionEngine(self.profile,'1.7.7')

    def test_better_pass_beats_unresolved(self):
        old=ImageEvidence('x','NEED_MORE_IMAGE',quality_score=.9)
        new=ImageEvidence('x','PASS',quality_score=.4)
        self.assertTrue(self.eng._better(new,old))

    def test_quality_fail_empty_value_is_need_more_image(self):
        from label_tool.core.models import FieldResult
        r=FieldResult(name='x',actual='',expected='y',status='FAIL')
        self.assertEqual(self.eng._classify_field(r,True),'NEED_MORE_IMAGE')

    def test_identity_items_are_unique_keys(self):
        from label_tool.core.multi_image_inspection import IDENTITY_ITEMS
        self.assertEqual(len(set(IDENTITY_ITEMS.values())),3)

    def test_required_contains_artwork(self):
        req=self.eng._required_items()
        self.assertIn('Artwork: COMTREND Logo',req)
        self.assertIn('Artwork: CE Mark',req)

    def test_excel_writer_smoke(self):
        from label_tool.core.multi_image_inspection import MultiImageResult
        with tempfile.TemporaryDirectory() as td:
            r=MultiImageResult(overall='NEED_MORE_IMAGE',session_id='test',session_dir=td,image_count=2,initial_image_count=2)
            r.unresolved_items=['Artwork: COMTREND Logo']
            p=self.eng._write_excel(r,{})
            self.assertTrue(Path(p).exists())

if __name__=='__main__': unittest.main()

class _FakeQ:
    passed=True; sharpness=180.0; contrast=50.0
class _FakeOne:
    quality=_FakeQ(); overall='PASS'; error_codes=[]

class _FusionEngine(MultiImageInspectionEngine):
    def _required_items(self):
        return ['Variable: S/N Barcode Format','Artwork: COMTREND Logo','Artwork: CE Mark']
    def _inspect_one(self,image_path,session_dir,expected,index):
        name=Path(image_path).name
        if 'one' in name:
            obs=[
              ImageEvidence('Variable: S/N Barcode Format','PASS','SN001','SN','one.jpg',.8,'',''),
              ImageEvidence('Artwork: COMTREND Logo','PASS','Shape+Position PASS','ok','one.jpg',.8,'',''),
              ImageEvidence('Artwork: CE Mark','NEED_MORE_IMAGE','','ok','one.jpg',.2,'blur',''),
            ]
        else:
            obs=[
              ImageEvidence('Variable: S/N Barcode Format','PASS','SN001','SN','two.jpg',.9,'',''),
              ImageEvidence('Artwork: CE Mark','PASS','Shape+Position PASS','ok','two.jpg',.9,'',''),
            ]
        return _FakeOne(),obs

class V177BatchFusionFlowTests(unittest.TestCase):
    def test_initial_batch_fuses_complementary_images_and_writes_logs(self):
        profile={'profile_name':'Test','live':{'required_items':[]}}
        eng=_FusionEngine(profile,'1.7.7')
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'one.jpg'; b=Path(td)/'two.jpg'; a.write_bytes(b'a'); b.write_bytes(b'b')
            r=eng.inspect_batch([str(a),str(b)],Path(td)/'out',{})
            self.assertEqual(r.overall,'PASS')
            self.assertEqual(r.identity_status,'PASS')
            self.assertEqual(r.evidence['Artwork: COMTREND Logo'].source_image,'one.jpg')
            self.assertEqual(r.evidence['Artwork: CE Mark'].source_image,'two.jpg')
            for f in ['execution.log','test.log','debug.log','result.json']:
                self.assertTrue((Path(r.session_dir)/f).exists(),f)
            self.assertTrue(Path(r.report_path).exists())

    def test_additional_image_recheck_resolves_unresolved(self):
        class _Step(_FusionEngine):
            def _inspect_one(self,image_path,session_dir,expected,index):
                name=Path(image_path).name
                if 'one' in name:
                    return _FakeOne(),[
                      ImageEvidence('Variable: S/N Barcode Format','PASS','SN001','SN',name,.8,'',''),
                      ImageEvidence('Artwork: COMTREND Logo','PASS','Shape+Position PASS','ok',name,.8,'',''),
                      ImageEvidence('Artwork: CE Mark','NEED_MORE_IMAGE','','ok',name,.2,'blur','')]
                return _FakeOne(),[
                  ImageEvidence('Variable: S/N Barcode Format','PASS','SN001','SN',name,.9,'',''),
                  ImageEvidence('Artwork: CE Mark','PASS','Shape+Position PASS','ok',name,.9,'','')]
        eng=_Step({'profile_name':'Test','live':{'required_items':[]}},'1.7.7')
        with tempfile.TemporaryDirectory() as td:
            a=Path(td)/'one.jpg'; b=Path(td)/'two.jpg'; a.write_bytes(b'a'); b.write_bytes(b'b')
            r1=eng.inspect_batch([str(a)],Path(td)/'out',{})
            self.assertEqual(r1.overall,'NEED_MORE_IMAGE')
            r2=eng.inspect_batch([str(b)],Path(td)/'out',{},previous_session=r1)
            self.assertEqual(r2.overall,'PASS')
            self.assertEqual(r2.additional_image_count,1)
