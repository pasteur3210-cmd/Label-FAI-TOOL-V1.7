from pathlib import Path
from PIL import Image

from label_tool.app import App


def test_gpon_barcode_locator_prefers_gpon_payload_not_first_barcode(tmp_path):
    img=tmp_path/'final.png'
    Image.new('RGB',(1000,700),'white').save(img)
    gi={
        'machine_codes':[
            {'kind':'BARCODE','file':str(img),'text':'2654297UF-AA000029','points':[(600,80),(900,80),(900,140),(600,140)]},
            {'kind':'BARCODE','file':str(img),'text':'1C6499AFB4A7','points':[(600,200),(900,200),(900,260),(600,260)]},
            {'kind':'BARCODE','file':str(img),'text':'434D544499AFB4A7','points':[(600,320),(900,320),(900,380),(600,380)]},
        ],
        'image_ocr_results':[],
    }
    app=object.__new__(App)
    row={'raw_text':'GPON S/N: 434D5444XXXXXXXX','expected':'Code128 data: 434D5444XXXXXXXX','machine_code_field':'gpon_sn'}
    box,note=App._golden_review_machine_code_box(app,'Variable: GPON S/N Barcode Format',row,str(img),gi,'')
    assert box is not None
    assert box[1] > 250, box
    assert 'GPON_SN' in note


def test_consistency_gpon_uses_same_semantic_locator(tmp_path):
    img=tmp_path/'final.png'
    Image.new('RGB',(1000,700),'white').save(img)
    gi={'machine_codes':[
        {'kind':'BARCODE','file':str(img),'text':'2654297UF-AA000029','points':[(600,80),(900,80),(900,140),(600,140)]},
        {'kind':'BARCODE','file':str(img),'text':'434D544499AFB4A7','points':[(600,320),(900,320),(900,380),(600,380)]},
    ], 'image_ocr_results':[]}
    app=object.__new__(App)
    row={'raw_text':'GPON S/N: CMTD + MAC last 8','machine_code_field':'gpon_sn'}
    box,note=App._golden_review_machine_code_box(app,'Consistency: GPON S/N Text vs Barcode',row,str(img),gi,'434D544499AFB4A7')
    assert box is not None and box[1] > 250
    assert 'GPON_SN' in note


def test_manual_review_full_golden_uses_arrow_callout_not_large_box():
    src=Path('label_tool/app.py').read_text(encoding='utf-8')
    assert 'factory-review locator: use a callout arrow as' in src
    assert 'draw.polygon([(cx,cy),p1,p2]' in src
    assert 'Small corner ticks are deliberately non-authoritative' in src
    assert "draw.rectangle((max(0,x1-off)" not in src
