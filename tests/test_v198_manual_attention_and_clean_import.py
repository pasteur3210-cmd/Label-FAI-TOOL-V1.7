import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from label_tool.core.golden_profile_manager import build_dynamic_profile
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult, ImageEvidence


def make_docx(path: Path, model='VG-8043u', pn='680010-375', image_name='golden.png', image_bytes=b'PNGDATA'):
    text=(f'Chassis Label Request Form\nPAK Name: {model}-CTU-P1\n'
          '1. Comtrend Logo：■ Yes □ No\n'
          '2. Model Name (必填)：■ (康全) '+model+' □ (客戶) PRT-7302\n'
          '3. QR Code：含 SN、MAC、WiFi Key\n'
          f'Chassis Label Part Number：{pn}\n')
    paras=''.join(f'<w:p><w:r><w:t>{line}</w:t></w:r></w:p>' for line in text.splitlines())
    xml=('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
         f'<w:body>{paras}</w:body></w:document>')
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('word/document.xml',xml)
        z.writestr('word/media/'+image_name,image_bytes)


class V198Tests(unittest.TestCase):
    def test_all_nonpass_items_have_attention_mode(self):
        self.assertEqual(MultiImageInspectionEngine.manual_attention_mode('Artwork: WEEE Mark'),'OVERRIDE_ALLOWED')
        self.assertEqual(MultiImageInspectionEngine.manual_attention_mode('Fixed: model'),'OVERRIDE_ALLOWED')
        self.assertEqual(MultiImageInspectionEngine.manual_attention_mode('Variable: MAC Barcode Format'),'OVERRIDE_ALLOWED')
        self.assertEqual(MultiImageInspectionEngine.manual_attention_mode('Consistency: MAC Text vs Barcode'),'OVERRIDE_ALLOWED')

    def test_review_only_action_is_logged_without_overriding_auto(self):
        profile={'live':{'required_items':['Variable: MAC Barcode Format']}}
        eng=MultiImageInspectionEngine(profile,software_version='1.9.8')
        with tempfile.TemporaryDirectory() as td:
            r=MultiImageResult(session_id='t',session_dir=td,automatic_overall='FAIL',overall='FAIL')
            r.evidence['Variable: MAC Barcode Format']=ImageEvidence(item='Variable: MAC Barcode Format',result='FAIL',actual='BAD',expected='12 HEX')
            eng._write_excel=lambda result,expected: str(Path(td)/'report.xlsx')
            out=eng.record_manual_review_action(r,'Variable: MAC Barcode Format','CONFIRM_FAIL','operator checked')
            self.assertEqual(out.evidence['Variable: MAC Barcode Format'].result,'FAIL')
            self.assertEqual(out.manual_reviews[-1]['mode'],'OVERRIDE_ALLOWED')
            self.assertEqual(out.manual_reviews[-1]['action'],'CONFIRM_FAIL')
            data=json.loads((Path(td)/'result.json').read_text(encoding='utf-8'))
            self.assertEqual(data['manual_reviews'][-1]['item'],'Variable: MAC Barcode Format')

    def test_reimport_same_identity_replaces_stale_golden_assets(self):
        with tempfile.TemporaryDirectory() as td:
            ext=Path(td)/'profiles'; ext.mkdir()
            doc=Path(td)/'golden.docx'
            make_docx(doc,image_name='new.png',image_bytes=b'NEW')
            seed={'live':{},'image_inspection':{},'image_quality':{},'vision':{}}
            with patch('label_tool.core.golden_profile_manager.external_profile_dir',lambda:ext), \
                 patch('label_tool.core.golden_profile_manager._ocr_golden_images',lambda imgs:('',[])):
                out,p=build_dynamic_profile(str(doc),seed)
                asset=Path(p['golden_import']['asset_dir'])
                (asset/'imported_media'/'stale_old.png').write_bytes(b'OLD')
                # same identity re-import must remove stale_old.png instead of merging directories
                out2,p2=build_dynamic_profile(str(doc),seed)
                files={x.name for x in (Path(p2['golden_import']['asset_dir'])/'imported_media').iterdir()}
                self.assertTrue(any(x.endswith('new.png') for x in files))
                self.assertNotIn('stale_old.png',files)
                self.assertEqual(out,out2)

    def test_app_source_lists_every_nonpass_not_only_override_allowed(self):
        app=(Path(__file__).resolve().parents[1]/'label_tool'/'app.py').read_text(encoding='utf-8')
        self.assertIn('mode=self.multi_image_engine.manual_attention_mode(item)',app)
        # Old filter would hide REVIEW_ONLY items; it must not return.
        self.assertNotIn('if self.multi_image_engine._manual_review_allowed(item):\n                candidates.append',app)
        self.assertIn('REVIEW ONLY',app)
        self.assertIn('Golden Reference / Golden 對照',app)

if __name__=='__main__':
    unittest.main()
