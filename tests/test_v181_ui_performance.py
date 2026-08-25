from pathlib import Path
from types import SimpleNamespace

from label_tool.core.multi_image_inspection import MultiImageInspectionEngine


def test_v181_manual_review_panel_is_built_before_expandable_results_table():
    src = Path('label_tool/app.py').read_text(encoding='utf-8')
    start = src.index('def _build_image_tab')
    end = src.index('def _reload_profiles', start)
    block = src[start:end]
    assert block.index('Manual Review / 人工目檢輔助') < block.index('results=ttk.Frame(right)')
    assert 'yscrollcommand=manual_scroll.set' in block
    assert 'xscrollcommand=tree_x.set' in block


def test_v181_visual_compliance_override_returns_cache_for_reuse():
    engine = MultiImageInspectionEngine.__new__(MultiImageInspectionEngine)
    engine._role_items = lambda: {
        'COMPLIANCE': {'Artwork: CE Mark', 'Artwork: WEEE Mark', 'Artwork: RoHS Mark'}
    }

    calls = {'count': 0}

    class FakeArtwork:
        def evaluate_shape_only(self, image, requested_items=None):
            calls['count'] += 1
            dets = [
                SimpleNamespace(item='Artwork: CE Mark', shape_state='PASS'),
                SimpleNamespace(item='Artwork: WEEE Mark', shape_state='PASS'),
                SimpleNamespace(item='Artwork: RoHS Mark', shape_state='VERIFY'),
            ]
            return [], dets

    engine.artwork = FakeArtwork()
    role, dets, req = engine._visual_compliance_override_cached(object(), 'IDENTITY')
    assert role == 'COMPLIANCE'
    assert calls['count'] == 1
    assert len(dets) == 3
    assert set(req) == {'Artwork: CE Mark', 'Artwork: WEEE Mark', 'Artwork: RoHS Mark'}
