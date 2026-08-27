from label_tool.core import golden_profile_manager as gpm

SAMPLE = '''
Chassis Label Request Form
PAK Name: GRG-4366u-CTU-P1
1. Comtrend Logo：■ Yes □ No
2. FCC Mark：■ Yes □ No
3. WEEE Mark：■ Yes □ No
4. CE Mark：□ Yes ■ No
5. Product (必填)：Home Gateway
6. Model Name (必填)：□ (康全) GRG-4366u ■ (客戶) GRG-4366
7. Part No.：■ Yes, 7XXXXX-XXX □ No
8. Input：12 VDC 3A
9. USB 3.0: 5V 900mA
10. S/N Number (including Barcode)：■ Comtrend (20碼) □ Customer
Barcode Type：Code type：128 Checking code：1
11. MAC Number (including Bar code)：■ Yes □ No
12. GPON SN：CMTD + MAC 後八碼
13. SSID
ComtrendXXXX_2.4GHz = Comtrend + last 4 characters of MAC address_2.4GHz
14. Encryption Type = WPA2-PSK
15. WiFi Key: Random 10 digits
16. Made in Taiwan/China
17. Add IC mark
18. Add UL file listing number E203979
19. Add
FCC ID: L9VGRG4366
US: 4013A-GRG4366
20. QR Code：含 SN、MAC、WiFi Key for 測試刷入使用
Finished Information:
1. Blank Label Part Number：502109-024
'''

def test_numbered_golden_parser_keeps_all_20_items_and_qr():
    rows=gpm.extract_golden_form_items(SAMPLE)
    assert [r['form_no'] for r in rows] == list(range(1,21))
    qr=next(r for r in rows if r['form_no']==20)
    assert qr['type']=='Golden QR'
    assert 'Variable: WiFi QR Format' in qr['engine_items']
    assert qr['required'] is True


def test_checkbox_yes_no_is_preserved_not_dropped():
    rows=gpm.extract_golden_form_items(SAMPLE)
    assert next(r for r in rows if r['form_no']==1)['required'] is True
    ce=next(r for r in rows if r['form_no']==4)
    assert ce['required'] is False
    assert ce['selected']=='NO'


def test_unknown_numbered_item_remains_needs_review():
    rows=gpm.extract_golden_form_items('1. Completely New Factory Symbol: ABC\nFinished Information:')
    assert len(rows)==1
    assert rows[0]['type']=='Needs Review'
    assert rows[0]['review_status']=='NEEDS_REVIEW'


def test_profile_editor_shows_golden_plus_explicit_library_only():
    p={'live':{'required_items':[]},'image_inspection':{'role_items':{}},'golden_form_items':gpm.extract_golden_form_items(SAMPLE),
       'dynamic_standard_items':[{'item':'Variable: Password Format','type':'Standard','role':'WIFI','required':True,'origin':'AUTO_GOLDEN'},
                                 {'item':'Consistency: QR Key vs Printed WiFi Key','type':'Standard','role':'WIFI','required':True,'origin':'STANDARD_LIBRARY'}]}
    rows=gpm._dynamic_item_rows(p)
    names={r['item'] for r in rows}
    assert any(x.startswith('Golden #20: QR') for x in names)
    assert 'Variable: Password Format' not in names
    assert 'Consistency: QR Key vs Printed WiFi Key' in names


def test_golden_rows_map_to_legacy_engine_without_duplicate_standard_display():
    p={'dynamic_profile':True,'live':{},'image_inspection':{},'profile_edit_log':[]}
    rows=gpm.extract_golden_form_items(SAMPLE)
    out=gpm.apply_editable_items(p,rows)
    req=set(out['live']['required_items'])
    assert 'Variable: WiFi QR Format' in req
    assert 'Variable: S/N Barcode Format' in req
    assert 'Variable: MAC Barcode Format' in req
    assert 'Variable: GPON S/N Barcode Format' in req
    shown=gpm._dynamic_item_rows(out)
    assert all(r.get('source')=='Golden' for r in shown)


def test_readiness_accepts_manual_path_for_unmapped_required_unknown():
    p={'dynamic_profile':True,'golden_form_items':[{'form_no':1,'item':'Golden #1: New Thing','type':'Needs Review','required':True,'engine_items':[],'manual_review_allowed':True}],
       'golden_completeness':{'document_item_count':1,'profile_item_count':1,'document_item_numbers':[1],'missing_item_numbers':[]}}
    assert gpm.validation_readiness_errors(p)==[]
    s=gpm.validation_readiness_summary(p)
    assert s['manual']==1 and s['missing']==0

def test_chassis_label_part_number_wins_over_blank_label_part_number():
    text='Blank Label Part Number：502109-024\nChassis Label Part Number：680010-371'
    assert gpm._candidate_label_pn(text)=='680010-371'

def test_app_has_standard_library_and_golden_assisted_manual_review():
    from pathlib import Path
    src=(Path(__file__).parents[1]/'label_tool'/'app.py').read_text(encoding='utf-8')
    assert 'From Standard Library / 既有檢查項目' in src
    assert 'Golden Reference / Golden 對照' in src
    assert '_show_manual_golden_review' in src
    assert 'Confirm PASS / 人工確認PASS' in src
