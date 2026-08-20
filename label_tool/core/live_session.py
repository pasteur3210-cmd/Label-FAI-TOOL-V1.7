from __future__ import annotations
from datetime import datetime
from pathlib import Path
import json
import logging
import uuid
import cv2
from .inspection_report import create_inspection_report

class LiveInspectionSession:
    def __init__(self, base_dir: str, profile_name: str):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
        self.profile_name = profile_name
        self.started_at = datetime.now()
        self.run_dir = Path(base_dir) / self.session_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "images").mkdir(exist_ok=True)
        (self.run_dir / "target_ocr").mkdir(exist_ok=True)
        self.execution = self._logger("execution", logging.INFO)
        self.test = self._logger("test", logging.INFO)
        self.debug = self._logger("debug", logging.DEBUG)
        self.performance = self._logger("performance", logging.INFO)
        self.lock_history = self._logger("lock_history", logging.INFO)
        self.execution.info("LIVE_SESSION_START id=%s profile=%s", self.session_id, profile_name)
        self.test.info("SESSION_TEST_LOG_OPEN id=%s profile=%s", self.session_id, profile_name)
        self.debug.info("SESSION_DEBUG_LOG_OPEN id=%s profile=%s", self.session_id, profile_name)

    def _logger(self, name, level):
        logger = logging.getLogger(f"label_live_{name}_{self.session_id}")
        logger.setLevel(level); logger.handlers.clear(); logger.propagate=False
        h = logging.FileHandler(self.run_dir / f"{name}.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(h)
        return logger

    def save_image(self, name: str, image):
        if image is None: return ""
        p = self.run_dir / "images" / name
        try:
            cv2.imencode(".jpg", image)[1].tofile(str(p))
            return str(p)
        except Exception as e:
            self.debug.exception("SAVE_IMAGE_FAIL name=%s err=%s", name, e)
            return ""


    def save_target_image(self, name: str, image):
        if image is None:
            return ""
        p = self.run_dir / "target_ocr" / name
        try:
            cv2.imencode(".jpg", image)[1].tofile(str(p))
            return str(p)
        except Exception as e:
            self.debug.exception("SAVE_TARGET_IMAGE_FAIL name=%s err=%s", name, e)
            return ""


    def save_excel_report(self, payload: dict):
        p = self.run_dir / f"Label_Inspection_Report_{self.session_id}.xlsx"
        try:
            create_inspection_report(p, payload)
            self.execution.info("EXCEL_REPORT_SAVED path=%s overall=%s", p, payload.get("overall"))
            return str(p)
        except Exception as e:
            self.debug.exception("EXCEL_REPORT_FAIL err=%s", e)
            self.execution.error("EXCEL_REPORT_FAIL err=%s", e)
            return ""

    def save_result(self, payload: dict):
        p = self.run_dir / "result.json"
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.execution.info("RESULT_SAVED path=%s overall=%s", p, payload.get("overall"))
        return str(p)
