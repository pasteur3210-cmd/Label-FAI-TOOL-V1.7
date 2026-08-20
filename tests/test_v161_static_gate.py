import unittest
from pathlib import Path


class V161StaticGateTests(unittest.TestCase):
    def test_workflow_checks_only_undefined_names(self):
        src=Path('.github/workflows/build.yml').read_text(encoding='utf-8')
        self.assertIn('ruff check label_tool --select F821',src)
        self.assertNotIn('pyflakes label_tool',src)

    def test_known_unused_imports_removed(self):
        checks={
            'label_tool/app.py':'from pathlib import Path',
            'label_tool/core/inspection_report.py':'from datetime import datetime',
            'label_tool/core/production_zone_ocr.py':'GuidedTarget, DEFAULT_TARGETS',
            'label_tool/core/roi.py':'import numpy as np',
        }
        for rel,token in checks.items():
            src=Path(rel).read_text(encoding='utf-8')
            self.assertNotIn(token,src,rel)


if __name__=='__main__':
    unittest.main()
