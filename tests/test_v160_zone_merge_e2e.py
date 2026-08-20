import unittest
from label_tool.app import App
from label_tool.core.models import FieldResult
from label_tool.core.production_zone_ocr import ZoneOCRResult, ProductionZoneScheduler
from label_tool.core.smart_lock import SmartLockEngine

class _Var:
    def __init__(self): self.value=''
    def set(self,v): self.value=v
class _Tree:
    def exists(self,name): return True
    def item(self,*a,**k): pass
class _Log:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass
    def error(self,*a,**k): pass
    def exception(self,*a,**k): pass
class _Session:
    debug=_Log(); test=_Log(); performance=_Log(); execution=_Log(); lock_history=_Log()
    def save_target_image(self,*a,**k): return ''

class V160ZoneMergeE2E(unittest.TestCase):
    def _app(self):
        a=object.__new__(App)
        a.live_active=True
        a.live_session=_Session()
        a.guided_ocr_var=_Var(); a.guided_quality_var=_Var()
        a.live_tree=_Tree(); a.zone_stats={}; a.report_expected={}
        items=['Fixed: GPON VoIP Gateway','Fixed: model']
        a.locks=SmartLockEngine(items,2,3,12.0)
        a.production_scheduler=ProductionZoneScheduler()
        # keep scheduler on Zone A, whose effective items filter to our two locks
        a._refresh_cross_checks=lambda: None
        a._update_zone_ui=lambda: None
        a._update_live_overall=lambda frame: None
        return a

    def _result(self):
        rows=[
            FieldResult('Fixed: GPON VoIP Gateway','Present','GPON VoIP Gateway','PASS','score=1.0',''),
            FieldResult('Fixed: model','GRG-4297u','GRG-4297u','PASS','match',''),
        ]
        return ZoneOCRResult('A','ZONE A - Basic Information',rows,'GPON VoIP Gateway\nModel: GRG-4297u',None,55.0,1200.0,True,['Fixed: GPON VoIP Gateway','Fixed: model'],['Fixed: GPON VoIP Gateway','Fixed: model'])

    def test_two_zone_observations_lock_both_and_complete_zone(self):
        a=self._app(); r=self._result()
        App._merge_zone_result(a,r,None,1)
        self.assertEqual(a.locks.status_text('Fixed: GPON VoIP Gateway'),'PASS 1/2')
        self.assertEqual(a.locks.status_text('Fixed: model'),'PASS 1/2')
        App._merge_zone_result(a,r,None,2)
        self.assertTrue(a.locks.is_locked('Fixed: GPON VoIP Gateway'))
        self.assertTrue(a.locks.is_locked('Fixed: model'))
        self.assertTrue(a.zone_stats['A']['completed'])

if __name__=='__main__': unittest.main()
