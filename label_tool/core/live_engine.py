from __future__ import annotations

import re
import time
import cv2
from dataclasses import dataclass, field

from .models import QualityResult
from .image_quality import evaluate_image_quality
from .preprocess import detect_label, normalize_for_ocr
from .roi import build_rois
from .decoder import decode_codes_multi
from .ocr_engine import OCREngine
from .parser import merge_fields
from .rules import validate


@dataclass
class LiveFrameResult:
    quality: QualityResult
    quality_ok: bool
    fields: list
    corrected: object
    raw_fields: dict
    decoded_texts: list[str]
    roi_sharpness: dict[str, float]
    timings_ms: dict[str, float] = field(default_factory=dict)
    active_items: list[str] = field(default_factory=list)
    scanned_rois: list[str] = field(default_factory=list)
    error: str = ""


# Required checklist item -> parser ROI dependencies.
ITEM_ROI_MAP = {
    "Fixed: model": {"fixed_text"},
    "Fixed: ip": {"fixed_text"},
    "Fixed: username": {"fixed_text"},
    "Fixed: GPON VoIP Gateway": {"fixed_text"},
    "Fixed: Input 12V 1.5A": {"fixed_text"},
    "Fixed: USB 2.0 5V 500mA": {"fixed_text"},
    "Fixed: Comtrend Central Europe address": {"fixed_text"},
    "Fixed: CLASS 1 LASER PRODUCT": {"fixed_text"},

    "Variable: P/N Format": {"pn"},
    "Work Order: P/N": {"pn"},
    "Variable: Made in Format": {"fixed_text"},
    "Work Order: Made in": {"fixed_text"},

    "Variable: S/N Human Readable Format": {"sn_text"},
    "Variable: S/N Barcode Format": {"sn_barcode"},
    "Consistency: S/N Text vs Barcode": {"sn_text", "sn_barcode"},

    "Variable: MAC Human Readable Format": {"mac_text"},
    "Variable: MAC Barcode Format": {"mac_barcode"},
    "Consistency: MAC Text vs Barcode": {"mac_text", "mac_barcode"},

    "Variable: GPON S/N Human Readable Format": {"gpon_text"},
    "Variable: GPON S/N Barcode Format": {"gpon_barcode"},
    "Consistency: GPON S/N Text vs Barcode": {"gpon_text", "gpon_barcode"},

    "Variable: SSID Format": {"ssid_password_wifi"},
    "Rule: SSID = MAC Last 6": {"ssid_password_wifi", "mac_text", "mac_barcode"},
    "Rule: GPON S/N = Prefix + MAC Last 8": {"gpon_text", "gpon_barcode", "mac_text", "mac_barcode"},
    "Variable: Password Format": {"ssid_password_wifi"},
    "Variable: WiFi Key Format": {"ssid_password_wifi"},

    "Variable: WiFi QR Format": {"wifi_qr"},
    "Consistency: QR SSID vs Printed SSID": {"wifi_qr", "ssid_password_wifi"},
    "Consistency: QR Key vs Printed WiFi Key": {"wifi_qr", "ssid_password_wifi"},
}

BARCODE_ROIS = {"sn_barcode", "mac_barcode", "gpon_barcode", "wifi_qr"}
OCR_ROIS = {
    "fixed_text",
    "pn",
    "ssid_password_wifi",
    "sn_text",
    "mac_text",
    "gpon_text",
}

# Locked source checklist -> parser field memory.
LOCK_TO_FIELD = {
    "Fixed: model": "model",
    "Fixed: ip": "ip",
    "Fixed: username": "username",
    "Variable: P/N Format": "pn",
    "Variable: Made in Format": "made_in",
    "Variable: S/N Human Readable Format": "sn_text",
    "Variable: S/N Barcode Format": "sn_barcode",
    "Variable: MAC Human Readable Format": "mac_text",
    "Variable: MAC Barcode Format": "mac_barcode",
    "Variable: GPON S/N Human Readable Format": "gpon_sn_text",
    "Variable: GPON S/N Barcode Format": "gpon_sn_barcode",
    "Variable: SSID Format": "ssid",
    "Variable: Password Format": "password",
    "Variable: WiFi Key Format": "wifi_key",
    "Variable: WiFi QR Format": "wifi_qr",
}


