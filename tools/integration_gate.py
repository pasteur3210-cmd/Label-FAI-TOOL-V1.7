from __future__ import annotations

"""V1.9.8 integration gate.

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
    ce = next(r for r in rows if r['form_no'] == 4)
    check(ce['required'] is False, 'CE ■ No checkbox did not remain Not Required')

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

    result = {x.name: x for x in validate(fields, profile, {'pn': '740114-001', 'made_in': 'Taiwan'})}
    for name in ('Fixed: model', 'Variable: P/N Format', 'Variable: S/N Human Readable Format',
                 'Variable: S/N Barcode Format', 'Consistency: S/N Text vs Barcode',
                 'Variable: MAC Human Readable Format', 'Variable: MAC Barcode Format',
                 'Consistency: MAC Text vs Barcode', 'Variable: SSID Format',
                 'Variable: WiFi Key Format', 'Variable: WiFi QR Format'):
        check(name in result and result[name].status == 'PASS', f'Runtime replay failed: {name}')

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

    # 7) Profile/Golden switch must clear rendered Image evidence so an old
    # session cannot be reviewed under a newly loaded Golden.
    check('IMAGE_SESSION_INVALIDATED' in app, 'Profile/Golden change does not invalidate previous Image result')

    # 8) Re-importing the same Golden identity must replace, not merge, the
    # asset directory. This prevents old embedded label images being shown in
    # Golden-assisted Manual Review.
    gp=(ROOT/'label_tool/core/golden_profile_manager.py').read_text(encoding='utf-8')
    check('__incoming_' in gp and 'backup=root.parent' in gp, 'Transactional Golden asset replacement guard missing')

    print('[INTEGRATION_GATE][PASS] Golden completeness, dynamic runtime, unique profile identity, all-non-PASS review, stale-Golden isolation')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
