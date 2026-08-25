from pathlib import Path


def test_multi_image_add_uses_existing_os_path_helper_not_undefined_path():
    source = Path('label_tool/app.py').read_text(encoding='utf-8')
    assert 'Path(self.image_paths[0]).name' not in source
    assert 'os.path.basename(self.image_paths[0])' in source

def test_v178_image_inspection_runs_in_background_worker_and_polls_queue():
    source = Path('label_tool/app.py').read_text(encoding='utf-8')
    assert "threading.Thread(target=worker,name='ImageInspectionWorker'" in source
    assert 'self.image_worker_queue.put(("result",result))' in source
    assert 'self.after(100,self._poll_image_worker)' in source


def test_v178_run_and_recheck_use_common_nonblocking_launcher():
    source = Path('label_tool/app.py').read_text(encoding='utf-8')
    assert "def _start_image_job" in source
    assert "def inspect_images(self):" in source
    inspect_block = source[source.index("def inspect_images(self):"):source.index("def recheck_unresolved(self):")]
    assert "self._start_image_job" in inspect_block
    assert "action='recheck unresolved'" in source
