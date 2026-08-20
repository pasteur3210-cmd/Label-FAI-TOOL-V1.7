import unittest
from pathlib import Path
from label_tool.app import App
from label_tool.core.direct_guided_ocr import GuidedOCRResult
from label_tool.core.models import FieldResult

class _Log:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass
    def error(self,*a,**k): pass
    def exception(self,*a,**k): pass

class _Session:
    debug=_Log(); test=_Log(); performance=_Log()
    execution=_Log(); lock_history=_Log()
    def save_target_image(self,*a,**k): pass

class _Var:
    def __init__(self): self.value=""
    def set(self,v): self.value=v

class _Locks:
    def __init__(self,item):
        self.fields={item:object()}
        self.count=0
        self.value=""
    def is_locked(self,name): return False
    def offer(self,name,value,status,message,source=""):
        if status=="PASS":
            self.count += 1
            self.value=value
        return "LOCK" if self.count>=2 else "VERIFY"
    def status_text(self,name):
        return "LOCK" if self.count>=2 else f"PASS {self.count}/2"
    def get_value(self,name): return self.value

class _Tree:
    def exists(self,name): return True
    def item(self,*a,**k): pass

class _Scheduler:
    def advance_if_locked(self,locks): return False

def _app_for_merge(item):
    a=object.__new__(App)
    a.live_active=True
    a.live_session=_Session()
    a.guided_ocr_var=_Var()
    a.guided_quality_var=_Var()
    a.guided_expected_var=_Var()
    a.locks=_Locks(item)
    a.live_tree=_Tree()
    a.guided_scheduler=_Scheduler()
    a._candidate_value=lambda row: row.actual
    a._refresh_cross_checks=lambda: None
    a._update_zone_ui=lambda: None
    a._update_live_overall=lambda frame: None
    return a

class V153MergeRootCauseTests(unittest.TestCase):
    def test_app_imports_re_for_merge_safe_name(self):
        src=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.assertIn("import re\n",src)

    def test_gpon_result_enters_merge_without_nameerror(self):
        item="Fixed: GPON VoIP Gateway"
        a=_app_for_merge(item)
        row=FieldResult(
            name=item,actual="GPON VoIP Gateway",
            expected="GPON VoIP Gateway",status="PASS",
            message="score=1.000",error_code=""
        )
        result=GuidedOCRResult(
            item=item,rows=[row],raw_text="GPON VoIP\nGateway",
            target_image=None,sharpness=55.0,elapsed_ms=120.0,
            ready=True,expected_display="GPON VoIP Gateway",
            match_score=1.0
        )
        App._merge_guided_result(a,result,None,1)
        self.assertEqual(a.locks.count,1)
        self.assertEqual(a.guided_ocr_var.value,"OCR: GPON VoIP | Gateway")

    def test_model_result_enters_merge_without_nameerror(self):
        item="Fixed: model"
        a=_app_for_merge(item)
        row=FieldResult(
            name=item,actual="GRG-4297u",expected="GRG-4297u",
            status="PASS",message="match",error_code=""
        )
        result=GuidedOCRResult(
            item=item,rows=[row],raw_text="Model: GRG-4297u",
            target_image=None,sharpness=50.0,elapsed_ms=100.0,
            ready=True,expected_display="GRG-4297u",
            match_score=1.0
        )
        App._merge_guided_result(a,result,None,2)
        self.assertEqual(a.locks.count,1)

if __name__=="__main__":
    unittest.main()
