from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image

from label_tool.app import App
from label_tool.core.artwork_presence import resolve_artwork_file


def _app(profile):
    app=object.__new__(App)
    app.multi_image_engine=SimpleNamespace(profile=profile)
    app.multi_image_result=SimpleNamespace(evidence={})
    return app


def test_weee_artwork_can_get_conservative_review_marker(tmp_path):
    templ, _path, _audit = resolve_artwork_file('grg4297u_chassis/weee_mark.png')
    assert templ is not None and templ.size
    canvas=np.full((700,1100),255,dtype=np.uint8)
    # Paste the real bundled generic WEEE template into a synthetic Golden.
    t=cv2.resize(templ,(max(24,templ.shape[1]),max(24,templ.shape[0])))
    y,x=250,760
    h,w=t.shape[:2]
    canvas[y:y+h,x:x+w]=t
    golden=tmp_path/'golden.png'
    cv2.imencode('.png',canvas)[1].tofile(str(golden))
    profile={
        'golden_import':{'candidate_layout_image':str(golden),'image_ocr_results':[]},
        'golden_form_items':[{'item':'Golden #3: WEEE Mark','type':'Golden Artwork','engine_items':['Artwork: WEEE Mark']}],
    }
    app=_app(profile)
    path,box,note=app._golden_review_region('Artwork: WEEE Mark')
    assert Path(path)==golden
    assert box is not None
    assert box[0] < x+w and box[2] > x
    assert box[1] < y+h and box[3] > y
    assert 'Artwork marker' in note


def test_comtrend_artwork_uses_exact_ocr_marker_not_unrelated_text(tmp_path):
    golden=tmp_path/'golden.png'
    Image.new('RGB',(1000,600),'white').save(golden)
    profile={
        'golden_import':{
            'candidate_layout_image':str(golden),
            'image_ocr_results':[{'file':str(golden),'lines':[
                {'text':'WiFi Key: ABCD SSID: Comtrend1234','box':[[600,300],[900,300],[900,380],[600,380]]},
                {'text':'COMTREND','box':[[70,60],[330,60],[330,120],[70,120]]},
            ]}],
        },
        'golden_form_items':[{'item':'Golden #1: Comtrend Logo','type':'Golden Artwork','engine_items':['Artwork: COMTREND Logo']}],
    }
    app=_app(profile)
    _path,box,note=app._golden_review_region('Artwork: COMTREND Logo')
    assert box is not None
    assert box[0] < 200 and box[2] < 500
    assert 'exact Golden OCR COMTREND' in note


def test_full_golden_button_re_renders_with_highlight_and_focus_is_optional():
    src=Path('label_tool/app.py').read_text(encoding='utf-8')
    fn=src[src.index('    def _show_manual_golden_review'):src.index('    def manual_review_selected')]
    assert "render_golden(None,'Final Label / Full Golden reference',golden_crop)" in fn
    assert 'REVIEW: {item}' in fn
    assert "view_state.set('Full Golden / 完整Golden')" in fn
    assert "view_state.set('Focus Item / 項目放大')" in fn
    assert 'golden_focus_allowed=bool(golden_crop)' in fn
    assert "focus_btn.config(state='disabled')" in fn


def test_weee_can_show_suggested_area_from_qr_when_exact_locator_is_unavailable(tmp_path):
    golden=tmp_path/'golden.png'
    Image.new('RGB',(1000,600),'white').save(golden)
    profile={
        'golden_import':{
            'candidate_layout_image':str(golden),
            'image_ocr_results':[],
            'machine_codes':[{'kind':'QR','file':str(golden),'points':[[820,80],[940,80],[940,200],[820,200]]}],
        },
        'golden_form_items':[{'item':'Golden #3: WEEE Mark','type':'Golden Artwork','engine_items':['Artwork: WEEE Mark']}],
    }
    app=_app(profile)
    _path,box,note=app._golden_review_region('Artwork: WEEE Mark')
    assert box is not None
    assert box[0] >= 700 and box[1] >= 150
    assert note.startswith('Suggested WEEE search area')
