from pathlib import Path
import zipfile

from label_tool.core import golden_profile_manager as gpm
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult


def _box(y0,y1,x0=20,x1=300):
    return [[x0,y0],[x1,y0],[x1,y1],[x0,y1]]


def test_grg4297_later_test_programming_qr_is_reference_only_when_shipping_qr_already_defined():
    text='''
1. Comtrend logo
2. GPON VoIP Gateway
3. Model: GRG-4297u
4. P/N: 738125-00X
5. Input: 12V 1.5A
6. IP Address: 192.168.1.1
7. Username: user
8. Password: Random 8 characters
9. SSID=Telekom Slovenije_XXXXXX
10. WiFi Key: Random 14 碼
Barcode type：QR Code
QR Code內容: WIFI:T:WPA;S:SSID;P:WiFi Key;;
11. S/N: YYM4297UF-FFXXXXXX
12. MAC: Comtrend mac address
13. GPON S/N: 434D5444XXXXXXXX
14. Made in China/Taiwan
15. Company address
16. 安規Logo
17. Reserved
18. Password proposal reference
19. QR Code for測試刷入使用，內容含SN、MAC、Password、WiFi Key
20. 匯入列印方式參考
Finished Information:
'''
    rows=gpm.extract_golden_form_items(text)
    # No outside-QR evidence is needed for this deterministic Request-Form case.
    gpm._apply_chassis_scope_filter(rows,Path('final.png'),[],[])
    r10=next(r for r in rows if r.get('form_no')==10)
    r19=next(r for r in rows if r.get('form_no')==19)
    assert r10['inspection_scope']=='CHASSIS_LABEL'
    assert r10['required'] is True
    assert r19['inspection_scope']=='REFERENCE_ONLY'
    assert r19['required'] is False
    assert r19['engine_items']==[]
    assert r19['presence_item']==''
    assert 'shipped-label QR is already defined earlier' in r19['scope_reason']


def test_vg8043_only_qr_remains_runtime_even_when_wording_says_test_programming():
    text='''
1. Comtrend Logo：■ Yes
2. FCC Mark：■ Yes
3. WEEE Mark：■ Yes
4. CE Mark：■ No
5. Product：Home Gateway
6. Model Name：PRT-7302
7. Part No.：7XXXXX-XXX
8. Input：12 VDC 3A
9. USB 3.0: 5V 900mA
10. S/N Number (including Barcode)：Comtrend
11. MAC Number (including Bar code)：Yes
12. SSID ComtrendXXXX
13. Encryption Type = WPA3 Transition
14. WiFi Key: Random 10 digits
15. Made in Taiwan/China
16. Add IC mark
17. Add UL file listing number E203979
18. Add FCC ID and IC ID
19. QR Code：含SN、MAC、WiFi Key for 測試刷入使用 (生管提供)
Finished Information:
'''
    rows=gpm.extract_golden_form_items(text)
    gpm._apply_chassis_scope_filter(rows,Path('final.png'),[],[])
    r19=next(r for r in rows if r.get('form_no')==19)
    assert r19['inspection_scope']=='CHASSIS_LABEL'
    assert r19['required'] is True


def test_record_prefix_contains_model_label_type_and_label_pn():
    eng=MultiImageInspectionEngine({
        'model':'GRG-4297u','label_type':'Chassis Label','label_pn':'680010-378',
        'live':{'required_items':[]},'rules':{'sn_regex':'.*'},
    }, software_version='1.9.21')
    assert eng._record_prefix()=='GRG-4297u_Chassis_Label_680010-378'


def test_excel_filename_and_summary_include_traceable_golden_metadata(tmp_path):
    profile={
        'profile_name':'GRG-4297u Chassis Label [680010-378]',
        'model':'GRG-4297u','label_type':'Chassis Label','label_pn':'680010-378',
        'profile_version':'1.9.19',
        'golden_import':{'source_file':'680010-378 GRG-4297u-TSL-P1 738125-001 Chassis Label.doc'},
        'live':{'required_items':[]},'rules':{'sn_regex':'.*'},
    }
    eng=MultiImageInspectionEngine(profile, software_version='1.9.21')
    r=MultiImageResult(session_id='20260902_170000_abc123',session_dir=str(tmp_path),overall='PASS',automatic_overall='PASS')
    path=Path(eng._write_excel(r,{}))
    assert path.name=='GRG-4297u_Chassis_Label_680010-378_Image_Inspection_Report_20260902_170000_abc123.xlsx'
    with zipfile.ZipFile(path) as z:
        text='\n'.join(z.read(n).decode('utf-8','ignore') for n in z.namelist() if n.endswith('.xml'))
    for token in ('Request Form','Program Version','Profile Version','680010-378 GRG-4297u-TSL-P1 738125-001 Chassis Label.doc','1.9.21','1.9.19'):
        assert token in text


def test_named_log_aliases_are_created_without_breaking_canonical_internal_files(tmp_path):
    profile={'model':'GRG-4297u','label_type':'Chassis Label','label_pn':'680010-378','live':{'required_items':[]},'rules':{'sn_regex':'.*'}}
    eng=MultiImageInspectionEngine(profile,'1.9.21')
    sid='20260902_170000_abc123'
    r=MultiImageResult(session_id=sid,session_dir=str(tmp_path))
    for name in ('execution.log','test.log','debug.log','performance.log','result.json'):
        (tmp_path/name).write_text(name,encoding='utf-8')
    eng._sync_named_records(r)
    prefix='GRG-4297u_Chassis_Label_680010-378'
    for kind in ('Execution_Log','Test_Log','Debug_Log','Performance_Log'):
        assert (tmp_path/f'{prefix}_{kind}_{sid}.log').exists()
    assert (tmp_path/f'{prefix}_Result_{sid}.json').exists()
