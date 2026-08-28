from pathlib import Path
import tempfile

from label_tool.core.golden_profile_manager import _rules_from_golden_text, normalize_dynamic_profile_for_runtime
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult, ImageEvidence, IDENTITY_REVIEW_ITEM


def test_grg4297_password_random_8_is_parsed_as_8_not_zero():
    text='''8. Password: Random 8 characters (不可使用 MAC or SN 任一部分) (生管提供)\n9. SSID=Telekom Slovenije_XXXXXX\n10. WiFi Key: Random 14 碼'''
    rules=_rules_from_golden_text(text)
    assert rules['password_length']==8
    assert rules['wifi_key_length']==14


def test_every_nonpass_item_has_manual_completion_path():
    samples=[
        'Variable: Password Format',
        'Variable: S/N Barcode Format',
        'Variable: MAC Barcode Format',
        'Consistency: S/N Text vs Barcode',
        'Golden Machine Code: QR #19',
        'Artwork: COMTREND Logo',
        'Golden #14: Made in',
    ]
    for item in samples:
        assert MultiImageInspectionEngine._manual_review_allowed(item)
        assert MultiImageInspectionEngine.manual_attention_mode(item)=='OVERRIDE_ALLOWED'


def test_password_fail_can_be_completed_as_manual_pass_and_audit_is_preserved(tmp_path):
    eng=object.__new__(MultiImageInspectionEngine)
    eng.profile={'live':{'required_items':['Variable: Password Format']}}
    eng._required_items=lambda:['Variable: Password Format']
    eng._write_excel=lambda result, expected: str(tmp_path/'report.xlsx')
    result=MultiImageResult(session_id='t',session_dir=str(tmp_path))
    result.evidence['Variable: Password Format']=ImageEvidence(
        item='Variable: Password Format',result='FAIL',actual='483WzX8e',expected='8 characters',
        source_image='a.jpg',quality_score=0.9,message='Password length invalid',error_code='FMT-PASSWORD',photo_role='WIFI')
    result.identity_status='PASS'
    out=eng.apply_manual_pass(result,['Variable: Password Format'],'Operator checked against Golden')
    assert out.evidence['Variable: Password Format'].result=='MANUAL_PASS'
    assert out.manual_overrides['Variable: Password Format']['auto_result']=='FAIL'
    assert out.manual_overrides['Variable: Password Format']['auto_actual']=='483WzX8e'
    assert out.overall=='PASS_WITH_MANUAL_REVIEW'


def test_manual_review_mode_no_longer_blocks_identity_or_consistency_items():
    for item in ['Variable: S/N Human Readable Format','Consistency: MAC Text vs Barcode','Variable: WiFi QR Format']:
        assert MultiImageInspectionEngine.manual_attention_mode(item)=='OVERRIDE_ALLOWED'


def test_v1916_existing_dynamic_profile_migrates_password_zero_to_8():
    p={
        'dynamic_profile':True,'profile_status':'DRAFT','profile_version':'1.9.16','runtime_form_driven_version':'1.9.16',
        'live':{'required_items':['Variable: Password Format']},
        'rules':{'password_length':0},
        'golden_form_items':[
            {'form_no':8,'item':'Golden #8: Password','type':'Golden Variable','role':'WIFI','required':True,
             'raw_text':'Password: Random 8 characters (不可使用 MAC or SN 任一部分) (生管提供)',
             'engine_items':['Variable: Password Format'],'presence_item':'','manual_review_allowed':True},
        ],
        'dynamic_standard_items':[],
        'golden_completeness':{'document_item_count':1,'profile_item_count':1,'document_item_numbers':[8],'missing_item_numbers':[]},
        'golden_item_bindings':{'Variable: Password Format':8},
    }
    out,changed,_=normalize_dynamic_profile_for_runtime(p)
    assert changed
    assert out['rules']['password_length']==8


def test_cross_image_identity_mismatch_has_manual_completion_path(tmp_path):
    eng=object.__new__(MultiImageInspectionEngine)
    eng.profile={'live':{'required_items':[]}}
    eng._required_items=lambda:[]
    eng._write_excel=lambda result, expected: str(tmp_path/'report.xlsx')
    r=MultiImageResult(session_id='idm',session_dir=str(tmp_path),identity_status='MISMATCH',overall='IDENTITY_MISMATCH',automatic_overall='IDENTITY_MISMATCH')
    out=eng.apply_manual_pass(r,[IDENTITY_REVIEW_ITEM],'Operator checked all identity values against Golden/device label')
    assert out.automatic_overall=='IDENTITY_MISMATCH'
    assert out.manual_overrides[IDENTITY_REVIEW_ITEM]['auto_result']=='IDENTITY_MISMATCH'
    assert out.overall=='PASS_WITH_MANUAL_REVIEW'
