import threading
import unittest
import cv2
from label_tool.core.camera_manager import CameraManager


class _FakeCap:
    def __init__(self):
        self.af=1.0
        self.calls=[]
    def set(self, prop, value):
        self.calls.append(('set',prop,value))
        if prop == cv2.CAP_PROP_AUTOFOCUS:
            self.af=float(value)
        return True
    def get(self, prop):
        self.calls.append(('get',prop))
        return self.af


class V174CameraCommandTests(unittest.TestCase):
    def test_retrigger_is_off_then_on_on_command_processor(self):
        mgr=CameraManager(); cap=_FakeCap(); done=threading.Event(); result={}
        mgr._commands.put({'kind':'autofocus_retrigger','done':done,'result':result})
        mgr._process_commands(cap)
        vals=[c[2] for c in cap.calls if c[0]=='set' and c[1]==cv2.CAP_PROP_AUTOFOCUS]
        self.assertEqual(vals,[0,1])
        self.assertTrue(done.is_set())
        self.assertTrue(result['ok'])
        self.assertEqual(result['readback'],1.0)


if __name__ == '__main__':
    unittest.main()
