import unittest, tempfile, zipfile
from pathlib import Path
from label_tool.core.inspection_report import create_inspection_report

class V160ReportTests(unittest.TestCase):
    def test_excel_report_created_with_expected_sheets(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'report.xlsx'
            payload={'overall':'PASS','software_version':'1.6.0','profile':'P','locks':{'Fixed: model':{'state':'LOCK','locked_value':'GRG-4297u','lock_source':'Zone OCR A','lock_time':'2026-08-19T14:00:00','last_message':'ok'}},'zone_stats':{'A':{'title':'ZONE A','attempts':2,'total_ocr_ms':3000,'max_ocr_ms':1700,'last_sharpness':50,'locked_items':7,'total_items':7,'completed':True}}}
            create_inspection_report(p,payload)
            self.assertTrue(p.exists()); self.assertGreater(p.stat().st_size,1000)
            with zipfile.ZipFile(p) as z:
                workbook=z.read('xl/workbook.xml').decode('utf-8')
                for name in ['Summary','Inspection_Result','Zone_Performance','Traceability']: self.assertIn(name,workbook)

if __name__=='__main__': unittest.main()
