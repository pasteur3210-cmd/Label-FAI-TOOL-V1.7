import unittest
from pathlib import Path

class V160ArchitectureTests(unittest.TestCase):
    def test_production_mode_default(self):
        s=Path('label_tool/app.py').read_text(encoding='utf-8')
        self.assertIn('Production 4-Zone',s); self.assertIn('Manual Item Debug',s)
    def test_zone_worker_uses_queue(self):
        s=Path('label_tool/app.py').read_text(encoding='utf-8')
        start=s.index('    def _zone_worker('); end=s.find('\n    def ',start+5); body=s[start:end]
        self.assertIn("kind='zone_result'",body); self.assertNotIn('self.after(',body); self.assertNotIn('.config(',body)
    def test_protected_fast_reader_still_full_frame(self):
        s=Path('label_tool/core/fast_machine_reader.py').read_text(encoding='utf-8')
        self.assertIn('zxingcpp.read_barcodes(rgb)',s); self.assertNotIn('ProductionZone',s)
    def test_excel_report_called_after_result(self):
        s=Path('label_tool/app.py').read_text(encoding='utf-8')
        self.assertIn('save_excel_report(payload)',s)

if __name__=='__main__': unittest.main()
