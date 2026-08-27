from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from label_tool.app import App


def _app_with_profile(profile, evidence=None):
    app = object.__new__(App)
    app.multi_image_engine = SimpleNamespace(profile=profile)
    app.multi_image_result = SimpleNamespace(evidence=evidence or {})
    return app


def test_artwork_never_borrows_text_ocr_roi(tmp_path):
    golden = tmp_path / 'golden.png'
    Image.new('RGB', (1000, 600), 'white').save(golden)
    profile = {
        'golden_import': {
            'candidate_layout_image': str(golden),
            # Deliberately place a misleading WiFi OCR box. In V1.9.11 an
            # Artwork item could incorrectly borrow this text ROI.
            'image_ocr_results': [{
                'file': str(golden),
                'lines': [{'text': 'WiFi Key: ABCD SSID: Comtrend1234',
                           'box': [[600, 300], [900, 300], [900, 380], [600, 380]]}],
            }],
        },
        'golden_form_items': [{
            'item': 'Golden #1: Comtrend Logo',
            'type': 'Golden Artwork',
            'engine_items': ['Artwork: COMTREND Logo'],
        }],
    }
    app = _app_with_profile(profile)
    path, crop, note = app._golden_review_region('Artwork: COMTREND Logo')
    assert Path(path) == golden
    assert crop is None
    assert 'full Golden' in note


def test_artwork_focus_only_when_explicit_verified_roi_exists(tmp_path):
    golden = tmp_path / 'golden.png'
    Image.new('RGB', (1000, 600), 'white').save(golden)
    profile = {
        'golden_import': {'candidate_layout_image': str(golden)},
        'golden_form_items': [{
            'item': 'Golden #1: Comtrend Logo',
            'type': 'Golden Artwork',
            'engine_items': ['Artwork: COMTREND Logo'],
            'artwork_review_roi': [0.05, 0.05, 0.35, 0.20],
        }],
    }
    app = _app_with_profile(profile)
    path, crop, note = app._golden_review_region('Artwork: COMTREND Logo')
    assert Path(path) == golden
    assert crop == (50, 30, 350, 120)
    assert 'Verified Artwork ROI' in note


def test_golden_text_keeps_typed_ocr_focus(tmp_path):
    golden = tmp_path / 'golden.png'
    Image.new('RGB', (1000, 600), 'white').save(golden)
    profile = {
        'golden_import': {
            'candidate_layout_image': str(golden),
            'image_ocr_results': [{
                'file': str(golden),
                'lines': [{'text': 'Input: 12VDC 3A',
                           'box': [[150, 150], [400, 150], [400, 200], [150, 200]]}],
            }],
        },
        'golden_form_items': [{
            'item': 'Golden #8: Input', 'type': 'Golden Text',
            'expected': '12 VDC 3A', 'raw_text': '8. Input: 12 VDC 3A',
            'engine_items': [],
        }],
    }
    ev = {'Golden #8: Input': SimpleNamespace(actual='Input: 12VDC -3A C')}
    app = _app_with_profile(profile, ev)
    path, crop, note = app._golden_review_region('Golden #8: Input')
    assert Path(path) == golden
    assert crop is not None
    assert 'Golden OCR focus' in note


def test_manual_review_defaults_to_full_golden_and_has_optional_focus_controls():
    src = Path('label_tool/app.py').read_text(encoding='utf-8')
    fn = src[src.index('    def _show_manual_golden_review'):src.index('    def manual_review_selected')]
    assert "Full Golden / 完整Golden" in fn
    assert "Focus Item / 項目放大" in fn
    assert "render_golden(None,'Full Golden reference',golden_crop)" in fn
    assert 'golden_focus_allowed=bool(golden_crop)' in fn and "focus_btn.config(state='disabled')" in fn
