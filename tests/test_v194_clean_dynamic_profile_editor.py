import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from label_tool.core import golden_profile_manager as gpm


def _make_docx(path: Path):
    xml='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:r><w:t>680010-305 GRG-4355u-DIG-P1 Chassis Label</w:t></w:r></w:p>
<w:p><w:r><w:t>BARCODE TYPE: Code128</w:t></w:r></w:p>
</w:body></w:document>'''
    with ZipFile(path,'w',ZIP_DEFLATED) as z:
        z.writestr('word/document.xml',xml)
        z.writestr('word/media/label.png',b'FAKEPNG')


def _contaminated_seed():
    return {
        'profile_name':'GRG-4297u Chassis Label','profile_version':'1.9.3','model':'GRG-4297u',
        'label_type':'Chassis Label','label_pn':'680010-378',
        'fixed_fields':{'model':'GRG-4297u','ip':'192.168.1.1','username':'admin'},
        'rules':{'ssid_prefix':'Comtrend','password_length':12},
        'rois':{'fixed_text':[0,0,1,1]},
        'live':{'required_items':['Fixed: ip','Fixed: Input 12V 1.5A','Variable: P/N Format'],
                'custom_targets':[{'item':'Fixed: ip'}], 'camera_width':1920,'camera_height':1080},
        'image_quality':{'min_sharpness':10},
        'vision':{'label_expand_margin':0.1},
        'image_inspection':{'mode':'guided_multi_image','role_items':{'BASIC':['Fixed: ip']}},
        'artwork_verification':{'enabled':True,'symbols':[{'item':'Artwork: CE Mark','template':'old/ce.png','required':True}]},
    }


def test_dynamic_import_does_not_inherit_seed_inspection_content(tmp_path):
    src=tmp_path/'680010-305 GRG-4355u-DIG-P1 Chassis Label.docx'; _make_docx(src)
    profile_root=tmp_path/'profiles'; profile_root.mkdir()
    image_text='''COMTREND\nXGSPON ONT\nModel: GRG-4355u\nP/N: 301151-001\nInput: 12V 3A\nUSB 3.0: 5V 900mA\nGPON S/N: XXXXXXXXXXXXXXXX\nMAC: XXXXXXXXXXXX\nS/N: XXXXXXXXXXXXXXXX\nWiFi 2.4GHz: DIGIFIBRA-XXXX\nWiFi 5GHz: DIGIFIBRA-PLUS-XXXX\nKey: XXXXXXXXXXXX\nCLASS 1 LASER PRODUCT\nMade in China'''
    with patch.object(gpm,'external_profile_dir',lambda: profile_root), patch.object(gpm,'_ocr_golden_images',return_value=(image_text,[{'file':'label.png','line_count':12,'text':image_text}])):
        out,p=gpm.build_dynamic_profile(str(src),_contaminated_seed())
    req=set(p['live']['required_items'])
    assert 'Fixed: ip' not in req
    assert 'Fixed: Input 12V 1.5A' not in req
    assert 'username' not in p.get('fixed_fields',{})
    assert 'ip' not in p.get('fixed_fields',{})
    assert p['rules']['sn_regex']
    assert p['rules']['pn_display']=='301151-001'
    assert p['artwork_verification']['symbols'] == []
    assert p['artwork_verification']['enabled'] is False
    assert 'Fixed: model' in req
    assert 'Variable: P/N Format' in req
    assert 'Variable: GPON S/N Human Readable Format' in req
    assert 'Variable: MAC Human Readable Format' in req
    assert 'Variable: S/N Human Readable Format' in req
    assert 'Variable: SSID Format' in req
    assert 'Variable: WiFi Key Format' in req
    assert any('Input: 12V 3A' in r.get('text','') for r in p['dynamic_fixed_texts'])
    assert any('USB 3.0: 5V 900mA' in r.get('text','') for r in p['dynamic_fixed_texts'])
    assert out.name=='GRG-4355u_Chassis_Label_680010-305.json'


def test_visual_editor_can_add_edit_delete_golden_text_without_python_change():
    p=_contaminated_seed()
    p=gpm._clean_engine_template(p)
    p.update({'dynamic_profile':True,'profile_name':'GRG-4355u Chassis Label','profile_version':'1.9.4','profile_status':'DRAFT','model':'GRG-4355u','label_type':'Chassis Label','label_pn':'680010-305'})
    rows=[
        {'item':'Variable: MAC Human Readable Format','type':'Standard','role':'IDENTITY','required':True,'expected':'','threshold':'','origin':'MANUAL_EDIT'},
        {'item':'Golden Text: Input Rating','type':'Golden Text','role':'BASIC','required':True,'expected':'Input: 12V 3A','threshold':0.80,'origin':'MANUAL_EDIT','manual_review_allowed':True},
    ]
    p2=gpm.apply_editable_items(p,rows)
    got=gpm._dynamic_item_rows(p2)
    assert {r['item'] for r in got}=={'Variable: MAC Human Readable Format','Golden Text: Input Rating'}
    gt=next(r for r in got if r['type']=='Golden Text')
    assert gt['expected']=='Input: 12V 3A'
    assert abs(float(gt['threshold'])-0.80)<1e-9
    assert p2['profile_status']=='DRAFT'
    assert p2['image_inspection']['role_items']['BASIC']==['Golden Text: Input Rating']


def test_metadata_editor_supports_internal_and_customer_model(tmp_path):
    path=tmp_path/'GRG-4355u_Chassis_Label_680010-305.json'
    p={
        'dynamic_profile':True,'profile_name':'GRG-4355u Chassis Label','profile_version':'1.9.4','profile_status':'DRAFT',
        'model':'GRG-4355u','label_type':'Chassis Label','label_pn':'680010-305','live':{'required_items':[]},
        'fixed_fields':{'model':'GRG-4355u'},'dynamic_standard_items':[],
        'golden_import':{'source_sha256':'abc'},
        'profile_identity':{**gpm.canonical_profile_identity('GRG-4355u','Chassis Label','680010-305'),'source_sha256':'abc'},
    }
    path.write_text(json.dumps(p),encoding='utf-8')
    new_path,new=gpm.save_profile_identity_edits(path,p,'GRG-4355u','Chassis Label','680010-305','PRT-7302')
    assert new_path==path
    assert new['customer_model']=='PRT-7302'
    assert new['model_aliases']==['GRG-4355u','PRT-7302']
    assert gpm.dynamic_identity_errors(new,new_path)==[]


def test_app_contains_visual_profile_editor_controls():
    source=Path('label_tool/app.py').read_text(encoding='utf-8')
    for label in ('Add Item','Edit Selected','Delete Selected','Edit Metadata / 修改基本資料','Save Draft / 儲存草稿'):
        assert label in source
