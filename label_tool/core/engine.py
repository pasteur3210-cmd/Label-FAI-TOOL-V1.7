from pathlib import Path
import json
import logging
import cv2
import numpy as np
from datetime import datetime

from .models import InspectionResult
from .image_quality import evaluate_image_quality
from .preprocess import detect_label, normalize_for_ocr
from .decoder import decode_codes_multi
from .ocr_engine import OCREngine
from .parser import merge_fields
from .rules import validate, overall_status
from .roi import build_rois, save_rois

log = logging.getLogger(__name__)


class InspectionEngine:
    def __init__(self, profile: dict):
        self.profile = profile
        self.ocr = OCREngine()

    def set_profile(self, profile: dict):
        self.profile = profile

    def inspect(self, image_path: str, output_root: str, expected=None) -> InspectionResult:
        started = datetime.now()
        stamp = started.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        debug_dir = Path(output_root) / stamp
        debug_dir.mkdir(parents=True, exist_ok=True)

        result = InspectionResult(debug_dir=str(debug_dir))
        result.metadata.update({
            "source_image": str(image_path),
            "profile": self.profile.get("profile_name", ""),
            "profile_version": str(self.profile.get("profile_version", "")),
            "source_spec": self.profile.get("source_spec", ""),
            "inspection_principle": "Fixed values compare to SPEC; variable values validate format/relationship",
        })

        image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            result.overall = "IMAGE_NG"
            result.error_codes.append("IMG-001")
            return result
        cv2.imencode(".jpg", image)[1].tofile(str(debug_dir / "01_original.jpg"))

        corrected, locate_score, box = detect_label(image, self.profile)
        result.metadata["label_locate_score"] = f"{locate_score:.3f}"
        if box is None:
            result.error_codes.append("IMG-010")
            log.warning("Label detection uncertain; full image used for diagnostic recognition.")
        cv2.imencode(".jpg", corrected)[1].tofile(str(debug_dir / "02_corrected_full_label.jpg"))
        result.corrected_image_path = str(debug_dir / "02_corrected_full_label.jpg")

        quality = evaluate_image_quality(corrected, self.profile)
        result.quality = quality
        if not quality.passed:
            result.error_codes.append("IMG-020")
            log.warning("Image quality NG, continuing diagnostic OCR/decode: %s", quality.reasons)

        rois = build_rois(corrected, self.profile)
        save_rois(rois, debug_dir)

        try:
            decoded = decode_codes_multi(corrected, rois)
        except Exception as exc:
            decoded = []
            result.error_codes.append("DEC-001")
            log.exception("Decoder error: %s", exc)
        result.decoded = decoded
        decoded_texts = [d.text for d in decoded]
        (debug_dir / "decoded.txt").write_text("\n".join(f"{d.format}: {d.text}" for d in decoded), encoding="utf-8")

        try:
            full_ocr, _ = self.ocr.read(normalize_for_ocr(corrected))
            result.ocr_text = full_ocr
        except Exception as exc:
            full_ocr = ""
            result.error_codes.append("OCR-001")
            log.exception("Full-label OCR error: %s", exc)

        roi_texts = {}
        for name, roi in rois.items():
            try:
                txt, _ = self.ocr.read(normalize_for_ocr(roi))
            except Exception:
                txt = ""
            roi_texts[name] = txt

        (debug_dir / "ocr.txt").write_text(full_ocr, encoding="utf-8")
        (debug_dir / "roi_ocr.txt").write_text("\n\n".join(f"[{k}]\n{v}" for k, v in roi_texts.items()), encoding="utf-8")

        fields = merge_fields(full_ocr, decoded_texts, roi_texts=roi_texts)
        result.fields = validate(fields, self.profile, expected_work_order=expected or {})
        result.overall = overall_status(result.fields, quality.passed)

        for f in result.fields:
            if f.error_code and f.status in ("FAIL", "WARN") and f.error_code not in result.error_codes:
                result.error_codes.append(f.error_code)

        marked = corrected.copy()
        color = {"PASS": (0,170,0), "FAIL": (0,0,220), "REVIEW": (0,140,255), "IMAGE_NG": (0,0,220)}.get(result.overall, (0,0,0))
        cv2.rectangle(marked, (0,0), (min(marked.shape[1]-1, 760), 74), (255,255,255), -1)
        cv2.putText(marked, result.overall, (15,52), cv2.FONT_HERSHEY_SIMPLEX, 1.35, color, 3, cv2.LINE_AA)
        cv2.imencode(".jpg", marked)[1].tofile(str(debug_dir / "03_marked.jpg"))
        result.marked_image_path = str(debug_dir / "03_marked.jpg")

        report = {
            "overall": result.overall,
            "error_codes": result.error_codes,
            "metadata": result.metadata,
            "quality": vars(result.quality) if result.quality else None,
            "decoded": [vars(x) for x in result.decoded],
            "roi_ocr": roi_texts,
            "fields": [vars(x) for x in result.fields],
            "elapsed_seconds": (datetime.now() - started).total_seconds(),
        }
        (debug_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
