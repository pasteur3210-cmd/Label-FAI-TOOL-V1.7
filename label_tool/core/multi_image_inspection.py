from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import json
import logging
import shutil
import uuid
import time
import hashlib
import re

import cv2
import numpy as np
import xlsxwriter

from .engine import InspectionEngine
from .artwork_presence import ArtworkPresenceDetector
from .models import FieldResult, InspectionResult
from .decoder import decode_codes_multi
from .parser import merge_fields
from .rules import validate
from .preprocess import normalize_for_ocr
from .direct_guided_ocr import best_line_similarity, crop_relative
from .image_quality import evaluate_image_quality

log = logging.getLogger(__name__)

IDENTITY_ITEMS = {
    "Variable: S/N Barcode Format": "sn",
    "Variable: MAC Barcode Format": "mac",
    "Variable: GPON S/N Barcode Format": "gpon_sn",
}

ROLE_ORDER = ["FULL", "BASIC", "WIFI", "IDENTITY", "COMPLIANCE"]
ROLE_LABELS = {
    "FULL": "Full Label",
    "BASIC": "Basic / Logo",
    "WIFI": "WiFi / User Data",
    "IDENTITY": "Identity / Barcode",
    "COMPLIANCE": "Compliance / Artwork",
    "DETAIL": "Detail / Supplemental",
}

ROLE_ITEMS_CHASSIS = {
    "BASIC": {
        "Fixed: model", "Fixed: ip", "Fixed: username", "Fixed: GPON VoIP Gateway",
        "Fixed: Input 12V 1.5A", "Fixed: USB 2.0 5V 500mA", "Variable: P/N Format",
        "Artwork: COMTREND Logo",
    },
    "WIFI": {
        "Variable: Password Format", "Variable: WiFi Key Format", "Variable: SSID Format",
        "Variable: WiFi QR Format", "Consistency: QR SSID vs Printed SSID",
        "Consistency: QR Key vs Printed WiFi Key", "Fixed: Comtrend Central Europe address",
    },
    "IDENTITY": {
        "Variable: S/N Human Readable Format", "Variable: S/N Barcode Format",
        "Consistency: S/N Text vs Barcode", "Variable: MAC Human Readable Format",
        "Variable: MAC Barcode Format", "Consistency: MAC Text vs Barcode",
        "Variable: GPON S/N Human Readable Format", "Variable: GPON S/N Barcode Format",
        "Consistency: GPON S/N Text vs Barcode", "Rule: GPON S/N = Prefix + MAC Last 8",
        "Rule: SSID = MAC Last 6",
    },
    "COMPLIANCE": {
        "Variable: Made in Format", "Fixed: CLASS 1 LASER PRODUCT",
        "Artwork: Recycling Mark", "Artwork: RoHS Mark", "Artwork: CE Mark", "Artwork: WEEE Mark",
    },
}

ROLE_ITEMS_INNER = {
    "BASIC": {"Fixed: GPON VoIP Gateway", "Fixed: model", "Variable: P/N Format", "Artwork: COMTREND Logo"},
    "WIFI": {"Fixed: DoC Link"},
    "IDENTITY": {
        "Variable: S/N Human Readable Format", "Variable: S/N Barcode Format", "Consistency: S/N Text vs Barcode",
        "Variable: MAC Human Readable Format", "Variable: MAC Barcode Format", "Consistency: MAC Text vs Barcode",
        "Variable: GPON S/N Human Readable Format", "Variable: GPON S/N Barcode Format",
        "Consistency: GPON S/N Text vs Barcode", "Rule: GPON S/N = Prefix + MAC Last 8",
    },
    "COMPLIANCE": {"Variable: Made in Format", "Artwork: Recycling Mark", "Artwork: CE Mark", "Artwork: WEEE Mark"},
}

RAW_FIELD_KEYS = [
    "model", "ip", "username", "pn", "made_in", "password", "wifi_key", "ssid",
    "sn_text", "sn_barcode", "mac_text", "mac_barcode", "gpon_sn_text", "gpon_sn_barcode",
    "wifi_qr", "qr_sn", "qr_mac", "qr_ssid", "qr_wifi_key", "has_gateway_text", "has_input_text", "has_usb_text",
    "has_comtrend_address", "has_laser_text",
]

IDENTITY_REVIEW_ITEM = "Identity: Cross-Image Consistency"


@dataclass
class ImageEvidence:
    item: str
    result: str
    actual: str = ""
    expected: str = ""
    source_image: str = ""
    quality_score: float = 0.0
    message: str = ""
    error_code: str = ""
    photo_role: str = "DETAIL"


@dataclass
class MultiImageResult:
    overall: str = "NEED_MORE_IMAGE"
    session_id: str = ""
    session_dir: str = ""
    image_count: int = 0
    initial_image_count: int = 0
    additional_image_count: int = 0
    identity_status: str = "UNKNOWN"
    identity_values: dict = field(default_factory=dict)
    evidence: dict[str, ImageEvidence] = field(default_factory=dict)
    conflicts: dict[str, list[ImageEvidence]] = field(default_factory=dict)
    unresolved_items: list[str] = field(default_factory=list)
    report_path: str = ""
    session_fields: dict = field(default_factory=dict)
    field_sources: dict = field(default_factory=dict)
    photo_roles: dict = field(default_factory=dict)
    position_evidence: dict = field(default_factory=dict)
    closeup_shape_evidence: dict = field(default_factory=dict)
    manual_overrides: dict = field(default_factory=dict)
    manual_reviews: list[dict] = field(default_factory=list)
    automatic_overall: str = ""
    expected_work_order: dict = field(default_factory=dict)
    processed_images: list[dict] = field(default_factory=list)
    cache_context: str = ""
    cache_hits: int = 0


