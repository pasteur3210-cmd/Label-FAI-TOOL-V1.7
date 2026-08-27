import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from label_tool.app import App
from label_tool.core.golden_profile_manager import (
    _docx_final_label_media_names,
    apply_editable_items,
    normalize_dynamic_profile_for_runtime,
    validation_readiness_errors,
    validation_readiness_summary,
)


def _app(profile):
    app=object.__new__(App)
    app.multi_image_engine=SimpleNamespace(profile=profile)
    app.multi_image_result=SimpleNamespace(evidence={})
    return app


def test_vml_final_label_media_after_label_example_is_detected():
    doc_xml='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
      xmlns:v="urn:schemas-microsoft-com:vml">
      <w:body>
        <w:p><w:r><w:t>Password proposal</w:t><w:pict><v:shape><v:imagedata r:id="rId1"/></v:shape></w:pict></w:r></w:p>
        <w:p><w:r><w:t>Label Example:</w:t></w:r></w:p>
        <w:p><w:r><w:pict><v:shape><v:imagedata r:id="rId9"/></v:shape></w:pict></w:r></w:p>
      </w:body></w:document>'''
    rels='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="x" Target="media/password.png"/>
      <Relationship Id="rId9" Type="x" Target="media/final.png"/>
    </Relationships>'''
    with tempfile.TemporaryDirectory() as td:
        docx=Path(td)/'legacy-converted.docx'
        with zipfile.ZipFile(docx,'w') as z:
            z.writestr('word/document.xml',doc_xml)
            z.writestr('word/_rels/document.xml.rels',rels)
        assert _docx_final_label_media_names(docx)==['final.png']


def test_numbered_profile_reference_binding_never_fuzzy_matches_other_item(tmp_path):
    final=tmp_path/'final.png'; Image.new('RGB',(900,600),'white').save(final)
    profile={
        'golden_import':{'final_label_image':str(final),'asset_dir':str(tmp_path),'image_ocr_results':[],'machine_codes':[]},
        'golden_item_bindings':{'Artwork: COMTREND Logo':1,'Variable: MAC Human Readable Format':12,'Variable: Made in Format':14},
        'golden_form_items':[
            {'form_no':1,'item':'Golden #1: Comtrend logo','type':'Golden Artwork','raw_text':'Comtrend logo','engine_items':['Artwork: COMTREND Logo']},
            {'form_no':8,'item':'Golden #8: Password','type':'Golden Variable','raw_text':'Password: Random 8 characters. Detailed password proposal follows.','engine_items':['Variable: Password Format']},
            {'form_no':12,'item':'Golden #12: MAC','type':'Golden Barcode','raw_text':'MAC: Comtrend mac address (one unit 10 MAC) Barcode type: Code 128','engine_items':['Variable: MAC Human Readable Format']},
            {'form_no':14,'item':'Golden #14: Made in','type':'Golden Choice','raw_text':'Made in China/Taiwan','engine_items':['Variable: Made in Format']},
        ],
    }
    app=_app(profile)
    assert app._golden_form_row_for_item('Artwork: COMTREND Logo')['form_no']==1
    assert app._golden_form_row_for_item('Variable: MAC Human Readable Format')['form_no']==12
    assert app._golden_form_row_for_item('Variable: Made in Format')['form_no']==14
    assert 'Password' not in app._golden_item_specification('Artwork: COMTREND Logo')
    assert 'Golden item #1' in app._golden_item_specification('Artwork: COMTREND Logo')
    assert Path(app._golden_review_image_path())==final


def test_validate_accepts_manual_review_as_first_class_handling_path():
    p={
        'dynamic_profile':True,
        'golden_completeness':{'document_item_count':4,'profile_item_count':4,'document_item_numbers':[1,2,3,4],'missing_item_numbers':[]},
        'golden_form_items':[
            {'form_no':1,'item':'Golden #1 Logo','type':'Golden Artwork','required':True,'engine_items':[],'presence_item':'','manual_review_allowed':True},
            {'form_no':2,'item':'Golden #2 Text','type':'Golden Text','required':True,'engine_items':[],'manual_review_allowed':True},
            {'form_no':3,'item':'Golden #3 QR','type':'Golden QR','required':True,'engine_items':[],'presence_item':'Golden Machine Code: QR #3','manual_review_allowed':True},
            {'form_no':4,'item':'Golden #4 Disabled','type':'Needs Review','required':False,'engine_items':[],'manual_review_allowed':True},
        ],
    }
    assert validation_readiness_errors(p)==[]
    s=validation_readiness_summary(p)
    assert s=={'auto':2,'manual':1,'disabled':1,'missing':0,'total':4}


def test_validate_blocks_only_required_item_with_no_auto_or_manual_path():
    p={
        'dynamic_profile':True,
        'golden_completeness':{'document_item_count':1,'profile_item_count':1,'document_item_numbers':[1],'missing_item_numbers':[]},
        'golden_form_items':[{'form_no':1,'item':'Golden #1 Unknown','type':'Needs Review','required':True,'engine_items':[],'presence_item':'','manual_review_allowed':False}],
    }
    errs=validation_readiness_errors(p)
    assert len(errs)==1 and 'no AUTO or MANUAL handling path' in errs[0]


def test_runtime_migration_removes_stale_support_text_and_rebuilds_from_form_rows():
    p={
        'dynamic_profile':True,'profile_status':'DRAFT','profile_version':'1.9.13',
        'live':{'required_items':['Golden Text: password proposal line','Variable: MAC Human Readable Format']},
        'golden_form_items':[
            {'form_no':1,'item':'Golden #1: Comtrend logo','type':'Golden Artwork','role':'BASIC','required':True,'origin':'GOLDEN','source':'Golden','engine_items':['Artwork: COMTREND Logo'],'presence_item':'','manual_review_allowed':True},
            {'form_no':12,'item':'Golden #12: MAC','type':'Golden Barcode','role':'IDENTITY','required':True,'origin':'GOLDEN','source':'Golden','engine_items':['Variable: MAC Human Readable Format','Variable: MAC Barcode Format','Consistency: MAC Text vs Barcode'],'presence_item':'Golden Machine Code: MAC #12','manual_review_allowed':True},
            {'form_no':14,'item':'Golden #14: Made in','type':'Golden Choice','role':'COMPLIANCE','required':True,'origin':'GOLDEN','source':'Golden','engine_items':['Variable: Made in Format'],'presence_item':'','manual_review_allowed':True},
        ],
        'dynamic_fixed_texts':[{'item':'Golden Text: password proposal line','text':'password proposal line','required':True,'role':'DETAIL'}],
        'dynamic_standard_items':[],
        'golden_completeness':{'document_item_count':3,'profile_item_count':3,'document_item_numbers':[1,12,14],'missing_item_numbers':[]},
    }
    migrated,changed,notes=normalize_dynamic_profile_for_runtime(p)
    assert changed
    assert 'Golden Text: password proposal line' not in migrated['live']['required_items']
    assert migrated['dynamic_fixed_texts']==[]
    assert migrated['golden_item_bindings']['Artwork: COMTREND Logo']==1
    assert migrated['golden_item_bindings']['Variable: MAC Barcode Format']==12
    assert migrated['golden_item_bindings']['Variable: Made in Format']==14
    assert any('removed stale generated Golden Text' in x for x in notes)
    migrated2,changed2,_=normalize_dynamic_profile_for_runtime(migrated)
    assert not changed2 and migrated2==migrated
