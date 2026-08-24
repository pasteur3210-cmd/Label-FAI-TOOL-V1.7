import json
from pathlib import Path

from label_tool.core.multi_image_inspection import (
    MultiImageInspectionEngine, MultiImageResult, ImageEvidence
)


def load_profile(name='grg4297u_tsl_p1.json'):
    return json.loads(Path('label_tool/profiles', name).read_text(encoding='utf-8'))


def bare_engine(profile):
    e = MultiImageInspectionEngine.__new__(MultiImageInspectionEngine)
    e.profile = profile
    return e


def test_standard_five_photo_first_is_full_overview():
    e = bare_engine(load_profile())
    role = e.classify_photo_role({}, [], '', 1, 5)
    assert role == 'FULL'


def test_content_classifies_identity_closeup():
    e = bare_engine(load_profile())
    fields = {'sn_text':'2654297UF-AA000028','mac_text':'1C6499AFB49D','gpon_sn_text':'434D544499AFB49D'}
    role = e.classify_photo_role(fields, ['2654297UF-AA000028','1C6499AFB49D'], '', 4, 5)
    assert role == 'IDENTITY'


def test_content_classifies_compliance_closeup():
    e = bare_engine(load_profile())
    fields = {'made_in':'China','has_laser_text':True}
    role = e.classify_photo_role(fields, [], 'Made in China CLASS 1 LASER PRODUCT RoHS', 5, 5)
    assert role == 'COMPLIANCE'


def test_cross_photo_session_rule_refusion_ssid_mac_and_gpon():
    p = load_profile()
    e = bare_engine(p)
    result = MultiImageResult()
    result.session_fields = {
        'mac_barcode':'1C6499AFB49D',
        'ssid':'Telekom Slovenije_AFB49D',
        'gpon_sn_barcode':'434D544499AFB49D',
    }
    result.field_sources = {
        'mac_barcode':{'source':'identity.jpg','quality':0.9,'value':'1C6499AFB49D'},
        'ssid':{'source':'wifi.jpg','quality':0.9,'value':'Telekom Slovenije_AFB49D'},
        'gpon_sn_barcode':{'source':'identity.jpg','quality':0.9,'value':'434D544499AFB49D'},
    }
    best, conflicts = {}, {}
    e._merge_session_rules(result, {}, best, conflicts)
    assert best['Rule: SSID = MAC Last 6'].result == 'PASS'
    assert best['Rule: GPON S/N = Prefix + MAC Last 8'].result == 'PASS'


def test_artwork_overview_position_plus_closeup_shape_fuses_pass():
    p = load_profile()
    e = bare_engine(p)
    result = MultiImageResult()
    item='Artwork: RoHS Mark'
    result.position_evidence[item] = {
        'position_state':'PASS','position_error':0.4,'quality':0.8,'source':'full.jpg','score':0.3
    }
    result.closeup_shape_evidence[item] = {
        'shape_state':'PASS','score':0.82,'quality':0.9,'source':'compliance.jpg'
    }
    best={}
    e._merge_artwork_components(result,best)
    assert best[item].result == 'PASS'
    assert 'full.jpg' in best[item].source_image
    assert 'compliance.jpg' in best[item].source_image


def test_role_item_isolation_compliance_does_not_evaluate_identity():
    e = bare_engine(load_profile())
    assert e._role_allows('COMPLIANCE','Fixed: CLASS 1 LASER PRODUCT')
    assert not e._role_allows('COMPLIANCE','Variable: S/N Barcode Format')


def test_detail_photo_skips_legacy_full_label_engine(tmp_path):
    import numpy as np, cv2
    p=load_profile()
    e=bare_engine(p)
    class Base:
        class OCR: pass
        ocr=OCR()
        def inspect(self,*a,**k):
            raise AssertionError('detail photo must not enter legacy whole-label correction')
    e.base=Base()
    class Art: pass
    e.artwork=Art()
    e._direct_original_facts=lambda image: (
        {'ssid':'Telekom Slovenije_AFB49D','password':'483WzX8e','wifi_key':'MMBbgVzJUznv8Z'},
        'Password: 483WzX8e\nWiFi Key: MMBbgVzJUznv8Z\nSSID: Telekom Slovenije_AFB49D', [], []
    )
    img=np.full((400,800,3),235,dtype=np.uint8)
    path=tmp_path/'wifi.jpg'; cv2.imwrite(str(path),img)
    one, obs, fields, role, *_ = e._inspect_one(str(path),tmp_path,{},3)
    assert role=='WIFI'
    assert one.overall=='DETAIL'
