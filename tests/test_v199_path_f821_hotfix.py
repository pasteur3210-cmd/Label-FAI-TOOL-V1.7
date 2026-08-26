from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_import_golden_profile_uses_resolved_path_without_undefined_Path_symbol():
    app = (ROOT / 'label_tool' / 'app.py').read_text(encoding='utf-8')
    assert 'imported_resolved=pathlib.Path(path).resolve()' in app
    assert 'if pathlib.Path(pp).resolve() == imported_resolved:' in app
    assert 'imported_resolved=Path(path).resolve()' not in app
    assert 'if Path(pp).resolve() == imported_resolved:' not in app
