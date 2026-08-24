from pathlib import Path


def test_multi_image_add_uses_existing_os_path_helper_not_undefined_path():
    source = Path('label_tool/app.py').read_text(encoding='utf-8')
    assert 'Path(self.image_paths[0]).name' not in source
    assert 'os.path.basename(self.image_paths[0])' in source
