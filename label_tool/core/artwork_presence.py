from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import sys
import time
import threading

import cv2
import numpy as np

from .models import FieldResult
from .preprocess import detect_label, order_points

log = logging.getLogger(__name__)


def artwork_dir_candidates() -> list[Path]:
    """Candidate artwork roots, ordered from field-service external to bundle.

    V1.7.5 does *not* select one root globally. Each template is resolved and
    decoded independently so one stale/partial folder cannot hide a valid copy.
    """
    candidates: list[Path] = []
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if exe_dir is not None:
        candidates.extend([
            exe_dir / "golden_artwork",
            exe_dir / "label_tool" / "golden_artwork",
            exe_dir / "_internal" / "label_tool" / "golden_artwork",
        ])
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        candidates.extend([
            root / "golden_artwork",
            root / "label_tool" / "golden_artwork",
        ])
    candidates.append(Path(__file__).resolve().parents[1] / "golden_artwork")

    unique: list[Path] = []
    seen = set()
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _imread_gray_unicode(path: Path):
    """Unicode/space-safe image load on Windows.

    cv2.imread has historically varied across Windows/OpenCV builds for Unicode
    paths. np.fromfile + cv2.imdecode avoids that dependency and also works for
    ordinary ASCII paths.
    """
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size:
            img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if img is not None and img.size:
                return img
    except Exception:
        pass
    try:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        return img if img is not None and img.size else None
    except Exception:
        return None


def resolve_artwork_file(relative_path: str):
    """Resolve one artwork file independently and return (image, path, audit)."""
    rel = str(relative_path or "").replace("\\", "/").strip("/")
    audit = []
    for root in artwork_dir_candidates():
        path = root / rel
        exists = path.exists() and path.is_file()
        img = _imread_gray_unicode(path) if exists else None
        loaded = bool(img is not None and getattr(img, "size", 0))
        audit.append({"path": str(path), "exists": exists, "loaded": loaded})
        if loaded:
            return img, path, audit
    return None, None, audit


def bundled_artwork_dir() -> Path:
    """Compatibility helper used by legacy tests/tools."""
    for p in artwork_dir_candidates():
        if p.exists() and p.is_dir():
            return p
    return artwork_dir_candidates()[0]


@dataclass
class ArtworkDetection:
    item: str
    symbol_id: str
    present: bool
    score: float
    threshold: float
    best_scale: float
    shape_pass: bool = False
    position_pass: bool = False
    position_error: float = 999.0
    actual_center: tuple[float, float] | None = None
    expected_center: tuple[float, float] | None = None
    label_aligned: bool = False
    elapsed_ms: float = 0.0
    shape_state: str = "FAIL"
    position_state: str = "FAIL"


