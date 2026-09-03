from pathlib import Path
import tempfile

from label_tool.core.multi_image_inspection import (
    MultiImageInspectionEngine, MultiImageResult, ImageEvidence,
    profile_supports_work_order_field,
)


def carton_profile():
    return {
        'profile_name':'GRG-4297u Carton Label', 'model':'GRG-4297u',
        'label_type':'Carton Label', 'label_pn':'680010-354',
        'dynamic_profile':True,
        'live':{'required_items':['Fixed: model','Variable: P/N Format']},
        'golden_form_items':[
            {'item':'Model: GRG-4297u','raw_text':'3. Model: GRG-4297u','engine_items':['Fixed: model']},
            {'item':'P/N: 738125-00X','raw_text':'4. P/N: 738125-00X','engine_items':['Variable: P/N Format']},
            {'item':'C/T S/N','raw_text':'7. C/T S/N: Carton Serial Number (including Barcode)','engine_items':['Variable: S/N Barcode Format']},
        ],
    }


def test_carton_scope_disables_mac_but_keeps_serial_number_scope():
    p=carton_profile()
    assert profile_supports_work_order_field(p,'mac') is False
    assert profile_supports_work_order_field(p,'sn') is True


def test_required_items_do_not_leak_mac_checks_from_gui_expected():
    e=MultiImageInspectionEngine(carton_profile(),'1.9.24')
    e._active_expected={'sn_range_enabled':False,'mac_range_enabled':True,'mac_step_enabled':True}
    req=e._required_items()
    assert 'Work Order: MAC Range' not in req
    assert 'Work Order: MAC Allocation Step' not in req


def test_expected_work_order_is_scope_sanitized():
    e=MultiImageInspectionEngine(carton_profile(),'1.9.24')
    scoped=e._scope_expected_work_order({'mac_range_enabled':True,'mac_step_enabled':True,'mac_start':'AA','mac_end':'FF','mac_step':'10'})
    assert scoped['mac_range_enabled'] is False
    assert scoped['mac_step_enabled'] is False


def test_excel_uses_final_and_pre_manual_labels_and_excludes_out_of_scope_mac():
    import zipfile
    p=carton_profile(); e=MultiImageInspectionEngine(p,'1.9.24')
    with tempfile.TemporaryDirectory() as td:
        r=MultiImageResult(overall='PASS_WITH_MANUAL_REVIEW',automatic_overall='NEED_MORE_IMAGE',session_id='t',session_dir=td)
        r.evidence={'Fixed: model':ImageEvidence('Fixed: model','PASS','GRG-4297u','GRG-4297u','a.jpg',1.0,'','','FULL')}
        e._active_expected={'mac_range_enabled':False,'mac_step_enabled':False}
        path=e._write_excel(r, e._scope_expected_work_order({'mac_range_enabled':True,'mac_step_enabled':True}))
        with zipfile.ZipFile(path) as z:
            shared=z.read('xl/sharedStrings.xml').decode('utf-8')
        assert 'Final Result' in shared
        assert 'Auto Result Before Manual Review' in shared
        assert 'Work Order: MAC Allocation Step' not in shared
        assert 'Work Order: MAC Range' not in shared


def test_app_has_scope_driven_disabled_checkboxes():
    s=(Path(__file__).resolve().parents[1]/'label_tool/app.py').read_text(encoding='utf-8')
    assert 'def _apply_work_order_scope_ui' in s
    assert 'self.mac_range_check' in s and 'self.mac_step_check' in s
    assert 'state="normal" if enabled else "disabled"' in s
