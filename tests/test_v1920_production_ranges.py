from pathlib import Path

from label_tool.core.production_range import check_serial_range, check_mac_range, check_mac_allocation
from label_tool.core.rules import validate
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine


def _profile():
    return {
        'rules': {
            'sn_regex': r'[0-9A-Z-]{12,32}', 'sn_display':'Dynamic S/N',
            'mac_regex': r'[0-9A-F]{12}', 'gpon_regex': r'434D5444[0-9A-F]{8}',
            'password_length':8, 'wifi_key_length':14,
        },
        'fixed_fields': {},
        'live': {'required_items': [
            'Variable: S/N Human Readable Format','Variable: S/N Barcode Format',
            'Variable: MAC Human Readable Format','Variable: MAC Barcode Format',
        ]},
    }


def test_sn_range_numeric_tail_pass_and_fail():
    ok, _ = check_serial_range('2638043UXXF-AN000038','2638043UXXF-AN000001','2638043UXXF-AN000500')
    assert ok is True
    ok, _ = check_serial_range('2638043UXXF-AN000732','2638043UXXF-AN000001','2638043UXXF-AN000500')
    assert ok is False


def test_mac_range_uses_hex_numeric_comparison():
    ok, _ = check_mac_range('A01842EA8609','A01842EA8000','A01842EA8FFF')
    assert ok is True
    ok, _ = check_mac_range('A01842EA9000','A01842EA8000','A01842EA8FFF')
    assert ok is False


def test_mac_allocation_step_and_quantity_boundary():
    # Step 10 means valid base MACs are start + N*10, and each unit consumes 10 MACs.
    assert check_mac_allocation('A01842EA800A','A01842EA8000','A01842EA8FFF',10)[0] is True
    assert check_mac_allocation('A01842EA800B','A01842EA8000','A01842EA8FFF',10)[0] is False
    # An aligned base that would allocate past End must fail.
    assert check_mac_allocation('A01842EA8FFA','A01842EA8000','A01842EA8FFF',10)[0] is False


def test_rule_engine_emits_work_order_range_results():
    fields={
        'sn_text':'2638043UXXF-AN000038','sn_barcode':'2638043UXXF-AN000038',
        'mac_text':'A01842EA800A','mac_barcode':'A01842EA800A',
    }
    expected={
        'sn_range_enabled':True,'sn_start':'2638043UXXF-AN000001','sn_end':'2638043UXXF-AN000500',
        'mac_range_enabled':True,'mac_start':'A01842EA8000','mac_end':'A01842EA8FFF',
        'mac_step_enabled':True,'mac_step':'10',
    }
    rows={r.name:r for r in validate(fields,_profile(),expected)}
    assert rows['Work Order: S/N Range'].status=='PASS'
    assert rows['Work Order: MAC Range'].status=='PASS'
    assert rows['Work Order: MAC Allocation Step'].status=='PASS'


def test_range_failure_is_traceable_not_silent():
    fields={'sn_text':'2638043UXXF-AN000900','sn_barcode':'2638043UXXF-AN000900','mac_text':'A01842EA9000','mac_barcode':'A01842EA9000'}
    expected={'sn_range_enabled':True,'sn_start':'2638043UXXF-AN000001','sn_end':'2638043UXXF-AN000500',
              'mac_range_enabled':True,'mac_start':'A01842EA8000','mac_end':'A01842EA8FFF'}
    rows={r.name:r for r in validate(fields,_profile(),expected)}
    assert rows['Work Order: S/N Range'].status=='FAIL'
    assert rows['Work Order: S/N Range'].error_code=='WO-SN-RANGE'
    assert rows['Work Order: MAC Range'].status=='FAIL'
    assert rows['Work Order: MAC Range'].error_code=='WO-MAC-RANGE'


def test_multi_image_required_items_follow_enabled_production_gates():
    eng=MultiImageInspectionEngine(_profile(),'1.9.20')
    eng._active_expected={'sn_range_enabled':True,'mac_range_enabled':True,'mac_step_enabled':True}
    req=eng._required_items()
    assert 'Work Order: S/N Range' in req
    assert 'Work Order: MAC Range' in req
    assert 'Work Order: MAC Allocation Step' in req


def test_gui_source_contains_production_range_controls_and_live_fail_path():
    app=(Path(__file__).resolve().parents[1]/'label_tool/app.py').read_text(encoding='utf-8')
    for token in ('S/N Start','S/N End','Check S/N Range','MAC Start','MAC End','MAC Qty / Step','Check MAC Range','Check MAC Allocation Step'):
        assert token in app
    assert 'DERIVED_RULE_FAIL' in app