class ArtworkPresenceDetector:
    """V1.7.5 registered ROI artwork inspection with stable decisions.

    Production acceptance:
      * shape is correct
      * relative position is correct
      * printed size is NOT judged

    Flow:
      full frame -> label registration -> normalized label -> expected ROI ->
      multi-scale shape match -> relative-position decision.
    """

    DEFAULT_SCALES = [0.35,0.40,0.45,0.50,0.55,0.60,0.65,0.72,0.75,0.85,0.90,1.00,1.15,1.25,1.35,1.40,1.60,1.90,2.20]

    def __init__(self, profile: dict):
        self.set_profile(profile)

    def set_profile(self, profile: dict):
        self.profile = profile or {}
        art = self.profile.get("artwork_verification", {}) or {}
        self.enabled = bool(art.get("enabled", False))
        self.mode = str(art.get("mode", "shape_position"))
        self.require_label_alignment = bool(art.get("require_label_alignment", True))
        self.position_tolerance = art.get("position_tolerance", [0.12, 0.12]) or [0.12, 0.12]
        self.position_tolerance = (float(self.position_tolerance[0]), float(self.position_tolerance[1]))
        self.search_roi_expand = float(art.get("search_roi_expand", 1.35))
        self.label_alignment_min_score = float(art.get("label_alignment_min_score", 0.70))
        # V1.7.5 stability gates: a small dead-band avoids frame-to-frame
        # PASS/FAIL flipping when camera noise lands exactly on one threshold.
        self.shape_verify_margin = float(art.get("shape_verify_margin", 0.04))
        self.position_pass_ratio = float(art.get("position_pass_ratio", 0.90))
        self.position_fail_ratio = float(art.get("position_fail_ratio", 1.10))
        self.guide_mode = str(art.get("guide_mode", "outer_anchors"))
        self.guide_anchors = list(art.get("guide_anchors", []) or [])
        self.guide_aspect_ratio = float(art.get("guide_aspect_ratio", 0.0) or 0.0)
        self.guide_width_ratio = float(art.get("guide_width_ratio", 0.76))
        self.registration_vision = dict(art.get("registration_vision", {}) or {})
        self.symbols = []
        self.templates: dict[str, np.ndarray] = {}
        self.template_paths: dict[str, str] = {}
        self.resource_errors: dict[str, list] = {}
        self.expected_centers: dict[str, tuple[float, float]] = {}
        self.expected_boxes: dict[str, tuple[float, float, float, float]] = {}
        self._overlay_lock = threading.Lock()
        self._last_alignment_box = None
        self._last_alignment_score = 0.0
        self._last_alignment_ok = False
        self._last_alignment_at = 0.0

        layout_rel = str(art.get("golden_layout", "")).strip()
        self.golden_layout = None
        self.golden_layout_path = ""
        if layout_rel:
            img, path, audit = resolve_artwork_file(layout_rel)
            self.golden_layout = img
            self.golden_layout_path = str(path or "")
            if img is None:
                self.resource_errors["__golden_layout__"] = audit
            log.info("ARTWORK_LAYOUT_RESOLVE rel=%s selected=%s audit=%s", layout_rel, path, audit)

        for raw in art.get("symbols", []) or []:
            if not raw.get("required", False):
                continue
            cfg = dict(raw)
            item = str(cfg.get("item") or f"Artwork: {cfg.get('name', cfg.get('id', 'Symbol'))}")
            cfg["item"] = item
            self.symbols.append(cfg)
            rel = str(cfg.get("template", ""))
            templ, path, audit = resolve_artwork_file(rel)
            log.info("ARTWORK_TEMPLATE_RESOLVE item=%s rel=%s selected=%s audit=%s", item, rel, path, audit)
            if templ is not None:
                self.templates[item] = self._trim_template(templ)
                self.template_paths[item] = str(path)
            else:
                self.resource_errors[item] = audit

        self._calibrate_expected_geometry()

    def resource_status(self):
        required = [cfg["item"] for cfg in self.symbols]
        loaded = [x for x in required if x in self.templates]
        missing = [x for x in required if x not in self.templates]
        return {
            "enabled": self.enabled,
            "required": required,
            "loaded": loaded,
            "missing": missing,
            "golden_layout_loaded": bool(self.golden_layout is not None and getattr(self.golden_layout, "size", 0)),
            "golden_layout_path": self.golden_layout_path,
            "template_paths": dict(self.template_paths),
            "errors": dict(self.resource_errors),
        }

    @staticmethod
    def _trim_template(templ):
        gray = templ if templ.ndim == 2 else cv2.cvtColor(templ, cv2.COLOR_BGR2GRAY)
        _, ink = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
        pts = cv2.findNonZero(ink)
        if pts is None:
            return gray.copy()
        x, y, w, h = cv2.boundingRect(pts)
        pad = 1
        x1, y1 = max(0, x - pad), max(0, y - pad)
        x2, y2 = min(gray.shape[1], x + w + pad), min(gray.shape[0], y + h + pad)
        return gray[y1:y2, x1:x2].copy()

    @staticmethod
    def _binary(image):
        gray = image
        if gray.ndim == 3:
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return bw

    @staticmethod
    def _center_norm(loc, size, frame_shape):
        x, y = loc
        w, h = size
        fh, fw = frame_shape[:2]
        return ((x + w / 2.0) / max(fw, 1), (y + h / 2.0) / max(fh, 1))

    @staticmethod
    def _box_norm(loc, size, frame_shape):
        x, y = loc
        w, h = size
        fh, fw = frame_shape[:2]
        return (x / max(fw, 1), y / max(fh, 1), (x + w) / max(fw, 1), (y + h) / max(fh, 1))

    def _best_match(self, frame, templ, scales):
        search = self._binary(frame)
        tb = self._binary(templ)
        best = (-1.0, 1.0, (0, 0), (0, 0))
        for raw_scale in scales:
            scale = float(raw_scale)
            w = max(8, int(round(tb.shape[1] * scale)))
            h = max(8, int(round(tb.shape[0] * scale)))
            if w >= search.shape[1] or h >= search.shape[0]:
                continue
            rs = cv2.resize(tb, (w, h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
            if float(np.std(rs)) < 1e-6:
                continue
            corr = cv2.matchTemplate(search, rs, cv2.TM_CCOEFF_NORMED)
            if not corr.size:
                continue
            _minv, score, _minloc, loc = cv2.minMaxLoc(corr)
            if float(score) > best[0]:
                best = (float(score), scale, loc, (w, h))
        score, scale, loc, size = best
        return max(0.0, score), scale, loc, size


    @staticmethod
    def _corr_same_size(a, b):
        if a is None or b is None or not getattr(a,"size",0) or not getattr(b,"size",0):
            return 0.0
        if a.shape != b.shape:
            a=cv2.resize(a,(b.shape[1],b.shape[0]),interpolation=cv2.INTER_AREA)
        if float(np.std(a))<1e-6 or float(np.std(b))<1e-6:
            return 0.0
        v=float(cv2.matchTemplate(a,b,cv2.TM_CCOEFF_NORMED)[0,0])
        return max(0.0,min(1.0,v))

    def _best_match_comtrend(self, frame, templ, scales):
        """Text-logo specialist: locate with binary match, then normalize the
        candidate and combine grayscale/edge evidence. Printed size remains
        ignored; resize is only a comparison normalization step."""
        base_score, scale, loc, size = self._best_match(frame,templ,scales)
        if size==(0,0):
            return base_score,scale,loc,size,{"binary":base_score,"gray":0.0,"edge":0.0}
        x,y=loc; w,h=size
        crop=frame[y:y+h,x:x+w]
        if crop is None or not getattr(crop,"size",0):
            return base_score,scale,loc,size,{"binary":base_score,"gray":0.0,"edge":0.0}
        cg=crop if crop.ndim==2 else cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        tg=templ if templ.ndim==2 else cv2.cvtColor(templ,cv2.COLOR_BGR2GRAY)
        cg=cv2.resize(cg,(tg.shape[1],tg.shape[0]),interpolation=cv2.INTER_AREA)
        cg=cv2.equalizeHist(cg); tge=cv2.equalizeHist(tg)
        gray=self._corr_same_size(cg,tge)
        ce=cv2.Canny(cg,50,150); te=cv2.Canny(tge,50,150)
        edge=self._corr_same_size(ce,te)
        # Conservative fusion: binary location evidence remains important, but
        # normalized edge/gray structure can rescue correct logos affected by
        # focus/exposure without lowering the general symbol thresholds.
        hybrid=max(base_score, 0.35*base_score + 0.25*gray + 0.40*edge)
        return float(hybrid),scale,loc,size,{"binary":base_score,"gray":gray,"edge":edge}

    def _calibrate_expected_geometry(self):
        if self.golden_layout is None or not getattr(self.golden_layout, "size", 0):
            return
        for cfg in self.symbols:
            item = cfg["item"]
            templ = self.templates.get(item)
            if templ is None:
                continue
            scales = cfg.get("golden_calibration_scales") or [0.25,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.70,0.80,0.90,1.00,1.15]
            score, _scale, loc, size = self._best_match(self.golden_layout, templ, scales)
            auto_center = self._center_norm(loc, size, self.golden_layout.shape)
            auto_box = self._box_norm(loc, size, self.golden_layout.shape)
            center = cfg.get("expected_center")
            expected_center = (float(center[0]), float(center[1])) if center and len(center)==2 else auto_center
            self.expected_centers[item] = expected_center
            # Keep the Golden symbol's display footprint, but center it on the
            # authoritative expected_center so the operator ghost guide and
            # the inspection position gate use the same coordinate system.
            bw = auto_box[2]-auto_box[0]; bh = auto_box[3]-auto_box[1]
            bx1=max(0.0,expected_center[0]-bw/2); by1=max(0.0,expected_center[1]-bh/2)
            bx2=min(1.0,expected_center[0]+bw/2); by2=min(1.0,expected_center[1]+bh/2)
            self.expected_boxes[item] = (bx1,by1,bx2,by2)
            log.debug("ARTWORK_GOLDEN_CAL item=%s score=%.3f center=%s box=%s", item, score, self.expected_centers[item], self.expected_boxes[item])

    def _search_roi(self, normalized, expected_center, cfg):
        """Return ROI and its normalized origin around expected symbol position."""
        if expected_center is None:
            return normalized, (0.0, 0.0)
        tol = cfg.get("position_tolerance", self.position_tolerance)
        tx, ty = float(tol[0]), float(tol[1])
        expand = float(cfg.get("search_roi_expand", self.search_roi_expand))
        half_x = min(0.48, max(0.07, tx * expand))
        half_y = min(0.48, max(0.07, ty * expand))
        cx, cy = expected_center
        x1n, y1n = max(0.0, cx-half_x), max(0.0, cy-half_y)
        x2n, y2n = min(1.0, cx+half_x), min(1.0, cy+half_y)
        h, w = normalized.shape[:2]
        x1, y1 = int(x1n*w), int(y1n*h)
        x2, y2 = max(x1+8, int(x2n*w)), max(y1+8, int(y2n*h))
        return normalized[y1:y2, x1:x2], (x1n, y1n)

    @staticmethod
    def _roi_center_to_full(center_roi, origin, roi_shape, full_shape):
        if center_roi is None:
            return None
        ry, rx = roi_shape[:2]
        fy, fx = full_shape[:2]
        x = origin[0] + center_roi[0] * (rx / max(fx, 1))
        y = origin[1] + center_roi[1] * (ry / max(fy, 1))
        return (float(x), float(y))

    def _position_state(self, actual, expected, cfg):
        """Return (state, normalized_error) with hysteresis dead-band."""
        if actual is None or expected is None:
            return "FAIL", 999.0
        tol = cfg.get("position_tolerance", self.position_tolerance)
        tx, ty = float(tol[0]), float(tol[1])
        dx = abs(float(actual[0]) - float(expected[0]))
        dy = abs(float(actual[1]) - float(expected[1]))
        err = max(dx / max(tx, 1e-6), dy / max(ty, 1e-6))
        pass_ratio = float(cfg.get("position_pass_ratio", self.position_pass_ratio))
        fail_ratio = float(cfg.get("position_fail_ratio", self.position_fail_ratio))
        if err <= pass_ratio:
            return "PASS", float(err)
        if err >= fail_ratio:
            return "FAIL", float(err)
        return "VERIFY", float(err)

    def _position_result(self, actual, expected, cfg):
        """Legacy compatibility: return strict boolean + normalized error."""
        state, err = self._position_state(actual, expected, cfg)
        return state == "PASS", err

    def _shape_result(self, score, threshold, cfg):
        margin = float(cfg.get("shape_verify_margin", self.shape_verify_margin))
        fail_threshold = float(cfg.get("shape_fail_threshold", max(0.0, threshold - margin)))
        if score >= threshold:
            return "PASS"
        if score <= fail_threshold:
            return "FAIL"
        return "VERIFY"

    def _normalize_label(self, frame):
        # Artwork registration has its own vision calibration. This keeps the
        # Chassis near-square Golden layout tuning isolated from the OCR/Barcode
        # pipeline, so Zone A/B/C text performance is not changed by Artwork.
        reg_profile = self.profile
        if self.registration_vision:
            reg_profile = dict(self.profile)
            reg_profile["vision"] = dict(self.registration_vision)
        corrected, confidence, box = detect_label(frame, reg_profile)
        aligned = box is not None and float(confidence) >= self.label_alignment_min_score
        return (corrected if aligned else frame), aligned, float(confidence), box

    def evaluate(self, frame, requested_items=None):
        requested = None if requested_items is None else set(requested_items)
        if not self.enabled or frame is None or getattr(frame, "size", 0) == 0:
            return [], []
        if requested is not None and not requested:
            return [], []

        normalized, label_aligned, label_score, _box = self._normalize_label(frame)
        with self._overlay_lock:
            self._last_alignment_box = None if _box is None else np.asarray(_box, dtype=np.float32).copy()
            self._last_alignment_score = float(label_score)
            self._last_alignment_ok = bool(label_aligned)
            self._last_alignment_at = time.time()
        rows = []
        detections = []

        for cfg in self.symbols:
            item = cfg["item"]
            if requested is not None and item not in requested:
                continue
            started = time.perf_counter()
            threshold = float(cfg.get("shape_threshold", cfg.get("presence_threshold", 0.56)))
            templ = self.templates.get(item)
            expected_center = self.expected_centers.get(item)

            if templ is None:
                audit = self.resource_errors.get(item, [])
                rows.append(FieldResult(
                    name=item, actual="", expected="Shape + relative position",
                    status="ERROR", message=f"Golden artwork template missing; audit={audit}",
                    error_code="ART-TEMPLATE-MISSING"
                ))
                detections.append(ArtworkDetection(item, str(cfg.get("id", "")), False, 0.0, threshold, 1.0))
                continue

            # Invalid presentation is NOT an NG observation. This prevents the
            # operator moving the label into place from accumulating FAIL 1/3..3/3.
            if self.require_label_alignment and not label_aligned:
                elapsed = (time.perf_counter()-started)*1000.0
                msg = f"label_align=NO score={label_score:.3f}; ALIGN LABEL; size ignored; {elapsed:.1f}ms"
                rows.append(FieldResult(
                    name=item, actual="", expected=f"Shape>={threshold:.2f}; relative position; size ignored",
                    status="WARN", message=msg, error_code="ART-LABEL-NOT-ALIGNED"
                ))
                detections.append(ArtworkDetection(
                    item=item, symbol_id=str(cfg.get("id", "")), present=False,
                    score=0.0, threshold=threshold, best_scale=1.0,
                    expected_center=expected_center, label_aligned=False, elapsed_ms=elapsed,
                ))
                continue

            search_roi, origin = self._search_roi(normalized, expected_center, cfg)
            scales = cfg.get("detect_scales") or self.DEFAULT_SCALES
            detector=str(cfg.get("detector","default"))
            components=None
            if detector=="comtrend_hybrid" or str(cfg.get("id",""))=="comtrend_logo":
                score, best_scale, loc, size, components = self._best_match_comtrend(search_roi, templ, scales)
            else:
                score, best_scale, loc, size = self._best_match(search_roi, templ, scales)
            roi_center = self._center_norm(loc, size, search_roi.shape) if size != (0, 0) else None
            actual_center = self._roi_center_to_full(roi_center, origin, search_roi.shape, normalized.shape)
            shape_state = self._shape_result(score, threshold, cfg)
            position_state, pos_error = self._position_state(actual_center, expected_center, cfg)
            shape_pass = shape_state == "PASS"
            position_pass = position_state == "PASS"
            present = bool(shape_pass and position_pass)
            verifying = (shape_state == "VERIFY" or position_state == "VERIFY") and not present
            elapsed = (time.perf_counter() - started) * 1000.0

            if present:
                reason, code, actual, status = "shape and relative position OK", "", "Shape+Position PASS", "PASS"
            elif verifying:
                reason, code, actual, status = "borderline observation; hold previous state", "ART-VERIFY", "VERIFY", "WARN"
            elif shape_state == "FAIL":
                reason, code, actual, status = "shape below stable fail band", "ART-SHAPE-NG", "Shape NG", "FAIL"
            else:
                reason, code, actual, status = "relative position outside stable tolerance", "ART-POSITION-NG", "Shape PASS / Position NG", "FAIL"

            exp = f"Shape>={threshold:.2f}; relative position; size ignored"
            ac = actual_center or (-1.0, -1.0)
            ec = expected_center or (-1.0, -1.0)
            msg = (
                f"shape={score:.3f}/{threshold:.2f} state={shape_state}; pos={position_state}; "
                f"actual=({ac[0]:.3f},{ac[1]:.3f}); expected=({ec[0]:.3f},{ec[1]:.3f}); "
                f"pos_err={pos_error:.2f}; scale={best_scale:.2f}(ignored); "
                f"label_align=YES score={label_score:.3f}; roi_origin=({origin[0]:.3f},{origin[1]:.3f}); "
                f"detector={detector}; components={components if components is not None else {}}; "
                f"{reason}; {elapsed:.1f}ms"
            )
            rows.append(FieldResult(
                name=item, actual=actual, expected=exp,
                status=status, message=msg, error_code=code
            ))
            detections.append(ArtworkDetection(
                item=item, symbol_id=str(cfg.get("id", "")), present=present,
                score=score, threshold=threshold, best_scale=best_scale,
                shape_pass=shape_pass, position_pass=position_pass,
                position_error=pos_error, actual_center=actual_center,
                expected_center=expected_center, label_aligned=True,
                elapsed_ms=elapsed, shape_state=shape_state, position_state=position_state,
            ))
            log.debug("ARTWORK_EVAL item=%s final=%s %s", item, status, msg)
        return rows, detections


    def evaluate_shape_only(self, frame, requested_items=None):
        """Evaluate artwork *shape only* on a detail/close-up photo.

        V1.7.9 multi-image inspection uses the full-label overview for relative
        position and optional close-up photos only as higher-resolution shape
        evidence. Printed size is still ignored. This method deliberately does
        not run label registration or position acceptance.
        """
        requested = None if requested_items is None else set(requested_items)
        if not self.enabled or frame is None or getattr(frame, "size", 0) == 0:
            return [], []
        rows, detections = [], []
        for cfg in self.symbols:
            item = cfg["item"]
            if requested is not None and item not in requested:
                continue
            started = time.perf_counter()
            threshold = float(cfg.get("shape_threshold", cfg.get("presence_threshold", 0.56)))
            templ = self.templates.get(item)
            if templ is None:
                rows.append(FieldResult(name=item, actual="", expected=f"Shape>={threshold:.2f}; close-up",
                                        status="ERROR", message="Golden artwork template missing",
                                        error_code="ART-TEMPLATE-MISSING"))
                continue
            scales = cfg.get("detect_scales") or self.DEFAULT_SCALES
            detector = str(cfg.get("detector", "default"))
            components = None
            if detector == "comtrend_hybrid" or str(cfg.get("id", "")) == "comtrend_logo":
                score, best_scale, loc, size, components = self._best_match_comtrend(frame, templ, scales)
            else:
                score, best_scale, loc, size = self._best_match(frame, templ, scales)
            shape_state = self._shape_result(score, threshold, cfg)
            elapsed = (time.perf_counter()-started)*1000.0
            status = "PASS" if shape_state == "PASS" else ("WARN" if shape_state == "VERIFY" else "FAIL")
            actual = "Shape PASS" if status == "PASS" else ("VERIFY" if status == "WARN" else "Shape NG")
            msg=(f"shape-only close-up score={score:.3f}/{threshold:.2f} state={shape_state}; "
                 f"scale={best_scale:.2f}(ignored); detector={detector}; components={components or {}}; "
                 f"relative position must come from full-label overview; {elapsed:.1f}ms")
            rows.append(FieldResult(name=item, actual=actual, expected=f"Shape>={threshold:.2f}; size ignored",
                                    status=status, message=msg,
                                    error_code="" if status=="PASS" else "ART-SHAPE-CLOSEUP"))
            detections.append(ArtworkDetection(item=item, symbol_id=str(cfg.get("id","")),
                                                present=status=="PASS", score=score, threshold=threshold,
                                                best_scale=best_scale, shape_pass=status=="PASS",
                                                position_pass=False, label_aligned=False, elapsed_ms=elapsed,
                                                shape_state=shape_state, position_state="NOT_JUDGED"))
        return rows, detections

    def _template_contour_normalized(self, item):
        templ = self.templates.get(item)
        if templ is None:
            return None
        bw = self._binary(templ)
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        # combine meaningful external contours; tiny specks are dropped
        keep = [c for c in contours if cv2.contourArea(c) >= max(2.0, 0.0005*bw.size)]
        if not keep:
            keep = [max(contours, key=cv2.contourArea)]
        pts = np.vstack(keep).reshape(-1,2).astype(np.float32)
        pts[:,0] /= max(templ.shape[1]-1,1)
        pts[:,1] /= max(templ.shape[0]-1,1)
        return pts

    def draw_alignment_overlay(self, frame):
        """Draw a Golden ghost/contour operator guide on the camera preview.

        The guide is display-only. It helps placement/rotation but its apparent
        size is never used as an acceptance criterion.
        """
        if frame is None or not self.enabled:
            return frame
        display = frame
        with self._overlay_lock:
            box = None if self._last_alignment_box is None else self._last_alignment_box.copy()
            score = float(self._last_alignment_score)
            alignment_ok = bool(self._last_alignment_ok)
            age = time.time() - float(self._last_alignment_at or 0.0)
        # Registration runs only in the artwork worker. Never do expensive
        # detect_label work on the Tk preview thread.
        if age > 1.5:
            box = None
            score = 0.0
            alignment_ok = False
        h, w = display.shape[:2]

        if self.guide_mode == "outer_anchors":
            # Stable operator target: the guide no longer jumps with every
            # registration candidate. This is deliberately a placement aid,
            # not a printed-size gauge. The backend still judges only shape
            # and relative position.
            ratio = self.guide_aspect_ratio
            if ratio <= 0.1 and self.golden_layout is not None and self.golden_layout.shape[0] > 0:
                ratio = self.golden_layout.shape[1] / self.golden_layout.shape[0]
            if ratio <= 0.1:
                ratio = 1.8
            gw = int(w * min(max(self.guide_width_ratio, 0.45), 0.90))
            gh = int(gw / max(ratio, 0.2))
            if gh > int(h*0.72):
                gh = int(h*0.72); gw = int(gh*ratio)
            x1=(w-gw)//2; y1=(h-gh)//2
            ordered=np.array([[x1,y1],[x1+gw,y1],[x1+gw,y1+gh],[x1,y1+gh]],dtype=np.float32)
            color=(0,200,0) if alignment_ok else (0,180,255)
            if alignment_ok:
                header=f"LABEL READY | machine checks Golden ROI | size check OFF | reg={score:.2f}"
            else:
                header=f"PLACE WHOLE LABEL INSIDE GUIDE | align 3 large anchors | reg={score:.2f}/{self.label_alignment_min_score:.2f}"
        elif box is None:
            ratio = 1.8
            if self.golden_layout is not None and self.golden_layout.shape[0] > 0:
                ratio = self.golden_layout.shape[1] / self.golden_layout.shape[0]
            gw = int(w*0.78); gh = int(gw/max(ratio,0.2))
            if gh > int(h*0.72):
                gh = int(h*0.72); gw = int(gh*ratio)
            x1=(w-gw)//2; y1=(h-gh)//2
            ordered=np.array([[x1,y1],[x1+gw,y1],[x1+gw,y1+gh],[x1,y1+gh]],dtype=np.float32)
            color=(0,180,255)
            header="ALIGN ENTIRE LABEL"
        else:
            ordered = order_points(np.asarray(box,dtype=np.float32))
            if alignment_ok:
                color=(0,200,0)
                header=f"LABEL ALIGNED | Artwork guide | size check OFF | reg={score:.2f}"
            else:
                color=(0,180,255)
                header=f"ALIGNMENT NOT READY | keep entire label visible | reg={score:.2f}/{self.label_alignment_min_score:.2f}"

        cv2.polylines(display,[ordered.astype(np.int32)],True,color,3,cv2.LINE_AA)
        src = np.array([[0,0],[1,0],[1,1],[0,1]],dtype=np.float32)
        H = cv2.getPerspectiveTransform(src, ordered.astype(np.float32))

        # V1.7.5 operator guide: do NOT ask the operator to pixel-match five
        # small logos. Show only the label boundary plus a few broad anchors.
        # Fine artwork locations remain a machine-only Golden ROI decision.
        if self.guide_mode == "outer_anchors" and self.guide_anchors:
            for anchor in self.guide_anchors:
                rect = anchor.get("rect") or []
                if len(rect) != 4:
                    continue
                x1,y1,x2,y2 = [float(v) for v in rect]
                pts=np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]],dtype=np.float32)
                proj=cv2.perspectiveTransform(pts.reshape(-1,1,2),H).reshape(-1,2).astype(np.int32)
                cv2.polylines(display,[proj],True,color,2,cv2.LINE_AA)
                label=str(anchor.get("label", "ANCHOR"))
                px,py=int(proj[0][0]),int(proj[0][1])
                cv2.putText(display,label,(px,max(18,py-5)),cv2.FONT_HERSHEY_SIMPLEX,0.45,color,1,cv2.LINE_AA)
        elif self.guide_mode != "outer_only":
            for cfg in self.symbols:
                item = cfg["item"]
                center = self.expected_centers.get(item)
                boxn = self.expected_boxes.get(item)
                contour = self._template_contour_normalized(item)
                if center is None or contour is None:
                    continue
                if boxn is None:
                    bx1,by1,bx2,by2 = center[0]-0.06,center[1]-0.04,center[0]+0.06,center[1]+0.04
                else:
                    bx1,by1,bx2,by2 = boxn
                pts = contour.copy()
                pts[:,0] = bx1 + pts[:,0]*(bx2-bx1)
                pts[:,1] = by1 + pts[:,1]*(by2-by1)
                proj = cv2.perspectiveTransform(pts.reshape(-1,1,2),H).reshape(-1,2).astype(np.int32)
                if len(proj) >= 2:
                    cv2.polylines(display,[proj],True,color,2,cv2.LINE_AA)

        cv2.rectangle(display,(8,8),(min(w-8,1120),52),(0,0,0),-1)
        cv2.putText(display,header,(18,38),cv2.FONT_HERSHEY_SIMPLEX,0.66,color,2,cv2.LINE_AA)
        return display
