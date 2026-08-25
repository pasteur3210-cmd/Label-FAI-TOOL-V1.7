import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from label_tool.core.golden_profile_manager import _extract_docx, _fixed_text_candidates, validate_profile_structure
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine


def _make_docx(path: Path):
    xml='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>680010-305 GRG-4355u-DIG-P1 Chassis Label</w:t></w:r></w:p>
<w:p><w:r><w:t>GPON VoIP Gateway</w:t></w:r></w:p>
<w:p><w:r><w:t>CLASS 1 LASER PRODUCT</w:t></w:r></w:p>
<w:p><w:r><w:t>https://example.com/DoC/GRG-4355u.html</w:t></w:r></w:p>
</w:body></w:document>'''
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
        z.writestr('word/document.xml',xml)
        z.writestr('word/media/image1.png',b'PNGDATA')


def test_docx_text_and_media_extraction(tmp_path):
    src=tmp_path/'golden.docx'; _make_docx(src)
    text,images=_extract_docx(src,tmp_path/'assets')
    assert 'GRG-4355u' in text
    assert 'GPON VoIP Gateway' in text
    assert len(images)==1 and images[0].exists()


def test_fixed_text_candidates_are_profile_data():
    rows=_fixed_text_candidates('GPON VoIP Gateway\nCLASS 1 LASER PRODUCT\nhttps://example.com/DoC/x')
    assert len(rows)==3
    assert all(r['item'].startswith('Golden Text: ') for r in rows)
    assert all(0 < r['threshold'] <= 1 for r in rows)


def test_profile_structure_validation():
    good={'profile_name':'X','profile_version':'1.9.0','model':'M','live':{'required_items':[]},
          'dynamic_fixed_texts':[{'item':'Golden Text: ABC','text':'ABC','threshold':0.74}]}
    assert validate_profile_structure(good)==[]
    bad={'profile_name':'X','profile_version':'1.9.0','model':'M','live':{'required_items':'bad'}}
    assert validate_profile_structure(bad)


def test_dynamic_fixed_text_runtime_evaluation():
    profile={'profile_name':'X','profile_version':'1.9.0','model':'M','live':{'required_items':['Golden Text: GPON']},
             'dynamic_fixed_texts':[{'item':'Golden Text: GPON','name':'GPON','text':'GPON VoIP Gateway','threshold':0.70}],
             'image_inspection':{'role_items':{'DETAIL':['Golden Text: GPON']}}}
    eng=MultiImageInspectionEngine(profile,'1.9.0')
    rows=eng._dynamic_rows('Header GPON VoIP Gateway Footer')
    assert rows[0].status=='PASS'


def test_profile_driven_role_items_override_legacy():
    profile={'profile_name':'Anything','model':'M','live':{'required_items':[]},
             'image_inspection':{'role_items':{'COMPLIANCE':['Golden Text: DOC'],'BASIC':['Dynamic: P/N']}}}
    eng=MultiImageInspectionEngine(profile,'1.9.0')
    roles=eng._role_items()
    assert roles['COMPLIANCE']=={'Golden Text: DOC'}
    assert roles['BASIC']=={'Dynamic: P/N'}
