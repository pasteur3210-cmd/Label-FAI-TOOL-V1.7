from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
import uuid


class OCRRuntimeError(RuntimeError):
    pass


class OCRRuntimeInitError(OCRRuntimeError):
    pass


class OCRRuntimeTimeout(OCRRuntimeError):
    def __init__(self, message: str, recovered: bool = False):
        super().__init__(message)
        self.recovered = recovered


def _to_plain_result(result):
    lines=[]
    structured=[]
    for item in result or []:
        try:
            box, text, score = item
            txt=str(text).strip()
            if not txt:
                continue
            lines.append(txt)
            try: box=box.tolist()
            except Exception: pass
            structured.append((box, txt, float(score)))
        except Exception:
            continue
    return "\n".join(lines), structured


def _ocr_process_worker(request_q, response_q):
    """Isolated RapidOCR worker. A hang can be terminated by the parent."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        started=time.perf_counter()
        engine=RapidOCR()
        response_q.put({
            'type':'READY',
            'load_ms':(time.perf_counter()-started)*1000.0,
        })
    except BaseException as exc:
        response_q.put({'type':'INIT_ERROR','error':repr(exc)})
        return

    while True:
        try:
            msg=request_q.get()
        except BaseException:
            return
        if not isinstance(msg, dict):
            continue
        cmd=msg.get('cmd')
        if cmd=='STOP':
            return
        if cmd!='READ':
            continue
        request_id=msg.get('id','')
        image=msg.get('image')
        started=time.perf_counter()
        try:
            result, _ = engine(image)
            text, structured = _to_plain_result(result)
            response_q.put({
                'type':'RESULT','id':request_id,'text':text,
                'structured':structured,
                'elapsed_ms':(time.perf_counter()-started)*1000.0,
            })
        except BaseException as exc:
            response_q.put({
                'type':'READ_ERROR','id':request_id,'error':repr(exc),
                'elapsed_ms':(time.perf_counter()-started)*1000.0,
            })


class OCRProcessService:
    """RapidOCR runtime isolated in a restartable child process.

    Key reliability property: if ONNX/RapidOCR hangs, the GUI thread and the
    Barcode/QR pipeline stay alive. The hung process is terminated and rebuilt.
    """
    def __init__(self, init_timeout_sec: float = 12.0, read_timeout_sec: float = 6.0):
        self.init_timeout_sec=float(init_timeout_sec)
        self.read_timeout_sec=float(read_timeout_sec)
        self._ctx=mp.get_context('spawn')
        self._proc=None
        self._request_q=None
        self._response_q=None
        self._ready=False
        self._load_ms=0.0
        self._lock=threading.RLock()
        self.restart_count=0

    @property
    def ready(self):
        return bool(self._ready and self._proc is not None and self._proc.is_alive())

    @property
    def load_ms(self):
        return self._load_ms

    @property
    def pid(self):
        return self._proc.pid if self._proc is not None else None

    def _cleanup_locked(self, terminate=False):
        proc=self._proc
        self._proc=None
        self._ready=False
        if proc is not None:
            try:
                if terminate and proc.is_alive(): proc.terminate()
                proc.join(timeout=1.2)
                if proc.is_alive():
                    proc.kill(); proc.join(timeout=0.5)
            except Exception:
                pass
        for q in (self._request_q,self._response_q):
            if q is not None:
                try:q.close()
                except Exception:pass
                try:q.cancel_join_thread()
                except Exception:pass
        self._request_q=None
        self._response_q=None

    def stop(self):
        with self._lock:
            if self._request_q is not None and self.ready:
                try:self._request_q.put_nowait({'cmd':'STOP'})
                except Exception:pass
            self._cleanup_locked(terminate=True)

    def start(self, timeout_sec: float | None = None):
        timeout=float(timeout_sec or self.init_timeout_sec)
        with self._lock:
            if self.ready:
                return {'load_ms':self._load_ms,'pid':self.pid,'reused':True}
            self._cleanup_locked(terminate=True)
            self._request_q=self._ctx.Queue(maxsize=2)
            self._response_q=self._ctx.Queue(maxsize=4)
            self._proc=self._ctx.Process(
                target=_ocr_process_worker,
                args=(self._request_q,self._response_q),
                name='RapidOCRRuntimeProcess',
                daemon=True,
            )
            self._proc.start()
            try:
                msg=self._response_q.get(timeout=timeout)
            except queue.Empty:
                self._cleanup_locked(terminate=True)
                raise OCRRuntimeInitError(f'RapidOCR process did not become READY within {timeout:.1f}s')
            if msg.get('type')!='READY':
                err=msg.get('error','unknown init error')
                self._cleanup_locked(terminate=True)
                raise OCRRuntimeInitError(f'RapidOCR initialization failed: {err}')
            self._ready=True
            self._load_ms=float(msg.get('load_ms',0.0))
            return {'load_ms':self._load_ms,'pid':self.pid,'reused':False}

    def restart(self, timeout_sec: float | None = None):
        with self._lock:
            self.restart_count+=1
            self._cleanup_locked(terminate=True)
        return self.start(timeout_sec=timeout_sec)

    def read_with_meta(self, image, timeout_sec: float | None = None):
        timeout=float(timeout_sec or self.read_timeout_sec)
        with self._lock:
            if not self.ready:
                self.start()
            request_id=uuid.uuid4().hex
            try:
                self._request_q.put({'cmd':'READ','id':request_id,'image':image}, timeout=1.0)
            except Exception as exc:
                recovered=False
                try:self.restart(); recovered=self.ready
                except Exception:pass
                raise OCRRuntimeError(f'Unable to submit OCR request: {exc!r}; recovered={recovered}')

            deadline=time.monotonic()+timeout
            while True:
                remain=deadline-time.monotonic()
                if remain<=0:
                    recovered=False
                    try:self.restart(); recovered=self.ready
                    except Exception:pass
                    raise OCRRuntimeTimeout(
                        f'OCR inference timeout after {timeout:.1f}s; runtime restarted={recovered}',
                        recovered=recovered,
                    )
                try:
                    msg=self._response_q.get(timeout=remain)
                except queue.Empty:
                    continue
                if msg.get('id')!=request_id:
                    # Ignore stale response from a previous timed-out request.
                    continue
                kind=msg.get('type')
                if kind=='RESULT':
                    return (
                        msg.get('text',''), msg.get('structured',[]),
                        {'elapsed_ms':float(msg.get('elapsed_ms',0.0)), 'pid':self.pid}
                    )
                if kind=='READ_ERROR':
                    raise OCRRuntimeError(f"OCR inference failed: {msg.get('error','unknown')}")

    def read(self, image, timeout_sec: float | None = None):
        text, structured, _ = self.read_with_meta(image, timeout_sec=timeout_sec)
        return text, structured

    def preflight(self, image, init_timeout_sec: float | None = None,
                  read_timeout_sec: float | None = None):
        started=time.perf_counter()
        info=self.start(timeout_sec=init_timeout_sec)
        text, structured, meta=self.read_with_meta(image, timeout_sec=read_timeout_sec)
        return {
            'ready':True,
            'pid':self.pid,
            'load_ms':info.get('load_ms',0.0),
            'inference_ms':meta.get('elapsed_ms',0.0),
            'total_ms':(time.perf_counter()-started)*1000.0,
            'text':text,
            'line_count':len(structured),
            'restart_count':self.restart_count,
        }
