from pathlib import Path
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult


def _engine():
    return MultiImageInspectionEngine({
        'model':'GRG-4297u','label_type':'Inner Box Label','label_pn':'502109-180',
        'profile_name':'GRG-4297u Inner Box Label [502109-180]',
        'live':{'required_items':[]},'rules':{'sn_regex':'.*'},
    }, '1.9.22')


def test_inner_record_names_do_not_repeat_trace_prefix(tmp_path):
    eng=_engine()
    sid='20260902_175755_968b82'
    session=tmp_path/f'{eng._record_prefix()}_{sid}'
    session.mkdir()
    r=MultiImageResult(session_id=sid,session_dir=str(session),overall='PASS',automatic_overall='PASS')
    report=Path(eng._write_excel(r,{}))
    assert report.name=='Inspection_Report.xlsx'
    assert eng._record_prefix() in session.name
    assert eng._record_prefix() not in report.name


def test_long_install_root_still_keeps_report_component_short(tmp_path):
    eng=_engine()
    sid='20260902_175755_968b82'
    root=tmp_path/('LabelFAI_' + 'X'*90)/('Release_' + 'Y'*70)/'image_records'
    session=root/f'{eng._record_prefix()}_{sid}'
    session.mkdir(parents=True)
    r=MultiImageResult(session_id=sid,session_dir=str(session),overall='PASS',automatic_overall='PASS')
    report=Path(eng._write_excel(r,{}))
    # The V1.9.21 failure repeated a ~60-char trace prefix in both folder and file.
    assert len(report.name) <= 40
    assert report.exists()


def test_named_aliases_are_short_inside_traceable_folder(tmp_path):
    eng=_engine(); sid='20260902_175755_968b82'
    session=tmp_path/f'{eng._record_prefix()}_{sid}'; session.mkdir()
    r=MultiImageResult(session_id=sid,session_dir=str(session))
    for name in ('execution.log','test.log','debug.log','performance.log','result.json'):
        (session/name).write_text('x',encoding='utf-8')
    eng._sync_named_records(r)
    expected={'Execution_Log.log','Test_Log.log','Debug_Log.log','Performance_Log.log','Result.json'}
    assert expected.issubset({p.name for p in session.iterdir()})
