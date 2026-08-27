from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from label_tool.app import App
from label_tool.core.golden_profile_manager import _layout_candidate_score, select_final_label_image


def _app(profile):
    app=object.__new__(App)
    app.multi_image_engine=SimpleNamespace(profile=profile)
    app.multi_image_result=SimpleNamespace(evidence={})
    return app


def test_final_label_score_beats_password_support_screenshot():
    support='Password proposal characters are from this pool. New password must be min 14 characters. Entropy must be > 80. Comtrend office.'
    label='COMTREND GPON VoIP Gateway Model GRG-4297u P/N 738125-001 Input 12V 1.5A S/N 2644297UF-FF000001 MAC C8D12A00767F GPON S/N 434D54442A00767F SSID Telekom Slovenije_00767F WiFi Key ABCD1234 Made in China'
    s1,_=_layout_candidate_score(support,0)
    s2,_=_layout_candidate_score(label,2)
    assert s2 > s1 + 10


def test_select_final_label_image_uses_label_content_not_largest_file(tmp_path):
    support=tmp_path/'support.png'; final=tmp_path/'final.png'
    Image.new('RGB',(1600,1000),'white').save(support)
    Image.new('RGB',(900,700),'white').save(final)
    # Make support larger on disk to reproduce old largest-image failure mode.
    support.write_bytes(support.read_bytes()+b'X'*20000)
    rows=[
        {'file':str(support),'text':'Password proposal characters entropy reset button software upgrade Comtrend office','lines':[]},
        {'file':str(final),'text':'COMTREND Model GRG-4297u P/N 738125-001 Input 12V S/N 2644297UF MAC C8D12A00767F SSID Telekom WiFi Key ABCD Made in China','lines':[]},
    ]
    codes=[{'file':str(final),'kind':'QR'},{'file':str(final),'kind':'BARCODE'}]
    chosen,score,reason=select_final_label_image([support,final],rows,codes)
    assert chosen == final
    assert score > 5
    assert 'machine_codes=2' in reason


def test_mac_focus_and_spec_are_from_final_label_not_support_image(tmp_path):
    support=tmp_path/'support.png'; final=tmp_path/'final.png'
    Image.new('RGB',(1200,700),'white').save(support)
    Image.new('RGB',(1000,600),'white').save(final)
    profile={
        'golden_import':{
            'candidate_layout_image':str(support),  # intentionally wrong old-profile value
            'asset_dir':str(tmp_path),
            'image_ocr_results':[
                {'file':str(support),'text':'Password proposal Comtrend office random WiFi password entropy','lines':[
                    {'text':'Comtrend office random WiFi password','box':[[100,100],[900,100],[900,180],[100,180]]},
                ]},
                {'file':str(final),'text':'COMTREND Model GRG-4297u P/N 738125-001 S/N 2644297UF MAC C8D12A00767F Made in China','lines':[
                    {'text':'MAC: C8D12A00767F','box':[[510,310],[800,310],[800,355],[510,355]]},
                    {'text':'Made in China','box':[[500,420],[730,420],[730,460],[500,460]]},
                ]},
            ],
            'machine_codes':[{'file':str(final),'kind':'BARCODE','points':[[500,250],[800,250],[800,300],[500,300]]}],
        },
        'golden_form_items':[
            {'form_no':12,'item':'Golden #12: MAC','type':'Golden Barcode','raw_text':'MAC: Comtrend mac address (one unit 10 MAC) Barcode type: Code 128 Checking code: 1','engine_items':['Variable: MAC Human Readable Format']},
            {'form_no':14,'item':'Golden #14: Made in China/Taiwan','type':'Golden Choice','raw_text':'Made in China/Taiwan (change according to production location)','engine_items':['Variable: Made in Format']},
        ],
    }
    app=_app(profile)
    assert Path(app._golden_review_image_path()) == final
    path,box,note=app._golden_review_region('Golden Text: MAC: Comtrend mac address (one unit 10 MAC)')
    assert Path(path) == final
    assert box is not None and box[0] >= 400
    assert 'MAC' in note
    spec=app._golden_item_specification('Golden Text: MAC: Comtrend mac address (one unit 10 MAC)')
    assert 'Golden item #12' in spec
    assert 'Code 128' in spec
    assert 'password' not in spec.lower()


def test_made_in_spec_and_focus_use_item_14(tmp_path):
    final=tmp_path/'final.png'; Image.new('RGB',(1000,600),'white').save(final)
    profile={
        'golden_import':{'candidate_layout_image':str(final),'asset_dir':str(tmp_path),'image_ocr_results':[
            {'file':str(final),'text':'Made in China','lines':[{'text':'Made in China','box':[[500,420],[730,420],[730,460],[500,460]]}]}
        ],'machine_codes':[]},
        'golden_form_items':[{'form_no':14,'item':'Golden #14: Made in','type':'Golden Choice','raw_text':'Made in China/Taiwan (change according to production location)','engine_items':['Variable: Made in Format']}],
    }
    app=_app(profile)
    path,box,note=app._golden_review_region('Golden Text: Made in China/Taiwan')
    assert Path(path)==final
    assert box is not None
    assert 'Made in' in note
    spec=app._golden_item_specification('Golden Text: Made in China/Taiwan')
    assert 'Golden item #14' in spec
    assert 'Made in China/Taiwan' in spec


def test_manual_review_ui_has_two_separate_golden_references():
    src=Path('label_tool/app.py').read_text(encoding='utf-8')
    fn=src[src.index('    def _show_manual_golden_review'):src.index('    def manual_review_selected')]
    assert 'Golden Item Specification / Golden 項目說明' in fn
    assert '_golden_item_specification(item)' in fn
    assert 'Final Label / Full Golden reference' in fn

def test_grg4297u_real_request_form_mac_and_made_in_spec_text_are_not_replaced_by_password_notes(tmp_path):
    final=tmp_path/'final.png'; Image.new('RGB',(1000,700),'white').save(final)
    profile={
        'golden_import':{'candidate_layout_image':str(final),'asset_dir':str(tmp_path),'image_ocr_results':[],'machine_codes':[]},
        'golden_form_items':[
            {'form_no':12,'item':'Golden #12: MAC','type':'Golden Barcode',
             'raw_text':'MAC: Comtrend mac address (一台 10 個 MAC) (生管提供) Barcode type：Code 128 Checking code：1',
             'engine_items':['Variable: MAC Human Readable Format','Variable: MAC Barcode Format']},
            {'form_no':14,'item':'Golden #14: Made in China/Taiwan','type':'Golden Choice',
             'raw_text':'Made in China/Taiwan (依實際生產地點做變更)',
             'engine_items':['Variable: Made in Format']},
        ],
    }
    app=_app(profile)
    mac=app._golden_item_specification('Golden Text: MAC: Comtrend mac address (一台 10 個 MAC) (生管提供)')
    made=app._golden_item_specification('Golden Text: Made in China/Taiwan (依實際生產地點做變更)')
    assert 'Golden item #12' in mac and 'Code 128' in mac and '一台 10 個 MAC' in mac
    assert 'Golden item #14' in made and 'Made in China/Taiwan' in made
    assert 'password' not in (mac+made).lower()
