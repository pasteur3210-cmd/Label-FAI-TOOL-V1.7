from __future__ import annotations

"""V1.9.15 integration gate.

This gate protects the production Legacy CAM/Image engine while proving that
Dynamic Golden data reaches the runtime correctly and that operator Golden
comparison review is actually wired into the UI.
"""

import json
import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from label_tool.core.golden_profile_manager import (
    _rules_from_golden_text,
    apply_editable_items,
    extract_golden_form_items,
    validation_readiness_errors,
)
from label_tool.core.parser import merge_fields
from label_tool.core.profile_manager import _display_name
from label_tool.core.rules import validate
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult

GOLDEN = '''
Chassis Label Request Form
PAK Name: VG-8043u-CTU-P1
1. Comtrend Logo：■ Yes □ No
2. FCC Mark：■ Yes □ No
3. WEEE Mark：■ Yes □ No
4. CE Mark：□ Yes ■ No
5. Product (必填)：Home Gateway
6. Model Name (必填)：□ (康全) VG-8043u ■ (客戶) PRT-7302
7. Part No.：■ Yes, 7XXXXX-XXX □ No
8. Input：12 VDC 3A
9. USB 3.0: 5V 900mA
10. S/N Number (including Barcode)：■ Comtrend (20 碼) □ Customer
11. MAC Number (including Bar code)：■ Yes □ No
12. SSID
ComtrendXXXX
XXXX= last 4 digits of MAC
13. Encryption Type = WPA3 Transition
14. WiFi Key: Random 10 digits
15. Made in Taiwan/China
16. Add IC mark
17. Add UL file listing number E203979
18. Add FCC ID: L9VGRG4366 IC ID: 4013A-GRG4366
19. QR Code：含 SN、MAC、WiFi Key for 測試刷入使用
Finished Information:
1. Blank Label Part Number：502109-024
2. Chassis Label Part Number：680010-375
'''


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f'[INTEGRATION_GATE][FAIL] {msg}')


