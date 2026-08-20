from __future__ import annotations

import os
import cv2
import threading
import time


class CameraManager:
    """Camera capture separated from recognition.

    A background thread continuously grabs frames. Consumers only receive
    the newest frame; old frames are intentionally discarded.
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
                # Keep hardware buffer low when backend supports it.
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

    def _capture_loop(self):
        while not self._stop_event.is_set():
            cap = self.cap
            if cap is None or not cap.isOpened():
                break
            ok, frame = cap.read()
            if ok and frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._frame_seq += 1
            else:
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
            return {
                "frame_seq": self._frame_seq,
                "last_read_seq": self._last_read_seq,
                "capture_failures": self._capture_failures,
            }

    def autofocus(self, enabled: bool = True):
        if self.cap is None:
            return False, 0.0
        ok = False
        try:
            ok = bool(self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if enabled else 0))
        except Exception:
            pass
        try:
            value = float(self.cap.get(cv2.CAP_PROP_AUTOFOCUS))
        except Exception:
            value = 0.0
        return ok, value

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

        with self._lock:
            self._latest_frame = None
            self._frame_seq = 0
            self._last_read_seq = 0
