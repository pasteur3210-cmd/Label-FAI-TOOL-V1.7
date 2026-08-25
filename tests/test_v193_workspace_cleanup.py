from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class WorkspaceCleanupTests(unittest.TestCase):
    def test_cleanup_script_exists_and_workflow_runs_it_before_release_gate(self):
        root = Path(__file__).resolve().parents[1]
        script = root / 'tools' / 'clean_workspace.py'
        workflow = (root / '.github' / 'workflows' / 'build.yml').read_text(encoding='utf-8')
        self.assertTrue(script.is_file())
        cleanup_pos = workflow.index('python tools/clean_workspace.py')
        gate_pos = workflow.index('python tools/release_gate.py')
        self.assertLess(cleanup_pos, gate_pos)

    def test_cleanup_logic_defines_stale_python_cache_patterns(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / 'tools' / 'clean_workspace.py').read_text(encoding='utf-8')
        for token in ('__pycache__', '.pytest_cache', '.pyc', 'build', 'dist'):
            self.assertIn(token, text)


if __name__ == '__main__':
    unittest.main()