def main() -> int:
    # 1) Controlled Golden form must not lose any numbered inspection item.
    rows = extract_golden_form_items(GOLDEN)
    check([r['form_no'] for r in rows] == list(range(1, 20)), 'Golden numbered items 1..19 are incomplete')
    qr = next(r for r in rows if r['form_no'] == 19)
    check(qr['type'] == 'Golden QR', 'QR item is not classified as Golden QR')
    check(bool(qr.get('presence_item')), 'Golden QR has no mandatory presence/review item')
    check(all(bool(r.get('presence_item')) for r in rows if r.get('type')=='Golden Barcode'), 'Golden Barcode item can bypass presence/review')
    ce = next(r for r in rows if r['form_no'] == 4)
    check(ce['required'] is False, 'CE ■ No checkbox did not remain Not Required')


    # 1b) Cross-model form-driven regression: nested numbering must not create
    # fake inspection items; blank top-level items are retained; composite WiFi
    # Key + QR remains one form item with a mandatory QR review path.
    golden_4297 = '''
Label Request:
1. Comtrend logo
2. GPON VoIP Gateway
3. Model: GRG-4297u
4. P/N: 738125-00X
5. Input: 12V 1.5A
USB 2.0: 5V 500mA
6. IP Address: 192.168.1.1
7. Username: user
8. Password: Random 8 characters
1. nested password rule
2. nested password rule two
9. SSID=Telekom Slovenije_XXXXXX
10. WiFi Key: Random 14 碼
Barcode type：QR Code
QR Code內容: WIFI:T:WPA;S:SSID;P:WiFi Key;;
11. S/N: YYM4297UF-FFXXXXXX (18 characters)
Barcode type：Code 128
12. MAC: Comtrend mac address (一台10個MAC)
Barcode type：Code 128
13. GPON S/N: 434D5444XXXXXXXX (16 characters)
Barcode type：Code 128
14. Made in China/Taiwan
15. Comtrend Central Europe, s.r.o.
16. 安規Logo：
17.
18. password proposal reference
19. QR Code for test，內容含 SN、MAC、Password、WiFi Key
20. print-method reference
Finished Information:
'''
    r4297=extract_golden_form_items(golden_4297)
    check([r['form_no'] for r in r4297] == list(range(1,21)), 'GRG-4297 top-level form sequence 1..20 is incomplete')
    check('nested password rule' in r4297[7]['raw_text'], 'Nested rule numbering escaped parent item #8')
    check(r4297[9]['type']=='Golden Variable' and r4297[9].get('machine_code_field')=='qr', 'WiFi Key + QR composite item was misclassified')
    check(r4297[10].get('machine_code_field')=='sn', 'S/N barcode field mapping failed')
    check(r4297[11].get('machine_code_field')=='mac', 'MAC barcode field mapping failed')
    check(r4297[12].get('machine_code_field')=='gpon_sn', 'GPON barcode field mapping failed')
    check(r4297[16]['type']=='Needs Review', 'Blank controlled item #17 was bypassed')
    check(r4297[18]['type']=='Golden QR' and not r4297[18].get('machine_code_rule_known'), 'Unsupported Password-containing QR should require manual review')

    # 2) Golden-backed profile generation must be clean and runtime-oriented.
    rules = _rules_from_golden_text(GOLDEN)
    check(rules.get('wifi_key_length') == 10, 'WiFi Key length rule was not extracted')
    check(rules.get('ssid_prefix') == 'Comtrend', 'SSID prefix rule was not extracted')
    check(rules.get('ssid_mac_suffix_length') == 4, 'SSID MAC suffix rule was not extracted')
    check(rules.get('qr_payload_fields') == ['sn', 'mac', 'wifi_key'], 'QR payload fields were not extracted')

    profile = {
        'dynamic_profile': True,
        'profile_name': 'VG-8043u Chassis Label',
        'model': 'VG-8043u',
        'model_aliases': ['VG-8043u', 'PRT-7302'],
        'label_pn': '680010-375',
        'fixed_fields': {'model': 'VG-8043u'},
        'rules': rules,
        'live': {},
        'image_inspection': {},
        'profile_edit_log': [],
    }
    profile = apply_editable_items(profile, rows)
    check('Variable: WiFi QR Format' in profile['live']['required_items'], 'Golden QR did not map to runtime QR check')
    check('Variable: S/N Barcode Format' in profile['live']['required_items'], 'Golden S/N did not map to runtime barcode check')
    check('Variable: MAC Barcode Format' in profile['live']['required_items'], 'Golden MAC did not map to runtime barcode check')
    check(qr['presence_item'] in profile['live']['required_items'], 'Golden QR mandatory presence item was dropped')

    # 3) Dynamic parser replay of the real field pattern from the reported run.
    profile['rules']['pn_regex'] = r'[0-9A-Z-]{5,32}'
    ocr = ('COMTREND Home Gateway Model: PRT-7302 P/N: 740114-001 '
           'Input: 12VDC 3A USB 3.0: 5V 900mA Encryption Type = WPA3 Transition '
           'WiFi Key: KAG7dcsyJ7 SSID: Comtrend8609 '
           'S/N: 2638043UXXF-AN000038 MAC: A01842EA8609 Made in Taiwan')
    decoded = [
        'S/N: 2638043UXXF-AN000038MAC: A01842EA8609WPA: KAG7dcsyJ7',
        '2638043UXXF-AN000038', 'A01842EA8609', 'A018426A8627',
    ]
    fields = merge_fields(ocr, decoded, profile=profile)
    check(fields.get('model') == 'PRT-7302', 'Customer model alias was not accepted')
    check(fields.get('pn') == '740114-001', 'P/N was not parsed dynamically')
    check(fields.get('mac_barcode') == 'A01842EA8609', 'Spurious MAC barcode candidate overrode the human-matching candidate')
    check(fields.get('qr_wifi_key') == 'KAG7dcsyJ7', 'QR WiFi Key was not parsed')
    check(fields.get('qr_sn') == '2638043UXXF-AN000038', 'QR S/N was not normalized')
    check(fields.get('qr_mac') == 'A01842EA8609', 'QR MAC was not normalized')

    result = {x.name: x for x in validate(fields, profile, {'pn': '740114-001', 'made_in': 'Taiwan'})}
    for name in ('Fixed: model', 'Variable: P/N Format', 'Variable: S/N Human Readable Format',
                 'Variable: S/N Barcode Format', 'Consistency: S/N Text vs Barcode',
                 'Variable: MAC Human Readable Format', 'Variable: MAC Barcode Format',
                 'Consistency: MAC Text vs Barcode', 'Variable: SSID Format',
                 'Variable: WiFi Key Format', 'Variable: WiFi QR Format'):
        check(name in result and result[name].status == 'PASS', f'Runtime replay failed: {name}')

    # Field-record regression: session fusion must preserve normalized QR S/N +
    # MAC facts and must not turn a single-image QR PASS into a conflict.
    fusion_profile={**profile,'live':{'required_items':['Variable: WiFi QR Format']}}
    fusion=MultiImageInspectionEngine(fusion_profile,'1.9.15')
    mr=MultiImageResult(overall='NEED_MORE_IMAGE',session_id='gate',session_dir=tempfile.gettempdir())
    mr.session_fields={k:fields[k] for k in ('wifi_qr','qr_sn','qr_mac','qr_wifi_key','sn_text','mac_text','wifi_key') if k in fields}
    best={}; conflicts={}
    fusion._merge_session_rules(mr,{},best,conflicts)
    check(not conflicts, 'QR session fusion created a conflict from already normalized QR evidence')
    check(best.get('Variable: WiFi QR Format') and best['Variable: WiFi QR Format'].result=='PASS', 'QR session fusion did not stay PASS')

    # 4) Same model, different Golden P/N must have distinct UI keys.
    a = {'profile_name': 'VG-8043u Chassis Label', 'dynamic_profile': True, 'label_pn': '680010-367'}
    b = {'profile_name': 'VG-8043u Chassis Label', 'dynamic_profile': True, 'label_pn': '680010-375'}
    check(_display_name(a, Path('a.json')) != _display_name(b, Path('b.json')), 'Dynamic Profile display key collides across Golden P/Ns')

    # 5) Required unresolved/unknown Golden items must block Validate rather than disappear.
    unknown = {'dynamic_profile': True,
               'golden_form_items': [{'form_no': 1, 'item': 'Golden #1: Unknown Mark', 'type': 'Needs Review', 'required': True, 'engine_items': []}],
               'golden_completeness': {'document_item_count': 1, 'missing_item_numbers': []}}
    check(bool(validation_readiness_errors(unknown)), 'Required unknown Golden item did not block Validate')

    # 6) Manual review UI must visibly require Golden comparison before PASS,
    # and every non-PASS item must enter operator attention (review-only when
    # traceability data may not be overridden).
    app = (ROOT / 'label_tool' / 'app.py').read_text(encoding='utf-8')
    mi = (ROOT / 'label_tool' / 'core' / 'multi_image_inspection.py').read_text(encoding='utf-8')
    for token in ('Review with Golden / Golden對照復判', '_show_manual_golden_review',
                  'Golden Reference / Golden 對照', 'Actual / 實拍', 'Confirm PASS / 人工確認PASS',
                  'REVIEW ONLY', 'mode=self.multi_image_engine.manual_attention_mode(item)'):
        check(token in app, f'Manual Golden review/operator-attention wiring missing: {token}')
    for token in ('manual_attention_mode', 'manual_reviews', 'record_manual_review_action'):
        check(token in mi, f'Manual review traceability core missing: {token}')
    for token in ('_golden_review_region', 'machine_codes', 'image_ocr_results', 'Full Golden / 完整Golden', 'Focus Item / 項目放大'):
        check(token in app, f'Item-aware Golden review is missing: {token}')
    check('showing full Golden' in app and '_golden_review_artwork_marker' in app, 'Artwork fallback/marker safety is missing')
    check('artwork_review_roi' in app, 'Artwork focus is not restricted to an explicit verified ROI')
    check("render_golden(None,'Final Label / Full Golden reference',golden_crop)" in app, 'Manual Review does not start on the complete Final Label with current-item marker')
    check('REVIEW: {item}' in app and 'golden_focus_allowed=bool(golden_crop)' in app, 'Golden current-item highlight / safe Focus policy missing')
    check('Golden Item Specification / Golden 項目說明' in app and '_golden_item_specification' in app, 'Golden item-specific specification panel missing')
    check('if role == "FULL" and not self.profile.get("dynamic_profile"):' in mi, 'Dynamic FULL path can still execute Legacy seed inspection')
    check('direct_rows=[r for r in direct_rows if r.name in dynamic_required]' in mi, 'Dynamic evidence is not filtered to current Profile requirements')
    check('"qr_sn", "qr_mac"' in mi, 'QR normalized S/N/MAC facts are not persisted into session fusion')

    # 7) Profile/Golden switch must clear rendered Image evidence so an old
    # session cannot be reviewed under a newly loaded Golden.
    check('IMAGE_SESSION_INVALIDATED' in app, 'Profile/Golden change does not invalidate previous Image result')

    # 7b) V1.9.8 regression: Import Golden profile path resolution must not use
    # an undefined bare Path symbol (GitHub Ruff F821). app.py imports pathlib.
    check('imported_resolved=Path(path).resolve()' not in app, 'Undefined bare Path regression in Import Golden path resolution')
    check('if Path(pp).resolve() == imported_resolved:' not in app, 'Undefined bare Path regression in Profile lookup')
    check('pathlib.Path(path).resolve()' in app and 'pathlib.Path(pp).resolve()' in app, 'Import Golden path resolution is not explicitly namespaced')

    # 8) Re-importing the same Golden identity must replace, not merge, the
    # asset directory. This prevents old embedded label images being shown in
    # Golden-assisted Manual Review.
    gp=(ROOT/'label_tool/core/golden_profile_manager.py').read_text(encoding='utf-8')
    check('select_final_label_image' in gp and 'candidate_layout_policy' in gp, 'Final Label selector guard missing')
    check('__incoming_' in gp and 'backup=root.parent' in gp, 'Transactional Golden asset replacement guard missing')
    check('_detect_golden_machine_codes' in gp and 'Golden Machine Code:' in gp, 'Golden Barcode/QR non-bypass detector is missing')
    check('_docx_final_label_media_names' in gp and 'document:Label Example' in gp, 'Final Label structural document-position guard is missing')
    check('counters[key]=counters.get(key,0)+1' in gp, 'Word list-number reconstruction guard is missing')

    print('[INTEGRATION_GATE][PASS] form-driven multi-model completeness, barcode/QR non-bypass, dynamic isolation, QR fusion, item-aware review, stale-Golden isolation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
