from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import sys
import time

import cv2
import numpy as np

from .models import FieldResult
from .preprocess import detect_label

log = logging.getLogger(__name__)


def artwork_dir_candidates() -> list[Path]:
    """Return artwork resource candidates in deterministic priority order.

    V1.7.3 supports source mode, PyInstaller one-folder mode, _internal layouts,
    and an explicit external ``golden_artwork`` folder copied beside the EXE.
    """
    candidates: list[Path] = []

    # External folder beside executable (preferred field-service location).
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else None
    if exe_dir is not None:
        candidates.extend([
            exe_dir / "golden_artwork",
            exe_dir / "label_tool" / "golden_artwork",
            exe_dir / "_internal" / "label_tool" / "golden_artwork",
        ])

    # PyInstaller extraction / internal bundle path.
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        candidates.extend([
            root / "golden_artwork",
            root / "label_tool" / "golden_artwork",
        ])

    # Source-tree fallback.
    candidates.append(Path(__file__).resolve().parents[1] / "golden_artwork")

    # Deduplicate while preserving order.
    unique: list[Path] = []
    seen = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def bundled_artwork_dir() -> Path:
    for p in artwork_dir_candidates():
        if p.exists() and p.is_dir():
            return p
    # Keep deterministic fallback so missing-resource logs show the expected path.
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


