from pathlib import Path
from types import SimpleNamespace

from label_tool.core.models import InspectionResult
from label_tool.core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult, ImageEvidence


class FastFakeEngine(MultiImageInspectionEngine):
    def __init__(self, profile, software_version='1.8.2'):
        # Deliberately avoid OCR/artwork runtime construction in this architecture test.
        self.profile = profile
        self.software_version = software_version
        self.calls = []

    def _inspect_one(self, image_path, session_dir, expected, index, target_items=None):
        self.calls.append(Path(image_path).name)
        ev = ImageEvidence(
            item='Fixed: model', result='PASS', actual='GRG-4297u', expected='GRG-4297u',
            source_image=Path(image_path).name, quality_score=0.9, photo_role='DETAIL'
        )
        one = InspectionResult(overall='DETAIL', fields=[])
        return one, [ev], {}, 'DETAIL', {}, {}, {
            'raw_text':'', 'decoded_texts':[], 'sharpness':100.0, 'contrast':30.0, 'quality':0.9
        }

    def _write_excel(self, result, expected):
        return str(Path(result.session_dir) / 'fake.xlsx')


def _profile():
    return {
        'profile_name':'cache-test',
        'live':{'required_items':['Fixed: model']},
    }


def test_v182_second_run_skips_previously_analyzed_image(tmp_path):
    a = tmp_path/'a.jpg'; a.write_bytes(b'first-image')
    b = tmp_path/'b.jpg'; b.write_bytes(b'second-image')
    out = tmp_path/'records'

    first_engine = FastFakeEngine(_profile())
    first = first_engine.inspect_batch([str(a)], str(out), expected={})
    assert first_engine.calls == ['a.jpg']
    assert first.image_count == 1

    second_engine = FastFakeEngine(_profile())
    second = second_engine.inspect_batch(
        [str(a), str(b)], str(out), expected={}, previous_session=first,
        target_items={'Fixed: model'},
    )
    assert second_engine.calls == ['b.jpg']
    assert second.image_count == 2
    assert second.cache_hits >= 1
    perf = Path(second.session_dir, 'performance.log').read_text(encoding='utf-8')
    assert 'CACHE_HIT file=a.jpg' in perf
    assert 'action=SKIP_OCR' in perf


def test_v182_same_content_new_filename_is_cache_hit(tmp_path):
    a = tmp_path/'a.jpg'; a.write_bytes(b'same-content')
    b = tmp_path/'renamed.jpg'; b.write_bytes(b'same-content')
    out = tmp_path/'records'
    e1 = FastFakeEngine(_profile())
    first = e1.inspect_batch([str(a)], str(out), expected={})
    e2 = FastFakeEngine(_profile())
    second = e2.inspect_batch([str(b)], str(out), expected={}, previous_session=first, target_items={'Fixed: model'})
    assert e2.calls == []
    assert second.image_count == 1
    assert second.cache_hits >= 1


def test_v182_cache_context_rejects_profile_or_work_order_change(tmp_path):
    a = tmp_path/'a.jpg'; a.write_bytes(b'first')
    out = tmp_path/'records'
    e1 = FastFakeEngine(_profile())
    first = e1.inspect_batch([str(a)], str(out), expected={'pn':'A'})
    e2 = FastFakeEngine(_profile())
    try:
        e2.inspect_batch([str(a)], str(out), expected={'pn':'B'}, previous_session=first, target_items={'Fixed: model'})
    except ValueError as exc:
        assert 'cache context changed' in str(exc).lower()
    else:
        raise AssertionError('cache context mismatch must invalidate the session')


def test_v182_empty_targets_after_pass_uses_early_stop_for_new_image(tmp_path):
    a = tmp_path/'a.jpg'; a.write_bytes(b'first')
    b = tmp_path/'b.jpg'; b.write_bytes(b'new-after-pass')
    out = tmp_path/'records'
    e1 = FastFakeEngine(_profile())
    first = e1.inspect_batch([str(a)], str(out), expected={})
    assert first.overall == 'PASS'
    e2 = FastFakeEngine(_profile())
    second = e2.inspect_batch([str(a), str(b)], str(out), expected={}, previous_session=first, target_items=set())
    assert e2.calls == []
    assert second.image_count == 2
    assert second.photo_roles['b.jpg'] == 'SKIPPED_AFTER_PASS'
    perf = Path(second.session_dir, 'performance.log').read_text(encoding='utf-8')
    assert 'EARLY_PASS file=b.jpg' in perf


def test_v182_app_run_path_reuses_previous_session_and_has_force_button():
    src = Path('label_tool/app.py').read_text(encoding='utf-8')
    block = src[src.index('def inspect_images(self):'):src.index('def recheck_unresolved(self):')]
    assert 'previous_session=self.multi_image_result' in block
    assert 'target_items=targets' in block
    assert 'def force_reanalyze_images(self):' in block
    assert 'Force Re-analyze All' in src


def test_v182_manual_override_keeps_automatic_result_separate(tmp_path):
    a = tmp_path/'a.jpg'; a.write_bytes(b'first')
    b = tmp_path/'b.jpg'; b.write_bytes(b'new')
    out = tmp_path/'records'
    profile = {'profile_name':'manual-test','live':{'required_items':['Fixed: model']}}
    e1 = FastFakeEngine(profile)
    first = e1.inspect_batch([str(a)], str(out), expected={})
    # Simulate a visual-item machine miss and a traceable manual PASS.
    first.evidence['Fixed: model'] = ImageEvidence('Fixed: model','NEED_MORE_IMAGE',source_image='a.jpg')
    first.unresolved_items = ['Fixed: model']
    first.overall = 'NEED_MORE_IMAGE'
    first.automatic_overall = 'NEED_MORE_IMAGE'
    first.manual_overrides['Fixed: model'] = {
        'timestamp':'2026-08-25T13:00:00', 'auto_result':'NEED_MORE_IMAGE',
        'final_result':'MANUAL_PASS', 'note':'visual confirmed'
    }
    first.evidence['Fixed: model'] = ImageEvidence('Fixed: model','MANUAL_PASS',actual='Present',source_image='MANUAL_REVIEW')
    first.unresolved_items = []
    first.overall = 'PASS_WITH_MANUAL_REVIEW'

    e2 = FastFakeEngine(profile)
    second = e2.inspect_batch([str(a), str(b)], str(out), expected={}, previous_session=first, target_items=set())
    assert second.overall == 'PASS_WITH_MANUAL_REVIEW'
    assert second.automatic_overall == 'NEED_MORE_IMAGE'
    assert second.manual_overrides['Fixed: model']['auto_result'] == 'NEED_MORE_IMAGE'
