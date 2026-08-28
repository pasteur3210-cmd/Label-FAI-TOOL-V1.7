import json
from pathlib import Path

from label_tool.core.models import FieldResult
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult, ImageEvidence


def load_chassis_profile():
    p = Path(__file__).resolve().parents[1] / 'label_tool' / 'profiles' / 'grg4297u_tsl_p1.json'
    return json.loads(p.read_text(encoding='utf-8'))


def test_gateway_fuzzy_phrase_rescue_from_original_ocr():
    engine = MultiImageInspectionEngine(load_chassis_profile(), software_version='1.8.0')
    rows = {
        'Fixed: GPON VoIP Gateway': FieldResult(
            name='Fixed: GPON VoIP Gateway', actual='', expected='Present in SPEC',
            status='WARN', message='Fixed text not recognized', error_code='OCR-FIXED'
        )
    }
    engine._rescue_fixed_phrase(
        rows,
        'COMTREND\nGPON VoIP Gatevvay\nModel: GRG-4297u',
        '',
        'Fixed: GPON VoIP Gateway',
        'GPON VoIP Gateway',
        [0, 0, 1, 1],
        0.72,
    )
    row = rows['Fixed: GPON VoIP Gateway']
    assert row.status == 'PASS'
    assert row.actual == 'Present'
    assert 'similarity=' in row.message


def test_manual_review_visual_item_is_traceable_and_identity_is_blocked(tmp_path):
    profile = {
        'profile_name': 'test',
        'label_type': 'Chassis Label',
        'live': {'required_items': ['Fixed: GPON VoIP Gateway']},
        'rules': {},
    }
    engine = MultiImageInspectionEngine(profile, software_version='1.8.0')
    result = MultiImageResult(
        overall='NEED_MORE_IMAGE', automatic_overall='NEED_MORE_IMAGE',
        session_id='T1', session_dir=str(tmp_path), image_count=1,
        identity_status='PASS', unresolved_items=['Fixed: GPON VoIP Gateway'],
        evidence={
            'Fixed: GPON VoIP Gateway': ImageEvidence(
                item='Fixed: GPON VoIP Gateway', result='NEED_MORE_IMAGE',
                expected='Present in SPEC', source_image='img1.jpg', quality_score=0.7,
                message='Fixed text not recognized'
            )
        },
    )
    result = engine.apply_manual_pass(result, ['Fixed: GPON VoIP Gateway'], 'Operator visual confirmed')
    assert result.overall == 'PASS_WITH_MANUAL_REVIEW'
    assert result.evidence['Fixed: GPON VoIP Gateway'].result == 'MANUAL_PASS'
    assert result.manual_overrides['Fixed: GPON VoIP Gateway']['auto_result'] == 'NEED_MORE_IMAGE'
    assert (tmp_path / 'execution.log').exists()
    assert (tmp_path / 'test.log').exists()
    assert (tmp_path / 'debug.log').exists()
    assert Path(result.report_path).exists()
    assert (tmp_path / 'result.json').exists()

    assert engine._manual_review_allowed('Fixed: GPON VoIP Gateway')
    assert engine._manual_review_allowed('Artwork: CE Mark')
    assert engine._manual_review_allowed('Variable: S/N Barcode Format')
    assert engine._manual_review_allowed('Consistency: S/N Text vs Barcode')
