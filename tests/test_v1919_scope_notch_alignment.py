from pathlib import Path

import cv2
import numpy as np

from label_tool.core import golden_profile_manager as gpm
from label_tool.core.multi_image_inspection import detect_label_notch_direction, NOTCH_ITEM


def _box(y0, y1, x0=20, x1=300):
    return [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]


def test_cmp001_excludes_process_and_lower_test_qr_but_keeps_traceability():
    text='''
1. Comtrend logo
2. Model: GRG-4297u
3. QR Code for 測試刷入使用，內容含 SN、MAC、Password、WiFi Key
4. 匯入列印方式參考 GRG-4297u Chassis Label 列印說明
Finished Information:
'''
    rows=gpm.extract_golden_form_items(text)
    final=Path('final.png')
    # Dense main-label OCR band + one separated lower production/test line.
    ocr=[{'file':'final.png','lines':[
        {'text':'COMTREND','box':_box(80,110)},
        {'text':'Model GRG-4297u','box':_box(130,160)},
        {'text':'P/N 738125-001','box':_box(180,210)},
        {'text':'Made in China','box':_box(360,390)},
        {'text':'S/N lower production','box':_box(760,790)},
    ]}]
    codes=[
        {'file':'final.png','kind':'QR','points':[[250,220],[330,220],[330,300],[250,300]]},
        {'file':'final.png','kind':'QR','points':[[120,700],[220,700],[220,800],[120,800]]},
    ]
    meta=gpm._apply_chassis_scope_filter(rows,final,ocr,codes)
    assert rows[0]['required'] is True
    assert rows[1]['required'] is True
    assert rows[2]['required'] is False
    assert rows[2]['inspection_scope']=='REFERENCE_ONLY'
    assert 'outside shipped-label scope' in rows[2]['scope_reason']
    assert rows[3]['required'] is False
    assert rows[3]['inspection_scope']=='REFERENCE_ONLY'
    assert len(meta['excluded_items'])==2


def test_cmp001_keeps_test_qr_when_it_is_inside_outgoing_label():
    rows=gpm.extract_golden_form_items('1. QR Code：含 SN、MAC、WiFi Key for 測試刷入使用\nFinished Information:')
    final=Path('final.png')
    ocr=[{'file':'final.png','lines':[
        {'text':'COMTREND','box':_box(60,90)},
        {'text':'Model GRG-4366','box':_box(120,150)},
        {'text':'MAC 64680CFFBD11','box':_box(300,330)},
        {'text':'Made in Taiwan','box':_box(430,460)},
    ]}]
    codes=[{'file':'final.png','kind':'QR','points':[[500,80],[590,80],[590,170],[500,170]]}]
    gpm._apply_chassis_scope_filter(rows,final,ocr,codes)
    assert rows[0]['required'] is True
    assert rows[0]['inspection_scope']=='CHASSIS_LABEL'


def test_cmp002_cmp003_keep_length_only_rules():
    rules=gpm._rules_from_golden_text('8. Password: Random 8 characters\n10. WiFi Key: Random 14 碼')
    assert rules['password_length']==8
    assert rules['wifi_key_length']==14
    # User explicitly chose length-only for CMP-002 / CMP-003.
    assert 'password_forbidden_overlap' not in rules
    assert 'wifi_key_forbidden_overlap' not in rules


def test_cmp008_parses_request_form_notch_and_builds_rule():
    text='Label Example: 印出後貼紙缺角處在左上角'
    direction,raw=gpm._extract_notch_direction(text)
    assert direction=='TOP_LEFT'
    assert '缺角' in raw
    rules=gpm._rules_from_golden_text(text)
    assert rules['notch_direction']=='TOP_LEFT'


def test_cmp008_notch_detector_top_left_synthetic():
    img=np.zeros((500,800,3),dtype=np.uint8)
    # White label polygon with a clear top-left cut corner.
    pts=np.array([[170,100],[650,100],[650,400],[100,400],[100,170]],dtype=np.int32)
    cv2.fillPoly(img,[pts],(245,245,245))
    direction,conf,msg=detect_label_notch_direction(img)
    assert direction=='TOP_LEFT', (direction,conf,msg)
    assert conf>=0.42


def test_notch_item_is_manual_reviewable_when_auto_uncertain():
    profile={
        'live':{'required_items':[NOTCH_ITEM]},
        'rules':{'notch_direction':'TOP_LEFT'},
        'dynamic_profile':True,
        'golden_form_items':[{
            'form_no':None,'item':'Golden Geometry: Label Notch Direction','type':'Golden Geometry',
            'role':'FULL','required':True,'engine_items':[NOTCH_ITEM], 'manual_review_allowed':True,
            'origin':'GOLDEN','source':'Golden'
        }],
    }
    summary=gpm.validation_readiness_summary(profile)
    assert summary['auto']==1
    assert summary['missing']==0
