import unittest, json
from pathlib import Path
from label_tool.core.direct_guided_ocr import DirectGuidedOCR, DEFAULT_TARGETS

class _FailingOCR:
    def read(self,image):
        raise RuntimeError("synthetic OCR backend failure")

class V153OCRErrorVisibilityTests(unittest.TestCase):
    def test_backend_exception_is_not_silently_converted_to_empty_text(self):
        import numpy as np
        profile=json.loads(
            Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8")
        )
        ocr=DirectGuidedOCR(profile,ocr_backend=_FailingOCR())
        frame=np.zeros((720,1280,3),dtype=np.uint8)
        # Make it textured enough to pass sharpness gate.
        frame[300:430:2,200:1000:2]=255
        target=DEFAULT_TARGETS[0]
        with self.assertRaisesRegex(RuntimeError,"synthetic OCR backend failure"):
            ocr.analyze(frame,target,{}, {},min_sharpness=0)

    def test_merge_hard_trace_tokens_exist(self):
        src=Path("label_tool/app.py").read_text(encoding="utf-8")
        for token in [
            "MERGE_DISPATCH_START","MERGE_PAYLOAD_OK","MERGE_ENTER",
            "MERGE_RESULT_VALID","MERGE_ROW_BEGIN","MERGE_END","MERGE_FATAL"
        ]:
            self.assertIn(token,src)

if __name__=="__main__":
    unittest.main()
