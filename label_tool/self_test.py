from __future__ import annotations
import json
from pathlib import Path
import time
import cv2
import numpy as np
from .core.ocr_runtime import OCRProcessService


def run_ocr_self_test(output_path='ocr_self_test.json'):
    out=Path(output_path)
    out.parent.mkdir(parents=True,exist_ok=True)
    service=OCRProcessService(init_timeout_sec=20,read_timeout_sec=10)
    payload={'test':'EXE_OCR_RUNTIME_SMOKE','passed':False}
    try:
        img=np.full((180,1000,3),255,dtype=np.uint8)
        cv2.putText(img,'GPON VoIP Gateway',(35,115),cv2.FONT_HERSHEY_SIMPLEX,2.0,(0,0,0),4,cv2.LINE_AA)
        info=service.preflight(img,init_timeout_sec=20,read_timeout_sec=10)
        payload.update(info)
        payload['passed']=True
        payload['reason']='RapidOCR process initialized and completed real inference inside packaged runtime.'
        return_code=0
    except Exception as exc:
        payload['error']=repr(exc)
        return_code=2
    finally:
        service.stop()
        payload['completed_at']=time.strftime('%Y-%m-%dT%H:%M:%S')
        out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return return_code
