import unittest
from pathlib import Path
import json

class OCRRuntimeWatchdogTests(unittest.TestCase):
    def test_process_runtime_has_hard_timeout_and_restart(self):
        s=Path('label_tool/core/ocr_runtime.py').read_text(encoding='utf-8')
        self.assertIn("mp.get_context('spawn')",s)
        self.assertIn('OCRRuntimeTimeout',s)
        self.assertIn('self.restart()',s)
        self.assertIn('proc.terminate()',s)

    def test_app_logs_before_and_after_ocr(self):
        s=Path('label_tool/app.py').read_text(encoding='utf-8')
        self.assertIn('GUIDED_WORKER_START',s)
        self.assertIn('OCR_CALL_START',s)
        self.assertIn('OCR_CALL_END',s)
        self.assertIn('OCR_TIMEOUT',s)

    def test_guided_ocr_waits_for_preflight(self):
        s=Path('label_tool/app.py').read_text(encoding='utf-8')
        self.assertIn("self.ocr_runtime_state!='READY'",s)
        self.assertIn('_start_ocr_preflight_async',s)
        self.assertIn('OCR_RUNTIME_LOAD_PASS',s)

    def test_run_uses_freeze_support(self):
        s=Path('run.py').read_text(encoding='utf-8')
        self.assertIn('multiprocessing.freeze_support()',s)
        self.assertIn('--self-test-ocr',s)

    def test_github_runs_packaged_exe_ocr_smoke(self):
        s=Path('.github/workflows/build.yml').read_text(encoding='utf-8')
        self.assertIn('Packaged EXE OCR runtime smoke test',s)
        self.assertIn('Label_Inspection_Tool.exe',s)
        self.assertIn('--self-test-ocr',s)
        self.assertIn('exe_ocr_smoke.json',s)

    def test_profile_requires_preflight(self):
        d=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))
        self.assertTrue(d['live']['ocr_runtime_process_isolation'])
        self.assertTrue(d['live']['ocr_preflight_required'])
        self.assertTrue(d['live']['ocr_auto_restart_on_timeout'])

if __name__=='__main__': unittest.main()