class MultiImageInspectionEngine:
    """V1.7.9.1 guided multi-photo inspection.

    Recommended capture set:
      1) Full Label overview
      2) Basic / Logo close-up
      3) WiFi / User data close-up
      4) Identity / Barcode close-up
      5) Compliance / Artwork close-up

    The engine does not force a geometric 4-way split. It classifies each photo
    by its readable content and combines raw facts across photos before running
    relationship rules. This lets a clear close-up rescue a weak area without
    requiring every photo to be a complete-label image.
    """

    def __init__(self, profile: dict, software_version: str = ""):
        self.profile = profile
        self.software_version = software_version
        self.base = InspectionEngine(profile)
        self.artwork = ArtworkPresenceDetector(profile)

    def set_profile(self, profile: dict):
        self.profile = profile
        self.base.set_profile(profile)
        self.artwork.set_profile(profile)

    @staticmethod
    def _stable_hash(payload) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _cache_context(self, expected: dict) -> str:
        """Fingerprint all inputs that can change an inspection decision.

        A previous session is reusable only while profile, work-order expectations
        and software version are unchanged.  This prevents stale evidence from a
        different Golden/Profile or rule set being silently reused.
        """
        return self._stable_hash({
            "profile": self.profile,
            "expected": dict(expected or {}),
            "software_version": self.software_version,
        })

    @staticmethod
    def _file_fingerprint(path: str) -> dict:
        p = Path(path)
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        st = p.stat()
        return {
            "sha256": h.hexdigest(),
            "source_path": str(p.resolve()),
            "source_name": p.name,
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
        }

    @staticmethod
    def _processed_hashes(result: MultiImageResult | None) -> set[str]:
        if result is None:
            return set()
        return {str(x.get("sha256", "")) for x in (result.processed_images or []) if x.get("sha256")}

    @staticmethod
    def _safe_load(path: str):
        try:
            return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            return None

    @staticmethod
    def _sharpness(image) -> float:
        if image is None or not getattr(image, "size", 0):
            return 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    @staticmethod
    def _contrast(image) -> float:
        if image is None or not getattr(image, "size", 0):
            return 0.0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        return float(np.std(gray))

    @classmethod
    def _direct_quality_score(cls, image) -> float:
        sh = cls._sharpness(image)
        ct = cls._contrast(image)
        return float(min(1.0, sh / 300.0) * 0.75 + min(1.0, ct / 80.0) * 0.25)

    @staticmethod
    def _quality_score(q) -> float:
        if q is None:
            return 0.0
        return float(min(1.0, max(0.0, q.sharpness / 300.0)) * 0.75 + min(1.0, max(0.0, q.contrast / 80.0)) * 0.25)

    @staticmethod
    def _classify_field(row: FieldResult, quality_ok: bool) -> str:
        status = (row.status or "").upper()
        if status == "PASS":
            return "PASS"
        if status in ("WARN", "INFO", "SKIP"):
            return "NEED_MORE_IMAGE"
        if status == "ERROR":
            return "ERROR"
        if status == "FAIL":
            if not quality_ok or not (row.actual or "").strip():
                return "NEED_MORE_IMAGE"
            return "FAIL"
        return "NEED_MORE_IMAGE"


    @staticmethod
    def _manual_review_allowed(item: str) -> bool:
        """Return whether an operator may resolve a non-PASS result manually.

        Factory workflow requirement: every non-PASS inspection item must have
        a traceable manual completion path so production is not blocked by an
        OCR/decoder limitation.  The original automatic result is NEVER erased;
        apply_manual_pass stores auto_result/actual/message in manual_overrides
        and reports the final state as MANUAL_PASS.
        """
        return bool(str(item or "").strip())

    @classmethod
    def manual_attention_mode(cls, item: str) -> str:
        return "OVERRIDE_ALLOWED" if cls._manual_review_allowed(item) else "REVIEW_ONLY"

    def record_manual_review_action(self, result: MultiImageResult, item: str, action: str, note: str = "") -> MultiImageResult:
        """Record operator review for any non-PASS item without altering auto evidence.

        Used for review-only identity/barcode/consistency cases and for explicit
        Confirm FAIL/Keep Auto actions. The automatic/final result remains
        traceable and the action is written to JSON/Excel/logs.
        """
        if result is None:
            raise ValueError("No image inspection result")
        item=str(item or "").strip()
        if not item:
            raise ValueError("Manual review item is blank")
        action=str(action or "KEEP_AUTO").strip().upper()
        ev=result.evidence.get(item)
        auto_result="CONFLICT" if item in result.conflicts else (ev.result if ev else "NEED_MORE_IMAGE")
        row={
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "item": item,
            "action": action,
            "mode": self.manual_attention_mode(item),
            "auto_result": auto_result,
            "final_result": (ev.result if ev else auto_result),
            "note": str(note or ""),
            "source_image": ev.source_image if ev else "",
            "actual": ev.actual if ev else "",
            "expected": ev.expected if ev else "",
        }
        result.manual_reviews.append(row)
        session_dir=Path(result.session_dir)
        line=(f"{datetime.now().isoformat(timespec='milliseconds')} | MANUAL_ATTENTION "
              f"item={item} mode={row['mode']} auto={auto_result} action={action} note={note!r}\n")
        for path_name in ("execution.log","test.log","debug.log"):
            try:
                with (session_dir/path_name).open("a",encoding="utf-8") as f: f.write(line)
            except Exception:
                pass
        result.report_path=self._write_excel(result,result.expected_work_order or {})
        (session_dir/"result.json").write_text(json.dumps(self._serialize(result),ensure_ascii=False,indent=2),encoding="utf-8")
        return result

    def _rescue_fixed_phrase(self, row_map: dict, raw_text: str, corrected_path: str, item: str, expected: str, roi, threshold: float = 0.74):
        """V1.8.0 targeted fixed-phrase rescue for clear photos.

        General OCR can miss a visually obvious fixed phrase even when the
        image is sharp.  First compare lines from original-photo OCR; if that
        is insufficient, OCR a small Golden-relative crop from the corrected
        full-label image.  This is intentionally limited to fixed text and
        never changes barcode/identity rules.
        """
        old = row_map.get(item)
        if old is not None and getattr(old, "status", "") == "PASS":
            return
        best_score, best = best_line_similarity(raw_text or "", expected)
        source = "full-photo OCR"
        target_img = None
        if best_score < threshold and corrected_path:
            try:
                corrected = self._safe_load(corrected_path)
                if corrected is not None:
                    target_img = crop_relative(corrected, roi)
                    tsh = self._sharpness(target_img)
                    if target_img is not None and target_img.size and tsh >= 12.0:
                        txt, _ = self.base.ocr.read(normalize_for_ocr(target_img))
                        score2, best2 = best_line_similarity(txt or "", expected)
                        if score2 > best_score:
                            best_score, best = score2, best2
                            source = f"normalized target OCR sharpness={tsh:.1f}"
            except Exception as exc:
                log.debug("MULTI_IMAGE_FIXED_PHRASE_RESCUE_ERROR item=%s err=%s", item, exc)
        if best_score >= threshold:
            row_map[item] = FieldResult(
                name=item, actual="Present", expected=expected, status="PASS",
                message=f"Targeted fixed-text confirmation similarity={best_score:.3f}; {source}",
                error_code="",
            )
        elif old is not None:
            old.message = (old.message + f" | targeted similarity={best_score:.3f}").strip(" |")

    def apply_manual_pass(self, result: MultiImageResult, items: list[str], note: str = "Visual inspection confirmed") -> MultiImageResult:
        """Apply traceable human visual review to eligible visual items.

        All non-PASS items may be manually completed for factory usability.
        The automatic result is preserved in manual_overrides and Excel/result.json;
        the final state becomes MANUAL_PASS so auditability is retained.
        """
        if result is None:
            raise ValueError("No image inspection result")
        session_dir = Path(result.session_dir)
        now = datetime.now().isoformat(timespec="seconds")
        changed=[]
        for item in items:
            item=str(item)
            if not self._manual_review_allowed(item):
                raise ValueError(f"Manual PASS item is blank: {item}")
            old = result.evidence.get(item)
            if item == IDENTITY_REVIEW_ITEM:
                auto_result = "IDENTITY_MISMATCH" if result.identity_status == "MISMATCH" else "PASS"
            else:
                auto_result = "CONFLICT" if item in result.conflicts else (old.result if old else "NEED_MORE_IMAGE")
            if auto_result in ("PASS", "MANUAL_PASS"):
                continue
            result.manual_overrides[item] = {
                "timestamp": now, "auto_result": auto_result, "final_result": "MANUAL_PASS",
                "note": note, "source_image": old.source_image if old else "",
                "auto_actual": old.actual if old else "", "auto_message": old.message if old else "",
            }
            result.evidence[item] = ImageEvidence(
                item=item, result="MANUAL_PASS", actual=(old.actual if old else "Visual confirmed"),
                expected=(old.expected if old else "Visual inspection"),
                source_image=(old.source_image if old else "MANUAL_REVIEW"),
                quality_score=(old.quality_score if old else 1.0),
                message=f"Manual visual review: {note}", error_code="MANUAL-OVERRIDE", photo_role="MANUAL",
            )
            result.conflicts.pop(item, None)
            changed.append((item, auto_result))

        required=self._required_items()
        unresolved=[]; hard_fail=[]
        for item in required:
            if item in result.conflicts:
                continue
            ev=result.evidence.get(item)
            if ev is None or ev.result in ("NEED_MORE_IMAGE", "ERROR"):
                unresolved.append(item)
            elif ev.result == "FAIL":
                hard_fail.append(item)
        result.unresolved_items=unresolved
        identity_manually_resolved = bool(result.manual_overrides.get(IDENTITY_REVIEW_ITEM))
        if result.identity_status == "MISMATCH" and not identity_manually_resolved:
            result.overall="IDENTITY_MISMATCH"
        elif result.conflicts:
            result.overall="CONFLICT"
        elif hard_fail:
            result.overall="FAIL"
        elif unresolved:
            result.overall="NEED_MORE_IMAGE"
        elif result.manual_overrides:
            result.overall="PASS_WITH_MANUAL_REVIEW"
        else:
            result.overall="PASS"

        for path_name, prefix in [("execution.log","MANUAL_REVIEW"),("test.log","MANUAL_REVIEW_RESULT"),("debug.log","MANUAL_REVIEW_DEBUG")]:
            path=session_dir/path_name
            with path.open("a",encoding="utf-8") as f:
                for item,auto in changed:
                    f.write(f"{datetime.now().isoformat(timespec='milliseconds')} | {prefix} item={item} auto={auto} final=MANUAL_PASS note={note!r}\n")
        result.report_path=self._write_excel(result,result.expected_work_order or {})
        (session_dir/"result.json").write_text(json.dumps(self._serialize(result),ensure_ascii=False,indent=2),encoding="utf-8")
        return result

    def _role_items(self):
        configured=(self.profile.get("image_inspection",{}) or {}).get("role_items")
        if isinstance(configured,dict) and configured:
            out={}
            for role,items in configured.items():
                out[str(role).upper()]={str(x) for x in (items or [])}
            # DETAIL is a legitimate generic role in V1.9.0 dynamic profiles.
            return out
        label_type = str(self.profile.get("label_type", self.profile.get("profile_name", ""))).lower()
        return ROLE_ITEMS_INNER if "inner" in label_type else ROLE_ITEMS_CHASSIS

    @staticmethod
    def _count_hits(fields: dict, keys: list[str]) -> int:
        return sum(1 for k in keys if fields.get(k) not in (None, "", False))

    def classify_photo_role(self, fields: dict, decoded_texts: list[str], raw_text: str, index: int, total: int) -> str:
        """Content-based role classification with five-photo order as fallback."""
        txt = (raw_text or "").lower()
        if total >= 5 and index == 1:
            return "FULL"
        scores = {
            "BASIC": self._count_hits(fields, ["model", "pn", "ip", "username", "has_gateway_text", "has_input_text", "has_usb_text"]),
            "WIFI": self._count_hits(fields, ["password", "wifi_key", "ssid", "wifi_qr", "has_comtrend_address"]),
            "IDENTITY": self._count_hits(fields, ["sn_text", "sn_barcode", "mac_text", "mac_barcode", "gpon_sn_text", "gpon_sn_barcode"]),
            "COMPLIANCE": self._count_hits(fields, ["made_in", "has_laser_text"]),
        }
        if "class 1 laser" in txt or "made in" in txt or "rohs" in txt:
            scores["COMPLIANCE"] += 2
        if any((x or "").upper().startswith("WIFI:") for x in decoded_texts):
            scores["WIFI"] += 2
        if len(decoded_texts) >= 2:
            scores["IDENTITY"] += 2
        active = sum(1 for v in scores.values() if v >= 2)
        total_hits = sum(scores.values())
        # In the recommended 5-photo workflow image #1 is the overview.
        # Close-ups can contain several neighbouring groups and must not be
        # promoted to FULL merely because OCR sees many fields.  This was the
        # root cause of 3/5 photos being classified FULL in the 2026-08-24
        # field record.
        if total < 5 and (active >= 3 or total_hits >= 9):
            return "FULL"
        best_role, best_score = max(scores.items(), key=lambda kv: kv[1])
        if best_score > 0:
            return best_role
        # Standard five-photo fallback if OCR cannot classify a blurry image.
        if total >= 5 and 1 <= index <= 5:
            return ROLE_ORDER[index-1]
        return "DETAIL"

    def _decode_original(self, image):
        try:
            decoded = decode_codes_multi(image, {}, include_full=True)
            return decoded, [x.text for x in decoded]
        except Exception as exc:
            log.warning("MULTI_IMAGE_FULL_DECODE_ERROR %s", exc)
            return [], []

    def _ocr_original(self, image):
        """OCR a static photo at a camera-like working resolution.

        Phone photos are commonly 3k-8k pixels wide. RapidOCR is much more
        stable on the same label when the long edge is near the live-camera
        working resolution.  V1.7.9.1 therefore downsizes only for OCR; the
        original high-resolution image remains available for artwork/barcodes.
        """
        try:
            work = image
            if work is not None and getattr(work, "size", 0):
                h, w = work.shape[:2]
                long_edge = max(h, w)
                max_edge = 1800
                if long_edge > max_edge:
                    scale = max_edge / float(long_edge)
                    work = cv2.resize(work, (max(1, int(w*scale)), max(1, int(h*scale))), interpolation=cv2.INTER_AREA)
            txt, _ = self.base.ocr.read(normalize_for_ocr(work))
            return txt or ""
        except Exception as exc:
            log.warning("MULTI_IMAGE_ORIGINAL_OCR_ERROR %s", exc)
            return ""

    def _direct_original_facts(self, image):
        decoded, decoded_texts = self._decode_original(image)
        raw_text = self._ocr_original(image)
        fields = merge_fields(raw_text, decoded_texts, roi_texts={}, profile=self.profile)
        return fields, raw_text, decoded_texts, decoded

    @staticmethod
    def _better(new: ImageEvidence, old: ImageEvidence | None) -> bool:
        if old is None:
            return True
        rank = {"PASS": 4, "FAIL": 3, "ERROR": 2, "NEED_MORE_IMAGE": 1}
        nr, orr = rank.get(new.result, 0), rank.get(old.result, 0)
        if nr != orr:
            return nr > orr
        return new.quality_score > old.quality_score

    def _required_items(self):
        items = list(self.profile.get("live", {}).get("required_items", []) or [])
        art = self.profile.get("artwork_verification", {}) or {}
        for s in art.get("symbols", []) or []:
            if s.get("required"):
                item = s.get("item") or f"Artwork: {s.get('name', s.get('id','Symbol'))}"
                if item not in items:
                    items.append(item)
        return items

    def _visual_compliance_override_cached(self, image, role: str):
        """Return ``(role, cached_shape_detections, requested_items)``.

        V1.8.0 used the compliance artwork detector once to classify a close-up
        and then immediately ran the same detector a second time to collect
        shape evidence.  On production phone photos that duplicate pass can
        cost many seconds.  V1.8.1 keeps the exact decision rule but reuses the
        first detector output.
        """
        if role in ("FULL", "COMPLIANCE"):
            return role, None, []
        req = [x for x in self._role_items().get("COMPLIANCE", set()) if str(x).startswith("Artwork: ")]
        if not req:
            return role, None, []
        try:
            _rows, dets = self.artwork.evaluate_shape_only(image, requested_items=req)
            passes = [d for d in dets if getattr(d, "shape_state", "") == "PASS"]
            if len(passes) >= 2:
                return "COMPLIANCE", dets, req
            return role, dets, req
        except Exception as exc:
            log.debug("MULTI_IMAGE_ROLE_VISUAL_OVERRIDE_ERROR %s", exc)
            return role, None, req

    def _visual_compliance_override(self, image, role: str) -> str:
        # Backward-compatible wrapper retained for tests/plugins.
        return self._visual_compliance_override_cached(image, role)[0]

    @staticmethod
    def _force_fact(result: MultiImageResult, key: str, value, source: str, quality: float, reason: str = ""):
        if value in (None, "", False):
            return
        result.session_fields[key] = value
        result.field_sources[key] = {
            "source": source, "quality": float(quality), "value": value,
            "reason": reason or "forced evidence precedence",
        }

    def _reconcile_machine_readable_wifi_key(self, result: MultiImageResult, raw_fields: dict, source: str, quality: float):
        """Prefer an exact printed OCR candidate that agrees with decoded QR.

        WiFi keys are case-sensitive.  A high-quality general OCR frame may
        confuse Z/z while a later close-up reads the exact QR value.  Global
        image quality must not cause the wrong-case OCR to overwrite that exact
        case evidence.
        """
        printed = str(raw_fields.get("wifi_key", "") or "")
        qr = str(raw_fields.get("qr_wifi_key", "") or result.session_fields.get("qr_wifi_key", "") or "")
        if printed and qr and printed == qr:
            self._force_fact(result, "wifi_key", printed, source, quality, "exact case-sensitive match to decoded WiFi QR")

    def _role_allows(self, role: str, item: str) -> bool:
        if role in ("FULL", "DETAIL"):
            return True
        return item in self._role_items().get(role, set())

    def _dynamic_rows(self, raw_text: str):
        """Evaluate Golden-driven fixed text / regex fields without source-code rules.

        These rows are deliberately profile-only: a new label may add, remove or
        change them by editing its external JSON profile.
        """
        rows=[]
        for cfg in self.profile.get("dynamic_fixed_texts",[]) or []:
            item=str(cfg.get("item") or f"Golden Text: {cfg.get('name','Text')}")
            expected=str(cfg.get("text","") or "")
            threshold=float(cfg.get("threshold",0.74) or 0.74)
            score,best=best_line_similarity(raw_text or "",expected)
            # Controlled Golden forms often describe a field as
            # "Product: Home Gateway" while the printed label OCR returns
            # "COMTREND Home Gateway".  Exact normalized containment/token
            # coverage is stronger evidence than whole-line fuzzy similarity.
            def _norm_text(v):
                return re.sub(r"[^a-z0-9]+"," ",str(v or "").lower()).strip()
            exp_norm=_norm_text(expected)
            raw_norm=_norm_text(raw_text)
            exp_tokens=[x for x in exp_norm.split() if len(x)>1 and x not in {"product","required","input","type"}]
            containment=bool(exp_norm and exp_norm in raw_norm)
            token_hit=bool(exp_tokens and all(tok in raw_norm.split() for tok in exp_tokens))
            if containment or token_hit or score >= threshold:
                method="containment" if containment else ("token" if token_hit else "fuzzy")
                rows.append(FieldResult(name=item,actual=best or expected or "Present",expected=expected,status="PASS",
                    message=f"Dynamic Golden text {method} match similarity={score:.3f} threshold={threshold:.3f}",error_code=""))
            elif best:
                rows.append(FieldResult(name=item,actual=best,expected=expected,status="WARN",
                    message=f"Dynamic Golden text needs clearer image similarity={score:.3f} threshold={threshold:.3f}",error_code="DYN-TEXT-VERIFY"))
            else:
                rows.append(FieldResult(name=item,actual="",expected=expected,status="WARN",
                    message="Dynamic Golden text not recognized",error_code="DYN-TEXT-MISSING"))
        compact=' '.join((raw_text or '').split())
        for cfg in self.profile.get("dynamic_variable_fields",[]) or []:
            item=str(cfg.get("item") or f"Dynamic: {cfg.get('name','Field')}")
            regex=str(cfg.get("regex","") or "")
            display=str(cfg.get("display",regex) or regex)
            actual=""
            if regex:
                try:
                    m=re.search(regex,compact,re.I)
                    if m: actual=m.group(1) if m.lastindex else m.group(0)
                except re.error:
                    pass
            if actual:
                rows.append(FieldResult(name=item,actual=actual,expected=display,status="PASS",
                    message="Dynamic Golden regex field matched",error_code=""))
            else:
                rows.append(FieldResult(name=item,actual="",expected=display,status="WARN",
                    message="Dynamic Golden regex field not recognized",error_code="DYN-FIELD-MISSING"))
        return rows

    def _inspect_one(self, image_path: str, session_dir: Path, expected: dict, index: int, target_items=None):
        per_root = session_dir / "per_image"
        per_root.mkdir(parents=True, exist_ok=True)
        image = self._safe_load(image_path)
        if image is None:
            one=InspectionResult(overall="IMAGE_NG",error_codes=["IMG-001"])
            return one, [], {}, "DETAIL", {}, {}, {}

        # V1.7.9.1 starts from the ORIGINAL photo. This is the critical difference
        # from the legacy offline path: a close-up photo is useful evidence even
        # when it cannot be reconstructed into a whole-label perspective view.
        direct_fields, raw_text, decoded_texts, _decoded = self._direct_original_facts(image)
        total = int(getattr(self, "_batch_total", index) or index)
        role = self.classify_photo_role(direct_fields, decoded_texts, raw_text, index, total)
        role, compliance_shape_cache, compliance_shape_req = self._visual_compliance_override_cached(image, role)
        qscore = self._direct_quality_score(image)
        direct_quality_ok = self._sharpness(image) >= 18.0 and self._contrast(image) >= 8.0
        direct_rows = validate(direct_fields, self.profile, expected_work_order=expected or {})
        direct_rows.extend(self._dynamic_rows(raw_text))
        # Dynamic Golden hard rule: every required Barcode / QR item has a
        # presence path even when the controlled document does not define a
        # payload/format rule. Unknown semantics become operator-reviewable;
        # they are never silently bypassed.
        if self.profile.get("dynamic_profile"):
            formats=[str(getattr(x,"format","") or "").upper() for x in _decoded]
            texts=[str(getattr(x,"text","") or "") for x in _decoded]
            has_qr=any("QR" in f for f in formats)
            has_barcode=any(f and "QR" not in f for f in formats)
            for cfg in self.profile.get("golden_form_items",[]) or []:
                if not cfg.get("required",False):
                    continue
                typ=str(cfg.get("type","") or "")
                presence=str(cfg.get("presence_item","") or "")
                if not presence:
                    continue
                rule_known=bool(cfg.get("machine_code_rule_known",False))
                field=str(cfg.get("machine_code_field","") or "")
                if typ=="Golden QR" or field=="qr":
                    actual=next((t for f,t in zip(formats,texts) if "QR" in f),"")
                    ok=bool(actual or has_qr)
                    expected_text="QR code required by Golden"
                    # If the controlled form does not define payload semantics,
                    # successful decode is evidence of presence but NOT enough to
                    # silently PASS the requirement. Keep it in manual review.
                    status="PASS" if (ok and rule_known) else "WARN"
                    msg=("Golden QR decoded; payload rule validated by profile" if status=="PASS" else
                         "Golden QR requires operator review" if ok else
                         "Required Golden QR was not decoded; operator review or clearer image required")
                elif typ=="Golden Barcode":
                    field_map={"sn":"sn_barcode","mac":"mac_barcode","gpon_sn":"gpon_sn_barcode"}
                    fkey=field_map.get(field,"")
                    actual=str(direct_fields.get(fkey,"") or "") if fkey else ""
                    if not actual and field not in ("sn","mac","gpon_sn"):
                        actual=next((t for f,t in zip(formats,texts) if f and "QR" not in f),"")
                    ok=bool(actual)
                    expected_text=(f"{field.upper() if field else 'Barcode'} barcode required by Golden")
                    # Known field barcodes may PASS only when the parser mapped
                    # the decoded value to that exact field. Generic/undefined
                    # barcodes remain reviewable even when a code was detected.
                    status="PASS" if (ok and rule_known and bool(fkey)) else "WARN"
                    msg=("Golden field barcode decoded and mapped" if status=="PASS" else
                         "Golden barcode requires operator review" if ok or has_barcode else
                         "Required Golden barcode was not decoded; operator review or clearer image required")
                else:
                    continue
                direct_rows.append(FieldResult(
                    name=presence, actual=actual or ("Present" if ok else ""), expected=expected_text,
                    status=status,
                    message=msg,
                    error_code="" if status=="PASS" else "GOLDEN-CODE-REVIEW"
                ))
            # Prevent seed/Legacy rows emitted by generic validate() from even
            # entering Dynamic evidence/debug logs.  Only the imported Golden
            # plus explicitly added Standard Library requirements may survive.
            dynamic_required=set(self._required_items())
            direct_rows=[r for r in direct_rows if r.name in dynamic_required]

        if role == "FULL" and not self.profile.get("dynamic_profile"):
            # Bundled Legacy profiles keep their established whole-label engine.
            # Dynamic Golden profiles must NOT execute a seed model's fixed ROI/
            # model-specific checks; their inspection content comes only from the
            # imported Golden + explicitly-added Standard Library items.
            one = self.base.inspect(image_path, str(per_root), expected)
            rows_by_name = {r.name: r for r in one.fields}
            label_type = str(self.profile.get("label_type", "")).lower()
            gateway_roi = [0.04, 0.12, 0.46, 0.22] if "chassis" in label_type else [0.01, 0.14, 0.43, 0.29]
            self._rescue_fixed_phrase(
                rows_by_name, raw_text, getattr(one, "corrected_image_path", ""),
                "Fixed: GPON VoIP Gateway", "GPON VoIP Gateway", gateway_roi, 0.72
            )
        else:
            # Detail photos deliberately skip detect_label/perspective/legacy ROI
            # processing. This avoids the V1.7.8 failure mode where a clear
            # Identity/Compliance close-up was rotated/cropped as if it were a
            # complete label.
            one = InspectionResult(
                overall="DETAIL",
                quality=evaluate_image_quality(image, self.profile),
                fields=list(direct_rows),
                decoded=[], ocr_text=raw_text, error_codes=[]
            )
            rows_by_name = {}

        # Original-photo OCR/decoder evidence is allowed to rescue a weak legacy
        # full-label correction and is the primary evidence for detail roles.
        for r in direct_rows:
            dynamic_item = r.name.startswith("Golden Text: ") or r.name.startswith("Dynamic: ")
            if self._role_allows(role, r.name) or dynamic_item:
                old = rows_by_name.get(r.name)
                if old is None or r.status == "PASS" or old.status != "PASS":
                    rows_by_name[r.name] = r
        if role in ("BASIC", "DETAIL"):
            self._rescue_fixed_phrase(
                rows_by_name, raw_text, "",
                "Fixed: GPON VoIP Gateway", "GPON VoIP Gateway", [0,0,1,1], 0.72
            )

        # Artwork: full overview supplies relative position. Basic/Compliance
        # close-ups may supply higher-resolution shape evidence. Size is ignored.
        art_position = {}
        art_shape = {}
        art_requested = None if target_items is None else [x for x in target_items if str(x).startswith("Artwork: ")]
        if role == "FULL":
            art_rows, art_dets = self.artwork.evaluate(image, requested_items=art_requested)
            for r in art_rows:
                rows_by_name[r.name] = r
            for d in art_dets:
                art_position[d.item] = {
                    "position_state": d.position_state,
                    "position_error": d.position_error,
                    "shape_state": d.shape_state,
                    "score": d.score,
                    "source": Path(image_path).name,
                    "quality": qscore,
                }
        elif role in ("BASIC", "COMPLIANCE", "DETAIL"):
            allowed = self._role_items().get(role, set()) if role != "DETAIL" else set(self._required_items())
            req = [x for x in (art_requested if art_requested is not None else allowed) if str(x).startswith("Artwork: ")]
            if req:
                # Reuse the visual-role detector result when it evaluated the
                # same compliance artwork set. This preserves thresholds and
                # scoring while removing a duplicate expensive image pass.
                if (compliance_shape_cache is not None and role == "COMPLIANCE"
                        and set(req).issubset(set(compliance_shape_req or []))):
                    shape_dets = [d for d in compliance_shape_cache if getattr(d, "item", None) in set(req)]
                else:
                    _shape_rows, shape_dets = self.artwork.evaluate_shape_only(image, requested_items=req)
                for d in shape_dets:
                    art_shape[d.item] = {
                        "shape_state": d.shape_state,
                        "score": d.score,
                        "source": Path(image_path).name,
                        "quality": qscore,
                        "threshold": d.threshold,
                    }

        observations = []
        for row in rows_by_name.values():
            if target_items is not None and row.name not in target_items:
                continue
            if not self._role_allows(role, row.name) and role != "FULL":
                continue
            observations.append(ImageEvidence(
                item=row.name,
                result=self._classify_field(row, direct_quality_ok),
                actual=row.actual,
                expected=row.expected,
                source_image=Path(image_path).name,
                quality_score=qscore,
                message=f"role={ROLE_LABELS.get(role, role)} | {row.message}",
                error_code=row.error_code,
                photo_role=role,
            ))

        return one, observations, direct_fields, role, art_position, art_shape, {
            "raw_text": raw_text,
            "decoded_texts": decoded_texts,
            "sharpness": self._sharpness(image),
            "contrast": self._contrast(image),
            "quality": qscore,
        }

    @staticmethod
    def _merge_fact(result: MultiImageResult, key: str, value, source: str, quality: float):
        if value in (None, "", False):
            return
        current = result.field_sources.get(key)
        if current is None or quality > float(current.get("quality", 0.0)):
            result.session_fields[key] = value
            result.field_sources[key] = {"source": source, "quality": float(quality), "value": value}

    def _merge_session_rules(self, result: MultiImageResult, expected: dict, best: dict, conflicts: dict):
        # Minimal synthetic/custom profiles used by plugins/tests may not carry
        # the production rule schema. In that case preserve legacy fusion only.
        if not self.profile.get("rules") or "sn_regex" not in self.profile.get("rules", {}):
            return
        fields = dict(result.session_fields)
        fields["sn"] = fields.get("sn_barcode") or fields.get("sn_text", "")
        fields["mac"] = fields.get("mac_barcode") or fields.get("mac_text", "")
        fields["gpon_sn"] = fields.get("gpon_sn_barcode") or fields.get("gpon_sn_text", "")
        printed_key = str(fields.get("wifi_key", "") or "")
        qr_key = str(fields.get("qr_wifi_key", "") or "")
        case_only_key_mismatch = bool(printed_key and qr_key and printed_key != qr_key and printed_key.casefold() == qr_key.casefold())
        rows = validate(fields, self.profile, expected_work_order=expected or {})
        for row in rows:
            if row.name not in self._required_items():
                continue
            if row.name == "Consistency: QR Key vs Printed WiFi Key" and case_only_key_mismatch:
                # Never turn a Z/z OCR ambiguity into a hard FAIL/CONFLICT.
                # An exact case-sensitive candidate from another photo is
                # promoted by _reconcile_machine_readable_wifi_key; otherwise
                # ask for another image.
                best[row.name] = ImageEvidence(
                    row.name, "NEED_MORE_IMAGE", printed_key, qr_key, "SESSION_FUSION", 0.90,
                    "Case-sensitive WiFi Key ambiguous (e.g. Z/z); add a clearer WiFi/User photo",
                    "XCHK-QR-KEY-CASE", "SESSION"
                )
                conflicts.pop(row.name, None)
                continue
            # Session-level rules can combine facts from different photos.
            if row.status == "PASS":
                conflicts.pop(row.name, None)
                src_keys = []
                for k, info in result.field_sources.items():
                    if str(info.get("value", "")) and str(info.get("value", "")) in str(row.actual) + str(row.expected):
                        src_keys.append(info.get("source", ""))
                src = "+".join(sorted(set(x for x in src_keys if x))) or "SESSION_FUSION"
                ev = ImageEvidence(row.name, "PASS", row.actual, row.expected, src, 0.95,
                                   "Session-level raw fact fusion / rule re-evaluation", row.error_code, "SESSION")
                old = best.get(row.name)
                if self._better(ev, old):
                    best[row.name] = ev
            elif row.status == "FAIL" and row.actual:
                ev = ImageEvidence(row.name, "FAIL", row.actual, row.expected, "SESSION_FUSION", 0.85,
                                   row.message or "Session-level rule failure", row.error_code, "SESSION")
                old = best.get(row.name)
                if old and old.result == "PASS":
                    conflicts.setdefault(row.name, [old]).append(ev)
                elif self._better(ev, old):
                    best[row.name] = ev

    def _merge_artwork_components(self, result: MultiImageResult, best: dict):
        for item in [x for x in self._required_items() if x.startswith("Artwork: ")]:
            p = result.position_evidence.get(item)
            s = result.closeup_shape_evidence.get(item)
            if not p or not s:
                continue
            pos_state = p.get("position_state")
            pos_err = float(p.get("position_error", 999.0))
            shape_ok = s.get("shape_state") == "PASS"
            # Multi-image corroboration: the overview remains the position
            # source. A position in the narrow VERIFY dead-band may be accepted
            # only when a separate close-up independently confirms shape.
            # This is not a size check and does not accept a position FAIL.
            position_ok = pos_state == "PASS" or (pos_state == "VERIFY" and pos_err <= 1.10 and float(p.get("quality",0.0)) >= 0.45)
            if position_ok and shape_ok:
                q = min(1.0, (float(p.get("quality",0.0)) + float(s.get("quality",0.0))) / 2.0 + 0.15)
                corroborated = pos_state == "VERIFY"
                ev = ImageEvidence(
                    item=item, result="PASS", actual="Shape+Position PASS", expected="Shape + relative position; size ignored",
                    source_image=f"{p.get('source','')} + {s.get('source','')}", quality_score=q,
                    message=(f"Multi-photo artwork fusion: overview position {'VERIFY-corroborated' if corroborated else 'PASS'} err={pos_err:.2f}; "
                             f"close-up shape PASS score={s.get('score',0):.3f}; size ignored"),
                    photo_role="SESSION",
                )
                if self._better(ev, best.get(item)):
                    best[item] = ev

    def inspect_batch(self, image_paths: list[str], output_root="image_records", expected=None,
                      previous_session: MultiImageResult | None = None, progress_callback=None,
                      cancel_event=None, target_items=None) -> MultiImageResult:
        if not image_paths:
            raise ValueError("No images selected")
        expected = dict(expected or {})
        started = datetime.now()
        sid = previous_session.session_id if previous_session else f"{started:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        session_dir = Path(previous_session.session_dir) if previous_session else Path(output_root) / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        src_dir = session_dir / "source_images"; src_dir.mkdir(exist_ok=True)
        execution_log = session_dir / "execution.log"
        test_log = session_dir / "test.log"
        debug_log = session_dir / "debug.log"
        performance_log = session_dir / "performance.log"

        def write(path: Path, text: str):
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='milliseconds')} | {text}\n")

        result = previous_session or MultiImageResult(session_id=sid, session_dir=str(session_dir))
        result.expected_work_order = dict(expected or result.expected_work_order or {})
        targets = None if target_items is None else set(target_items)

        current_context = self._cache_context(expected)
        if previous_session and result.cache_context and result.cache_context != current_context:
            raise ValueError("Inspection cache context changed (Profile/Golden/work-order/software). Reset the image session and run again.")
        result.cache_context = current_context

        def progress(stage, index=0, total=0, image="", elapsed_ms=None, **extra):
            if progress_callback:
                try:
                    progress_callback({"stage": stage, "index": index, "total": total, "image": image,
                                       "elapsed_ms": elapsed_ms, **extra})
                except Exception:
                    pass

        def cancelled():
            return bool(cancel_event is not None and getattr(cancel_event, "is_set", lambda: False)())

        # V1.8.2 incremental preflight: fingerprint every selected path first,
        # then analyze only content not already present in this session. Hashing
        # a file is orders of magnitude cheaper than OCR/artwork processing and
        # also prevents the same image being analyzed twice under a new filename.
        already = self._processed_hashes(result)
        queued = []
        seen_now = set()
        for src in image_paths:
            fp = self._file_fingerprint(str(src))
            digest = fp["sha256"]
            if digest in already or digest in seen_now:
                result.cache_hits += 1
                write(performance_log, f"CACHE_HIT file={Path(src).name} sha256={digest[:16]} action=SKIP_OCR")
                progress("cache_hit", 0, len(image_paths), Path(src).name, elapsed_ms=0.0)
                continue
            seen_now.add(digest)
            queued.append((str(src), fp))

        new_count = len(queued)
        if not previous_session:
            result.initial_image_count = new_count
        else:
            result.additional_image_count += new_count
        write(execution_log, f"IMAGE_INSPECTION_START profile={self.profile.get('profile_name','')} selected_count={len(image_paths)} new_count={new_count} cache_hits={len(image_paths)-new_count} targets={sorted(targets) if targets is not None else 'ALL'}")
        write(execution_log, "CAPTURE_PLAN recommended=FULL+BASIC+WIFI+IDENTITY+COMPLIANCE auto_classification=ON incremental_cache=ON")
        progress("batch_start", 0, new_count, "")

        best = dict(result.evidence)
        conflicts = {k: list(v) for k, v in result.conflicts.items()}
        identity_sets = {k: set([v]) if v else set() for k, v in result.identity_values.items()}

        # Early PASS: when there is no unresolved/conflicting target, selected
        # already-processed photos are true cache hits and no OCR work is needed.
        # New unique photos are still analyzed unless caller explicitly targets
        # an empty set (used by the UI after a completed PASS).
        if previous_session and targets is not None and not targets and new_count:
            for src, fp in queued:
                result.processed_images.append({**fp, "role": "SKIPPED_AFTER_PASS", "processed_at": datetime.now().isoformat(timespec="seconds")})
                result.photo_roles[Path(src).name] = "SKIPPED_AFTER_PASS"
                write(performance_log, f"EARLY_PASS file={Path(src).name} sha256={fp['sha256'][:16]} action=SKIP_ANALYSIS")
            result.image_count += new_count
            result.additional_image_count += 0  # already accounted above
            queued = []
            new_count = 0

        for idx, (src, fingerprint) in enumerate(queued, 1):
            if cancelled():
                write(execution_log, f"IMAGE_INSPECTION_CANCELLED before_index={idx}")
                progress("cancelled", idx-1, len(image_paths), "")
                raise RuntimeError("Image inspection cancelled by user")
            image_started = time.perf_counter()
            src_path = Path(src)
            progress("processing", idx, len(queued), src_path.name)
            copy_started = time.perf_counter()
            dest = src_dir / f"{result.image_count + idx:02d}_{src_path.name}"
            if not dest.exists():
                shutil.copy2(src_path, dest)
            copy_ms = (time.perf_counter()-copy_started)*1000.0
            inspect_started = time.perf_counter()
            self._batch_total = result.image_count + len(queued)
            try:
                one_result = self._inspect_one(str(src_path), session_dir, expected, result.image_count + idx, target_items=targets)
            except TypeError as exc:
                # Compatibility with earlier custom/test engines that override
                # _inspect_one using the V1.7.7 four-argument contract.
                if "target_items" not in str(exc):
                    raise
                one_result = self._inspect_one(str(src_path), session_dir, expected, result.image_count + idx)
            # Backward-compatible test/plugin contract: V1.7.7/1.7.8 custom
            # engines returned only (InspectionResult, observations).
            if len(one_result) == 2:
                one, observations = one_result
                raw_fields, role, art_pos, art_shape = {}, "DETAIL", {}, {}
                q=getattr(one,"quality",None)
                diag={"raw_text":"","decoded_texts":[],"sharpness":getattr(q,"sharpness",0.0),
                      "contrast":getattr(q,"contrast",0.0),"quality":self._quality_score(q)}
            else:
                one, observations, raw_fields, role, art_pos, art_shape, diag = one_result
            inspect_ms = (time.perf_counter()-inspect_started)*1000.0
            total_ms = (time.perf_counter()-image_started)*1000.0
            result.photo_roles[src_path.name] = role
            write(performance_log, f"IMAGE index={idx}/{len(queued)} role={role} file={src_path.name} copy_ms={copy_ms:.1f} inspect_ms={inspect_ms:.1f} total_ms={total_ms:.1f} target_count={len(targets) if targets is not None else 'ALL'}")
            write(debug_log, f"IMAGE file={src_path.name} role={role} base_overall={one.overall} direct_sharpness={diag.get('sharpness',0):.1f} direct_contrast={diag.get('contrast',0):.1f} direct_q={diag.get('quality',0):.3f} decoded={diag.get('decoded_texts',[])}")

            for key, value in raw_fields.items():
                if key in RAW_FIELD_KEYS:
                    self._merge_fact(result, key, value, src_path.name, float(diag.get("quality",0.0)))
            self._reconcile_machine_readable_wifi_key(
                result, raw_fields, src_path.name, float(diag.get("quality",0.0))
            )

            for item, info in art_pos.items():
                old = result.position_evidence.get(item)
                if old is None or float(info.get("quality",0)) > float(old.get("quality",0)):
                    result.position_evidence[item] = info
            for item, info in art_shape.items():
                old = result.closeup_shape_evidence.get(item)
                if old is None or float(info.get("score",0)) > float(old.get("score",0)):
                    result.closeup_shape_evidence[item] = info

            for ev in observations:
                write(debug_log, f"EVIDENCE item={ev.item} result={ev.result} role={ev.photo_role} q={ev.quality_score:.3f} source={ev.source_image} actual={ev.actual!r} code={ev.error_code} msg={ev.message}")
                if ev.item in IDENTITY_ITEMS and ev.result == "PASS" and ev.actual:
                    identity_sets.setdefault(IDENTITY_ITEMS[ev.item], set()).add(ev.actual.strip().upper())
                old = best.get(ev.item)
                if old and {old.result, ev.result} == {"PASS", "FAIL"} and min(old.quality_score, ev.quality_score) >= 0.45:
                    bucket = conflicts.setdefault(ev.item, [])
                    if not bucket:
                        bucket.append(old)
                    bucket.append(ev)
                    continue
                if self._better(ev, old):
                    best[ev.item] = ev
            result.processed_images.append({**fingerprint, "role": role, "processed_at": datetime.now().isoformat(timespec="seconds")})
            progress("image_done", idx, len(queued), f"{src_path.name} [{ROLE_LABELS.get(role,role)}]", elapsed_ms=total_ms)

        result.image_count += len(queued)

        # Cross-photo fusion: rerun all data/relationship rules from the best raw
        # facts gathered across the photo set, then combine close-up artwork shape
        # with full-overview relative-position evidence.
        self._merge_session_rules(result, expected, best, conflicts)
        self._merge_artwork_components(result, best)

        result.evidence = best
        result.conflicts = conflicts
        result.identity_values = {k: (sorted(v)[0] if len(v) == 1 else " | ".join(sorted(v))) for k, v in identity_sets.items() if v}
        mismatch = {k: v for k, v in identity_sets.items() if len(v) > 1}
        result.identity_status = "MISMATCH" if mismatch else ("PASS" if any(identity_sets.values()) else "UNKNOWN")

        required = self._required_items()
        unresolved, hard_fail = [], []
        for item in required:
            if item in conflicts:
                continue
            ev = best.get(item)
            if ev is None or ev.result in ("NEED_MORE_IMAGE", "ERROR"):
                unresolved.append(item)
            elif ev.result == "FAIL":
                hard_fail.append(item)
        result.unresolved_items = unresolved

        # Reconstruct the pure machine decision separately from the final
        # operator decision. Manual overrides store their original auto_result,
        # so a later incremental run must not rewrite Automatic Overall to PASS.
        auto_unresolved, auto_hard_fail, auto_conflict = [], [], False
        for item in required:
            manual = result.manual_overrides.get(item)
            if manual:
                state = str(manual.get("auto_result", "NEED_MORE_IMAGE")).upper()
                if state == "CONFLICT":
                    auto_conflict = True
                elif state == "FAIL":
                    auto_hard_fail.append(item)
                elif state in ("NEED_MORE_IMAGE", "ERROR", "VERIFY", "WARN", "INFO", "SKIP"):
                    auto_unresolved.append(item)
                continue
            if item in conflicts:
                auto_conflict = True
                continue
            ev = best.get(item)
            if ev is None or ev.result in ("NEED_MORE_IMAGE", "ERROR"):
                auto_unresolved.append(item)
            elif ev.result == "FAIL":
                auto_hard_fail.append(item)

        if result.identity_status == "MISMATCH":
            automatic = "IDENTITY_MISMATCH"
        elif auto_conflict:
            automatic = "CONFLICT"
        elif auto_hard_fail:
            automatic = "FAIL"
        elif auto_unresolved:
            automatic = "NEED_MORE_IMAGE"
        else:
            automatic = "PASS"
        result.automatic_overall = automatic

        identity_manually_resolved = bool(result.manual_overrides.get(IDENTITY_REVIEW_ITEM))
        if result.identity_status == "MISMATCH" and not identity_manually_resolved:
            final_overall = "IDENTITY_MISMATCH"
        elif conflicts:
            final_overall = "CONFLICT"
        elif hard_fail:
            final_overall = "FAIL"
        elif unresolved:
            final_overall = "NEED_MORE_IMAGE"
        elif result.manual_overrides:
            final_overall = "PASS_WITH_MANUAL_REVIEW"
        else:
            final_overall = "PASS"
        result.overall = final_overall
        write(test_log, f"RESULT overall={result.overall} images={result.image_count} identity={result.identity_status} roles={result.photo_roles} unresolved={unresolved} conflicts={list(conflicts)} hard_fail={hard_fail}")
        write(execution_log, f"IMAGE_INSPECTION_END overall={result.overall} total_images={result.image_count} roles={result.photo_roles}")

        report_started = time.perf_counter()
        progress("report", len(queued), len(queued), "")
        result.report_path = self._write_excel(result, expected)
        (session_dir / "result.json").write_text(json.dumps(self._serialize(result), ensure_ascii=False, indent=2), encoding="utf-8")
        report_ms = (time.perf_counter()-report_started)*1000.0
        write(performance_log, f"REPORT excel_json_ms={report_ms:.1f} overall={result.overall}")
        progress("completed", len(queued), len(queued), "", elapsed_ms=report_ms)
        return result

    def _serialize(self, result: MultiImageResult):
        return {
            "overall": result.overall,
            "session_id": result.session_id,
            "image_count": result.image_count,
            "initial_image_count": result.initial_image_count,
            "additional_image_count": result.additional_image_count,
            "identity_status": result.identity_status,
            "identity_values": result.identity_values,
            "unresolved_items": result.unresolved_items,
            "photo_roles": result.photo_roles,
            "session_fields": result.session_fields,
            "field_sources": result.field_sources,
            "position_evidence": result.position_evidence,
            "closeup_shape_evidence": result.closeup_shape_evidence,
            "automatic_overall": result.automatic_overall,
            "manual_overrides": result.manual_overrides,
            "manual_reviews": result.manual_reviews,
            "expected_work_order": result.expected_work_order,
            "processed_images": result.processed_images,
            "cache_context": result.cache_context,
            "cache_hits": result.cache_hits,
            "evidence": {k: asdict(v) for k, v in result.evidence.items()},
            "conflicts": {k: [asdict(x) for x in v] for k, v in result.conflicts.items()},
            "report_path": result.report_path,
        }

    def _write_excel(self, result: MultiImageResult, expected: dict):
        p = Path(result.session_dir) / f"Label_Image_Inspection_Report_{result.session_id}.xlsx"
        wb = xlsxwriter.Workbook(str(p))
        h = wb.add_format({"bold": True, "bg_color": "#4472C4", "font_color": "#FFFFFF", "border": 1})
        c = wb.add_format({"border": 1, "text_wrap": True, "valign": "top"})
        good = wb.add_format({"border": 1, "bg_color": "#E2F0D9", "font_color": "#006100", "bold": True})
        bad = wb.add_format({"border": 1, "bg_color": "#FCE4D6", "font_color": "#9C0006", "bold": True})
        warn = wb.add_format({"border": 1, "bg_color": "#FFF2CC", "font_color": "#7F6000", "bold": True})
        ws = wb.add_worksheet("Summary")
        rows = [
            ("Overall", result.overall), ("Automatic Overall", result.automatic_overall or result.overall),
            ("Manual Overrides", len(result.manual_overrides)), ("Manual Review Actions", len(result.manual_reviews)), ("Inspection Mode", "GUIDED_MULTI_IMAGE"),
            ("Recommended Capture", "Full Label + Basic + WiFi + Identity + Compliance"),
            ("Profile", self.profile.get("profile_name", "")), ("Label Type", self.profile.get("label_type", "")),
            ("Software Version", self.software_version), ("Session ID", result.session_id),
            ("Images Loaded", result.image_count), ("Initial Batch", result.initial_image_count),
            ("Additional Images", result.additional_image_count), ("Session Cache Hits", result.cache_hits), ("Identity Check", result.identity_status),
            ("S/N", result.identity_values.get("sn", "")), ("MAC", result.identity_values.get("mac", "")),
            ("GPON S/N", result.identity_values.get("gpon_sn", "")), ("Work Order P/N", expected.get("pn", "")),
            ("Made in", expected.get("made_in", "")), ("Need More Image", ", ".join(result.unresolved_items)),
            ("Conflicts", ", ".join(result.conflicts.keys())),
        ]
        ws.set_column(0, 0, 24); ws.set_column(1, 1, 100)
        for r, (k, v) in enumerate(rows):
            ws.write(r, 0, k, h)
            fmt = good if k == "Overall" and result.overall == "PASS" else bad if k == "Overall" and result.overall in ("FAIL", "IDENTITY_MISMATCH", "CONFLICT") else warn if k == "Overall" else c
            ws.write(r, 1, str(v), fmt)

        out = wb.add_worksheet("Inspection_Result")
        heads = ["Item", "Auto Result", "Final Result", "Manual Review", "Actual", "Expected", "Evidence Image", "Photo Role", "Quality Score", "Message", "Error Code"]
        for col, name in enumerate(heads): out.write(0, col, name, h)
        out.set_column(0, 0, 42); out.set_column(1, 3, 18); out.set_column(4, 5, 30); out.set_column(6, 7, 36); out.set_column(8, 8, 14); out.set_column(9, 10, 58)
        for r, item in enumerate(self._required_items(), 1):
            ev = result.evidence.get(item)
            manual = result.manual_overrides.get(item, {})
            if item in result.conflicts:
                auto = "CONFLICT"
                vals = [item, auto, auto, "No", "", "", "Multiple images", "SESSION", "", "Conflicting high-quality evidence", ""]
            elif ev:
                auto = manual.get("auto_result", ev.result)
                vals = [item, auto, ev.result, "Yes" if manual else "No", ev.actual, ev.expected, ev.source_image, ROLE_LABELS.get(ev.photo_role, ev.photo_role), round(ev.quality_score, 3), ev.message, ev.error_code]
            else:
                vals = [item, "NEED_MORE_IMAGE", "NEED_MORE_IMAGE", "No", "", "", "", "", "", "No usable evidence", ""]
            for col, v in enumerate(vals): out.write(r, col, v, c)

        photos = wb.add_worksheet("Photo_Roles")
        photos.write_row(0, 0, ["Image", "Detected Role"], h)
        for rr, (name, role) in enumerate(result.photo_roles.items(), 1):
            photos.write_row(rr, 0, [name, ROLE_LABELS.get(role, role)], c)
        photos.set_column(0, 0, 55); photos.set_column(1, 1, 30)

        facts = wb.add_worksheet("Session_Facts")
        facts.write_row(0, 0, ["Field", "Value", "Source Image", "Quality"], h)
        for rr, key in enumerate(sorted(result.session_fields), 1):
            info = result.field_sources.get(key, {})
            facts.write_row(rr, 0, [key, str(result.session_fields.get(key, "")), info.get("source", ""), round(float(info.get("quality", 0)), 3)], c)
        facts.set_column(0, 0, 32); facts.set_column(1, 1, 45); facts.set_column(2, 2, 55); facts.set_column(3, 3, 12)

        reviews = wb.add_worksheet("Manual_Review_Log")
        review_heads=["Timestamp","Item","Mode","Auto Result","Action","Final Result","Actual","Expected","Source Image","Note"]
        reviews.write_row(0,0,review_heads,h)
        for rr,row in enumerate(result.manual_reviews,1):
            reviews.write_row(rr,0,[row.get("timestamp",""),row.get("item",""),row.get("mode",""),row.get("auto_result",""),row.get("action",""),row.get("final_result",""),row.get("actual",""),row.get("expected",""),row.get("source_image",""),row.get("note","")],c)
        reviews.set_column(0,0,21); reviews.set_column(1,1,44); reviews.set_column(2,5,20); reviews.set_column(6,9,38)

        wb.close()
        return str(p)