class ArtworkPresenceDetector:
    """V1.7.2 Golden Artwork shape + relative-position detector.

    Acceptance:
      * required artwork shape is detected
      * detected artwork is at the expected position relative to the label

    Explicitly NOT judged:
      * printed artwork size
      * camera pixel size / camera-to-label distance
      * inter-symbol spacing as a separate requirement

    Scale search is used only to make shape recognition tolerant of camera distance;
    ``best_scale`` is diagnostic data and is never an acceptance criterion.
    """

    DEFAULT_SCALES = [0.35, 0.45, 0.55, 0.65, 0.75, 0.90, 1.00, 1.15, 1.35, 1.60, 1.90, 2.20]

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
        self.symbols = []
        self.templates = {}
        self.expected_centers: dict[str, tuple[float, float]] = {}

        root = bundled_artwork_dir()
        log.info("ARTWORK_RESOURCE_ROOT selected=%s candidates=%s", root, [str(p) for p in artwork_dir_candidates()])
        layout_rel = str(art.get("golden_layout", "")).strip()
        self.golden_layout = cv2.imread(str(root / layout_rel), cv2.IMREAD_GRAYSCALE) if layout_rel else None

        for raw in art.get("symbols", []) or []:
            if not raw.get("required", False):
                continue
            cfg = dict(raw)
            item = str(cfg.get("item") or f"Artwork: {cfg.get('name', cfg.get('id', 'Symbol'))}")
            cfg["item"] = item
            self.symbols.append(cfg)
            path = root / str(cfg.get("template", ""))
            log.info("ARTWORK_TEMPLATE_CHECK item=%s path=%s exists=%s", item, path, path.exists())
            if path.exists():
                templ = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if templ is not None and templ.size:
                    self.templates[item] = self._trim_template(templ)
                    log.info("ARTWORK_TEMPLATE_LOADED item=%s shape=%s", item, self.templates[item].shape)

        self._calibrate_expected_centers()

    @staticmethod
    def _trim_template(templ):
        """Remove white page margin around a golden symbol.

        V1.7.1 matched the original crop including margin.  That made the score
        highly sensitive to real camera background and was a major field issue.
        """
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
        # Otsu is substantially more stable than V1.7.1 adaptive thresholding
        # for black artwork printed on a white label under uneven camera light.
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        return bw

    @staticmethod
    def _center_norm(loc, size, frame_shape):
        x, y = loc
        w, h = size
        fh, fw = frame_shape[:2]
        return ((x + w / 2.0) / max(fw, 1), (y + h / 2.0) / max(fh, 1))

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

    def _calibrate_expected_centers(self):
        """Locate every symbol on the supplied Golden Label Example.

        This avoids hand-entering pixel coordinates. Expected positions come
        from the same source-spec artwork supplied by the user.
        """
        if self.golden_layout is None or not getattr(self.golden_layout, "size", 0):
            return
        for cfg in self.symbols:
            item = cfg["item"]
            # Explicit profile center wins if later engineering calibration is needed.
            center = cfg.get("expected_center")
            if center and len(center) == 2:
                self.expected_centers[item] = (float(center[0]), float(center[1]))
                continue
            templ = self.templates.get(item)
            if templ is None:
                continue
            scales = cfg.get("golden_calibration_scales") or [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 0.90, 1.00]
            score, _scale, loc, size = self._best_match(self.golden_layout, templ, scales)
            self.expected_centers[item] = self._center_norm(loc, size, self.golden_layout.shape)
            log.debug("ARTWORK_GOLDEN_CAL item=%s score=%.3f center=(%.4f,%.4f)", item, score, *self.expected_centers[item])

    def _position_result(self, actual, expected, cfg):
        if actual is None or expected is None:
            return False, 999.0
        tol = cfg.get("position_tolerance", self.position_tolerance)
        tx, ty = float(tol[0]), float(tol[1])
        dx = abs(float(actual[0]) - float(expected[0]))
        dy = abs(float(actual[1]) - float(expected[1]))
        # normalized error: <=1 means inside the rectangular tolerance window
        err = max(dx / max(tx, 1e-6), dy / max(ty, 1e-6))
        return bool(dx <= tx and dy <= ty), float(err)

    def _normalize_label(self, frame):
        corrected, confidence, box = detect_label(frame, self.profile)
        aligned = box is not None and confidence > 0.0
        if aligned:
            return corrected, True, float(confidence)
        return frame, False, float(confidence)

    def evaluate(self, frame, requested_items=None):
        requested = None if requested_items is None else set(requested_items)
        if not self.enabled or frame is None or getattr(frame, "size", 0) == 0:
            return [], []

        normalized, label_aligned, label_score = self._normalize_label(frame)
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
                rows.append(FieldResult(
                    name=item, actual="", expected="Shape + relative position",
                    status="FAIL", message="Golden artwork template missing",
                    error_code="ART-TEMPLATE-MISSING"
                ))
                detections.append(ArtworkDetection(item, str(cfg.get("id", "")), False, 0.0, threshold, 1.0))
                continue

            scales = cfg.get("detect_scales") or self.DEFAULT_SCALES
            score, best_scale, loc, size = self._best_match(normalized, templ, scales)
            actual_center = self._center_norm(loc, size, normalized.shape) if size != (0, 0) else None
            shape_pass = score >= threshold
            position_pass, pos_error = self._position_result(actual_center, expected_center, cfg)
            if self.require_label_alignment and not label_aligned:
                position_pass = False
            present = bool(shape_pass and position_pass)
            elapsed = (time.perf_counter() - started) * 1000.0

            if not label_aligned and self.require_label_alignment:
                reason = "label alignment not available; keep entire label visible"
                code = "ART-LABEL-NOT-ALIGNED"
            elif not shape_pass:
                reason = "shape below threshold"
                code = "ART-SHAPE-NG"
            elif not position_pass:
                reason = "relative position outside tolerance"
                code = "ART-POSITION-NG"
            else:
                reason = "shape and relative position OK"
                code = ""

            if present:
                actual = "Shape+Position PASS"
            elif not label_aligned and self.require_label_alignment:
                # Do not confirm NG while the operator has not presented the complete label.
                actual = ""
            elif shape_pass and not position_pass:
                # Stable semantic value allows SmartLock to confirm a real position NG.
                actual = "Shape PASS / Position NG"
            else:
                # Complete, aligned label but wrong/missing artwork shape: confirm NG after
                # the existing fail_confirmations gate instead of scanning forever.
                actual = "Shape NG"
            exp = f"Shape>={threshold:.2f}; relative position; size ignored"
            ac = actual_center or (-1.0, -1.0)
            ec = expected_center or (-1.0, -1.0)
            msg = (
                f"shape={score:.3f}/{threshold:.2f}; "
                f"pos={'PASS' if position_pass else 'FAIL'}; "
                f"actual=({ac[0]:.3f},{ac[1]:.3f}); expected=({ec[0]:.3f},{ec[1]:.3f}); "
                f"pos_err={pos_error:.2f}; scale={best_scale:.2f}(ignored); "
                f"label_align={'YES' if label_aligned else 'NO'} score={label_score:.3f}; "
                f"{reason}; {elapsed:.1f}ms"
            )
            rows.append(FieldResult(
                name=item, actual=actual, expected=exp,
                status="PASS" if present else "FAIL", message=msg, error_code=code
            ))
            det = ArtworkDetection(
                item=item, symbol_id=str(cfg.get("id", "")), present=present,
                score=score, threshold=threshold, best_scale=best_scale,
                shape_pass=shape_pass, position_pass=position_pass,
                position_error=pos_error, actual_center=actual_center,
                expected_center=expected_center, label_aligned=label_aligned,
                elapsed_ms=elapsed,
            )
            detections.append(det)
            log.debug(
                "ARTWORK_EVAL item=%s final=%s shape=%.3f threshold=%.3f shape_pass=%s position_pass=%s "
                "actual=%s expected=%s pos_error=%.3f scale=%.2f size_ignored=YES label_aligned=%s label_score=%.3f ms=%.1f",
                item, "PASS" if present else "FAIL", score, threshold, shape_pass,
                position_pass, actual_center, expected_center, pos_error, best_scale,
                label_aligned, label_score, elapsed,
            )
        return rows, detections
