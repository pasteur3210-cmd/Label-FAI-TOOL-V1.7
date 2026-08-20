import unittest
from pathlib import Path

class RuntimeLogTests(unittest.TestCase):
    def test_live_session_opens_required_logs(self):
        s=Path('label_tool/core/live_session.py').read_text(encoding='utf-8')
        self.assertIn('SESSION_TEST_LOG_OPEN',s)
        self.assertIn('SESSION_DEBUG_LOG_OPEN',s)
        self.assertIn('performance',s)
        self.assertIn('lock_history',s)

    def test_app_writes_runtime_self_checks(self):
        s=Path('label_tool/app.py').read_text(encoding='utf-8')
        self.assertIn('ZXING_RUNTIME_PASS',s)
        self.assertIn('SMART_LOCK_RUNTIME_',s)
        self.assertIn('CAMERA_RUNTIME_PASS',s)

if __name__=='__main__': unittest.main()
