from __future__ import annotations

import os
import cv2
import threading
import time
import queue


class CameraManager:
    """Camera capture separated from recognition and camera-control commands.

    V1.7.4 serializes CAP_PROP operations on the capture thread. This avoids
    GUI-thread cap.set()/cap.get() racing with cap.read() on the same backend.
    """
    def __init__(self):
        self.cap = None
        self.index = 0
        self.backend_name = ""
        self.width = 1920
        self.height = 1080

        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_frame = None
        self._frame_seq = 0
        self._last_read_seq = 0
        self._capture_failures = 0
        self._commands: queue.Queue = queue.Queue()
        self._last_af_result = {"ok": False, "readback": 0.0, "elapsed_ms": 0.0, "error": ""}

    def _backends(self):
        if os.name == "nt":
            return [
                ("DirectShow", cv2.CAP_DSHOW),
                ("MediaFoundation", cv2.CAP_MSMF),
                ("Default", cv2.CAP_ANY),
            ]
        return [("Default", cv2.CAP_ANY)]

    def scan(self, max_index: int = 6):
        found = []
        for idx in range(max_index + 1):
            cap = None
            try:
                for name, backend in self._backends():
                    cap = cv2.VideoCapture(idx, backend)
                    if cap.isOpened():
                        ok, _ = cap.read()
                        if ok:
                            found.append(idx)
                            break
                    cap.release()
                    cap = None
            finally:
                if cap is not None:
                    cap.release()
        return sorted(set(found))

    def open(self, index: int, width: int = 1920, height: int = 1080) -> bool:
        self.close()
        self.index = int(index)
        self.width = int(width)
        self.height = int(height)

        for name, backend in self._backends():
            cap = cv2.VideoCapture(self.index, backend)
            if not cap.isOpened():
                cap.release()
                continue

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            try:
                cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
            except Exception:
                pass

            ok, frame = cap.read()
            if ok and frame is not None:
                self.cap = cap
                self.backend_name = name
                with self._lock:
                    self._latest_frame = frame.copy()
                    self._frame_seq = 1
                    self._last_read_seq = 0
                    self._capture_failures = 0
                self._stop_event.clear()
                self._thread = threading.Thread(
                    target=self._capture_loop,
                    name="CameraCaptureThread",
                    daemon=True,
                )
                self._thread.start()
                return True

            cap.release()

        return False

    def _process_commands(self, cap):
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            kind = cmd.get("kind")
            done = cmd.get("done")
            result = cmd.get("result")
            started = time.perf_counter()
            try:
                if kind == "autofocus_retrigger":
                    # Force a real re-trigger instead of writing 1 -> 1.
                    off_ok = bool(cap.set(cv2.CAP_PROP_AUTOFOCUS, 0))
                    time.sleep(0.06)
                    on_ok = bool(cap.set(cv2.CAP_PROP_AUTOFOCUS, 1))
                    time.sleep(0.02)
                    try:
                        readback = float(cap.get(cv2.CAP_PROP_AUTOFOCUS))
                    except Exception:
                        readback = 0.0
                    payload = {
                        "ok": bool(on_ok or off_ok),
                        "readback": readback,
                        "elapsed_ms": (time.perf_counter()-started)*1000.0,
                        "error": "",
                    }
                elif kind == "autofocus_set":
                    enabled = bool(cmd.get("enabled", True))
                    ok = bool(cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if enabled else 0))
                    try:
                        readback = float(cap.get(cv2.CAP_PROP_AUTOFOCUS))
                    except Exception:
                        readback = 0.0
                    payload = {
                        "ok": ok,
                        "readback": readback,
                        "elapsed_ms": (time.perf_counter()-started)*1000.0,
                        "error": "",
                    }
                else:
                    payload = {
                        "ok": False,
                        "readback": 0.0,
                        "elapsed_ms": (time.perf_counter()-started)*1000.0,
                        "error": f"unknown camera command: {kind}",
                    }
            except Exception as exc:
                payload = {
                    "ok": False,
                    "readback": 0.0,
                    "elapsed_ms": (time.perf_counter()-started)*1000.0,
                    "error": repr(exc),
                }
            if isinstance(result, dict):
                result.update(payload)
            if kind in ("autofocus_retrigger", "autofocus_set"):
                self._last_af_result = dict(payload)
            if done is not None:
                done.set()

    def _capture_loop(self):
        while not self._stop_event.is_set():
            cap = self.cap
            if cap is None or not cap.isOpened():
                break
            self._process_commands(cap)
            ok, frame = cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._frame_seq += 1
            else:
                with self._lock:
                    self._capture_failures += 1
                time.sleep(0.01)

    def read(self):
        """Return newest available frame, never a queued historical frame."""
        with self._lock:
            if self._latest_frame is None:
                return False, None
            self._last_read_seq = self._frame_seq
            return True, self._latest_frame.copy()

    def stats(self):
        with self._lock:
            base = {
                "frame_seq": self._frame_seq,
                "last_read_seq": self._last_read_seq,
                "capture_failures": self._capture_failures,
            }
        base["last_autofocus"] = dict(self._last_af_result)
        return base

    def autofocus(self, enabled: bool = True, retrigger: bool = True, timeout: float = 1.2):
        """Request autofocus on the capture thread and wait briefly for result."""
        if self.cap is None or self._thread is None or not self._thread.is_alive():
            return False, 0.0, 0.0, "camera not running"
        done = threading.Event()
        result = {}
        self._commands.put({
            "kind": "autofocus_retrigger" if retrigger and enabled else "autofocus_set",
            "enabled": enabled,
            "done": done,
            "result": result,
        })
        if not done.wait(timeout=timeout):
            return False, 0.0, timeout*1000.0, "camera command timeout"
        return bool(result.get("ok")), float(result.get("readback",0.0)), float(result.get("elapsed_ms",0.0)), str(result.get("error", ""))

    def close(self):
        self._stop_event.set()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive():
            t.join(timeout=0.8)

        cap = self.cap
        self.cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

        while True:
            try:
                cmd = self._commands.get_nowait()
                if cmd.get("done") is not None:
                    cmd["done"].set()
            except queue.Empty:
                break

        with self._lock:
            self._latest_frame = None
            self._frame_seq = 0
            self._last_read_seq = 0
