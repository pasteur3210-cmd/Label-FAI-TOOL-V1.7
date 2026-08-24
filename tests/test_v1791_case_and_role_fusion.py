import json
from pathlib import Path
from types import SimpleNamespace

from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult, ImageEvidence


def profile():
    return json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))


def bare():
    e=MultiImageInspectionEngine.__new__(MultiImageInspectionEngine)
    e.profile=profile()
    return e


def test_five_photo_closeup_is_not_promoted_to_full_by_many_hits():
    e=bare()
    fields={
        'pn':'738125-001','ip':'192.168.1.1','username':'user','password':'483WzX8e',
        'wifi_key':'MMBbgVzJUzvn8Z','ssid':'Telekom Slovenije_AFB49D','has_input_text':True,
        'has_usb_text':True,'has_comtrend_address':True,
    }
    assert e.classify_photo_role(fields, [], 'WiFi Key Password SSID', 4, 5) != 'FULL'


def test_visual_compliance_override_needs_two_symbols():
    e=bare()
    class Art:
        def evaluate_shape_only(self, image, requested_items=None):
            return [], [
                SimpleNamespace(shape_state='PASS'),
                SimpleNamespace(shape_state='PASS'),
                SimpleNamespace(shape_state='VERIFY'),
            ]
    e.artwork=Art()
    assert e._visual_compliance_override(object(),'IDENTITY') == 'COMPLIANCE'


def test_exact_qr_case_match_overrides_higher_quality_wrong_case():
    e=bare()
    r=MultiImageResult()
    r.session_fields={'wifi_key':'MMBbgVzJUzvn8z','qr_wifi_key':'MMBbgVzJUzvn8Z'}
    r.field_sources={'wifi_key':{'source':'full.jpg','quality':0.9,'value':'MMBbgVzJUzvn8z'},
                     'qr_wifi_key':{'source':'full.jpg','quality':0.9,'value':'MMBbgVzJUzvn8Z'}}
    e._reconcile_machine_readable_wifi_key(r, {'wifi_key':'MMBbgVzJUzvn8Z'}, 'wifi_closeup.jpg', 0.4)
    assert r.session_fields['wifi_key']=='MMBbgVzJUzvn8Z'
    assert r.field_sources['wifi_key']['source']=='wifi_closeup.jpg'


def test_case_only_ambiguity_requests_more_image_not_conflict():
    e=bare()
    r=MultiImageResult()
    r.session_fields={'wifi_key':'MMBbgVzJUzvn8z','qr_wifi_key':'MMBbgVzJUzvn8Z','wifi_qr':'WIFI:T:WPA;S:Telekom Slovenije_AFB49D;P:MMBbgVzJUzvn8Z;;',
                      'ssid':'Telekom Slovenije_AFB49D'}
    r.field_sources={k:{'source':'a.jpg','quality':0.8,'value':v} for k,v in r.session_fields.items()}
    best={'Consistency: QR Key vs Printed WiFi Key':ImageEvidence('Consistency: QR Key vs Printed WiFi Key','PASS','MMBbgVzJUzvn8Z','MMBbgVzJUzvn8z','a.jpg',0.7)}
    conflicts={}
    e._merge_session_rules(r,{},best,conflicts)
    assert best['Consistency: QR Key vs Printed WiFi Key'].result=='NEED_MORE_IMAGE'
    assert 'Consistency: QR Key vs Printed WiFi Key' not in conflicts


def test_artwork_verify_position_can_be_corroborated_by_separate_closeup_shape():
    e=bare()
    r=MultiImageResult()
    item='Artwork: RoHS Mark'
    r.position_evidence[item]={'position_state':'VERIFY','position_error':0.98,'quality':0.7,'source':'full.jpg'}
    r.closeup_shape_evidence[item]={'shape_state':'PASS','score':0.8,'quality':0.9,'source':'compliance.jpg'}
    best={}
    e._merge_artwork_components(r,best)
    assert best[item].result=='PASS'
    assert 'VERIFY-corroborated' in best[item].message