class LiveFrameAnalyzer:
    def __init__(self, profile: dict):
        self.profile = profile
        self.ocr = OCREngine()

    def set_profile(self, profile: dict):
        self.profile = profile

    @staticmethod
    def _sharpness(image) -> float:
        if image is None or image.size == 0:
            return 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    @staticmethod
    def required_rois(active_items):
        wanted = set()
        for item in active_items or []:
            wanted.update(ITEM_ROI_MAP.get(item, set()))
        return wanted

    def analyze(
        self,
        frame,
        expected_work_order=None,
        active_items=None,
        known_fields=None,
    ) -> LiveFrameResult:
        t0 = time.perf_counter()
        active_items = list(active_items or [])
        known_fields = dict(known_fields or {})
        timings = {}

        corrected, _, _ = detect_label(frame, self.profile)
        timings["label_detect"] = (time.perf_counter() - t0) * 1000.0

        t = time.perf_counter()
        quality = evaluate_image_quality(corrected, self.profile)
        timings["quality"] = (time.perf_counter() - t) * 1000.0

        # Bad frame: return immediately. No OCR/decode cost.
        if not quality.passed:
            timings["total"] = (time.perf_counter() - t0) * 1000.0
            return LiveFrameResult(
                quality=quality,
                quality_ok=False,
                fields=[],
                corrected=corrected,
                raw_fields=known_fields,
                decoded_texts=[],
                roi_sharpness={},
                timings_ms=timings,
                active_items=active_items,
                scanned_rois=[],
            )

        all_rois = build_rois(corrected, self.profile)
        wanted = self.required_rois(active_items)
        rois = {k: v for k, v in all_rois.items() if k in wanted}
        roi_sharpness = {name: self._sharpness(img) for name, img in rois.items()}
        timings["roi_build"] = (time.perf_counter() - t) * 1000.0

        # Barcode/QR: only selected unlocked dependencies.
        t = time.perf_counter()
        decode_rois = {k: v for k, v in rois.items() if k in BARCODE_ROIS}
        decoded = decode_codes_multi(None, decode_rois, include_full=False) if decode_rois else []
        decoded_texts = [x.text for x in decoded]
        timings["decode"] = (time.perf_counter() - t) * 1000.0

        # OCR: only selected unlocked dependencies. No full-label OCR in live mode.
        t = time.perf_counter()
        roi_texts = {}
        for name, roi in rois.items():
            if name not in OCR_ROIS:
                continue
            try:
                txt, _ = self.ocr.read(normalize_for_ocr(roi))
            except Exception:
                txt = ""
            roi_texts[name] = txt
        timings["ocr"] = (time.perf_counter() - t) * 1000.0

        t = time.perf_counter()
        fields = merge_fields("", decoded_texts, roi_texts=roi_texts, profile=self.profile)

        # Restore values that have already been LOCKED, so relation checks can
        # complete without re-scanning those source ROIs.
        for key, value in known_fields.items():
            if value and not fields.get(key):
                fields[key] = value

        # Rebuild authoritative logical values after memory merge.
        fields["sn"] = fields.get("sn_barcode") or fields.get("sn_text", "")
        fields["mac"] = fields.get("mac_barcode") or fields.get("mac_text", "")
        fields["gpon_sn"] = fields.get("gpon_sn_barcode") or fields.get("gpon_sn_text", "")

        results = validate(
            fields,
            self.profile,
            expected_work_order=expected_work_order or {},
        )
        timings["rules"] = (time.perf_counter() - t) * 1000.0
        timings["total"] = (time.perf_counter() - t0) * 1000.0

        return LiveFrameResult(
            quality=quality,
            quality_ok=True,
            fields=results,
            corrected=corrected,
            raw_fields=fields,
            decoded_texts=decoded_texts,
            roi_sharpness=roi_sharpness,
            timings_ms=timings,
            active_items=active_items,
            scanned_rois=sorted(rois.keys()),
        )


    def evaluate_known_fields(self, known_fields=None, expected_work_order=None, active_items=None):
        """Zone D: evaluate rules from already LOCKED data without Camera/OCR/Decoder."""
        known_fields = dict(known_fields or {})
        known_fields["sn"] = known_fields.get("sn_barcode") or known_fields.get("sn_text", "")
        known_fields["mac"] = known_fields.get("mac_barcode") or known_fields.get("mac_text", "")
        known_fields["gpon_sn"] = known_fields.get("gpon_sn_barcode") or known_fields.get("gpon_sn_text", "")
        results = validate(known_fields, self.profile, expected_work_order=expected_work_order or {})
        wanted = set(active_items or [])
        return [r for r in results if r.name in wanted]

    def scanner_results(self, raw: str, expected_work_order=None):
        """Validate deterministic HID scanner data without OCR."""
        value = (raw or "").strip()
        if not value:
            return []

        f = merge_fields("", [value], roi_texts={}, profile=self.profile)
        all_results = validate(
            f,
            self.profile,
            expected_work_order=expected_work_order or {},
        )

        if value.upper().startswith("WIFI:"):
            names = {"Variable: WiFi QR Format"}
        elif re.fullmatch(self.profile.get("rules", {}).get("sn_regex", r"$^"), value, re.I):
            names = {"Variable: S/N Barcode Format"}
        elif re.fullmatch(self.profile.get("rules", {}).get("gpon_regex", r"$^"), value, re.I):
            names = {"Variable: GPON S/N Barcode Format"}
        elif re.fullmatch(self.profile.get("rules", {}).get("mac_regex", r"$^"), value, re.I):
            names = {"Variable: MAC Barcode Format"}
        else:
            names = set()

        return [r for r in all_results if r.name in names]
