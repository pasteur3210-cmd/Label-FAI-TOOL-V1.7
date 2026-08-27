from pathlib import Path

from label_tool.core import golden_profile_manager as gpm
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine
from label_tool.core.models import FieldResult


def test_form_barcode_and_qr_always_get_presence_items():
    rows=gpm.extract_golden_form_items('''
1. S/N Number (including Barcode)：■ Comtrend (20 碼) □ Customer
2. MAC Number (including Bar code)：■ Yes □ No
3. QR Code：■ Yes □ No
Finished Information:
''')
    assert all(r.get('presence_item') for r in rows)
    assert rows[0]['type']=='Golden Barcode'
    assert rows[2]['type']=='Golden QR'
    p={'dynamic_profile':True,'live':{},'image_inspection':{},'profile_edit_log':[]}
    out=gpm.apply_editable_items(p,rows)
    req=set(out['live']['required_items'])
    assert rows[0]['presence_item'] in req
    assert rows[1]['presence_item'] in req
    assert rows[2]['presence_item'] in req


def test_qr_or_barcode_without_payload_rule_is_not_bypassable():
    p={'dynamic_profile':True,'golden_form_items':[{
        'form_no':None,'item':'Golden Visual QR #1','type':'Golden QR','required':True,
        'engine_items':[],'presence_item':'Golden Machine Code: QR Visual #1','manual_review_allowed':True,
    }], 'golden_completeness':{'document_item_count':0,'missing_item_numbers':[]}}
    errs=gpm.validation_readiness_errors(p)
    assert not any('machine-code presence/review path' in e for e in errs)


def test_dynamic_full_path_isolated_from_legacy_base_inspection_source():
    src=(Path(__file__).parents[1]/'label_tool'/'core'/'multi_image_inspection.py').read_text(encoding='utf-8')
    assert 'if role == "FULL" and not self.profile.get("dynamic_profile"):' in src
    assert 'Dynamic Golden profiles must NOT execute a seed model' in src


def test_session_raw_fields_keep_qr_sn_and_mac_for_qr_fusion():
    src=(Path(__file__).parents[1]/'label_tool'/'core'/'multi_image_inspection.py').read_text(encoding='utf-8')
    raw=src[src.index('RAW_FIELD_KEYS = ['):src.index(']\n\n\n@dataclass',src.index('RAW_FIELD_KEYS = ['))+1]
    assert '"qr_sn"' in raw and '"qr_mac"' in raw


def test_dynamic_text_has_containment_and_token_match_before_fuzzy_only():
    src=(Path(__file__).parents[1]/'label_tool'/'core'/'multi_image_inspection.py').read_text(encoding='utf-8')
    fn=src[src.index('    def _dynamic_rows'):src.index('    def _inspect_one')]
    assert 'containment=bool' in fn
    assert 'token_hit=bool' in fn
    assert 'containment or token_hit or score >= threshold' in fn


def test_manual_review_has_item_aware_golden_region_helper():
    src=(Path(__file__).parents[1]/'label_tool'/'app.py').read_text(encoding='utf-8')
    assert 'def _golden_review_region(self, item: str)' in src
    assert 'machine_codes' in src
    assert 'image_ocr_results' in src
    assert 'Golden item location not verified; showing full Golden image' in src
    assert 'Full Golden / 完整Golden' in src
    assert 'Focus Item / 項目放大' in src
    assert "render_golden(None,'Full Golden reference',golden_crop)" in src


def test_actual_field_record_qr_session_fusion_stays_pass_when_qr_facts_preserved(tmp_path):
    from label_tool.core.golden_profile_manager import _rules_from_golden_text
    from label_tool.core.multi_image_inspection import MultiImageResult, ImageEvidence
    golden='''
10. S/N Number (including Barcode)：■ Comtrend (20 碼) □ Customer
12. SSID\nComtrendXXXX\nXXXX= last 4 digits of MAC
14. WiFi Key: Random 10 digits
19. QR Code：含 SN、MAC、WiFi Key for 測試刷入使用
'''
    profile={
        'dynamic_profile':True,
        'model':'VG-8043u','model_aliases':['VG-8043u','PRT-7302'],'fixed_fields':{'model':'VG-8043u'},
        'rules':_rules_from_golden_text(golden),
        'live':{'required_items':['Variable: WiFi QR Format']},
        'image_inspection':{'role_items':{}},
    }
    eng=MultiImageInspectionEngine(profile,'1.9.11')
    r=MultiImageResult(overall='NEED_MORE_IMAGE',session_id='x',session_dir=str(tmp_path))
    r.session_fields={
        'wifi_qr':'S/N: 2638043UXXF-AN000038MAC: A01842EA8609WPA: KAG7dcsyJ7',
        'qr_sn':'2638043UXXF-AN000038','qr_mac':'A01842EA8609','qr_wifi_key':'KAG7dcsyJ7',
        'sn_text':'2638043UXXF-AN000038','mac_text':'A01842EA8609','wifi_key':'KAG7dcsyJ7',
    }
    best={}; conflicts={}
    eng._merge_session_rules(r,{},best,conflicts)
    assert not conflicts
    assert best['Variable: WiFi QR Format'].result=='PASS'


def test_dynamic_filter_statement_prevents_legacy_residue_in_evidence_pipeline():
    src=(Path(__file__).parents[1]/'label_tool'/'core'/'multi_image_inspection.py').read_text(encoding='utf-8')
    assert 'dynamic_required=set(self._required_items())' in src
    assert 'direct_rows=[r for r in direct_rows if r.name in dynamic_required]' in src
