import cv2
import numpy as np


def order_points(pts):
    pts = np.asarray(pts, dtype="float32")
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def four_point_transform(image, pts):
    rect = order_points(pts)
    tl, tr, br, bl = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_w = max(int(width_a), int(width_b))
    max_h = max(int(height_a), int(height_b))
    if max_w < 20 or max_h < 20:
        return image.copy()
    dst = np.array([[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (max_w, max_h))


def _candidate_score(image, box):
    h, w = image.shape[:2]
    x, y, bw, bh = cv2.boundingRect(box.astype(np.int32))
    area_ratio = (bw * bh) / float(w * h)
    if not 0.04 <= area_ratio <= 0.72:
        return -1
    roi = image[max(0, y):min(h, y + bh), max(0, x):min(w, x + bw)]
    if roi.size == 0:
        return -1
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    density = float((edges > 0).mean())
    white_ratio = float((gray > 135).mean())
    return area_ratio * 1.8 + density * 1.5 + white_ratio * 0.25


def _expand_box_to_aspect(box, image_shape, expected_long_short_ratio=1.55, margin=1.04, expand_x=None, expand_y=None):
    """Expand a dense-print candidate to the full sticker area.

    V1.0.1 could lock onto only the left/text half. V1.0.2 profiles may provide
    independent X/Y expansion factors calibrated from the label artwork/photo.
    """
    pts = np.asarray(box, dtype=np.float32)
    h, w = image_shape[:2]
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)

    if expand_x is not None or expand_y is not None:
        fx = float(expand_x if expand_x is not None else 1.0)
        fy = float(expand_y if expand_y is not None else 1.0)
        bw *= fx
        bh *= fy
        expanded = np.array([
            [cx - bw/2, cy - bh/2],
            [cx + bw/2, cy - bh/2],
            [cx + bw/2, cy + bh/2],
            [cx - bw/2, cy + bh/2],
        ], dtype=np.float32)
    else:
        rect = cv2.minAreaRect(pts)
        (cx, cy), (rw, rh), angle = rect
        long_side = max(rw, rh)
        short_side = min(rw, rh)
        current_ratio = long_side / max(short_side, 1.0)
        target = max(float(expected_long_short_ratio), 1.0)
        if current_ratio < target:
            long_side = short_side * target
        long_side *= margin
        short_side *= margin
        new_size = (long_side, short_side) if rw >= rh else (short_side, long_side)
        expanded = cv2.boxPoints(((cx, cy), new_size, angle))

    expanded[:, 0] = np.clip(expanded[:, 0], 0, w - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, h - 1)
    return expanded

def detect_label(image, cfg=None):
    cfg = cfg or {}
    vision = cfg.get("vision", {})
    expected_ratio = float(vision.get("label_long_short_ratio", 1.55))
    expand_margin = float(vision.get("label_expand_margin", 1.06))

    h0, w0 = image.shape[:2]
    scale = min(1.0, 1400.0 / max(h0, w0))
    small = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else image.copy()
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edge = cv2.Canny(gray, 40, 145)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    closed = cv2.morphologyEx(edge, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    for c in contours:
        if cv2.contourArea(c) < 0.025 * small.shape[0] * small.shape[1]:
            continue
        r = cv2.minAreaRect(c)
        box = cv2.boxPoints(r)
        score = _candidate_score(small, box)
        if score > best_score:
            best_score = score
            best = box

    if best is None or best_score < 0.16:
        return image.copy(), 0.0, None

    box_full = best / scale
    box_full = _expand_box_to_aspect(
        box_full, image.shape, expected_ratio, expand_margin,
        vision.get("label_expand_x"), vision.get("label_expand_y")
    )
    warped = four_point_transform(image, box_full)

    # Normalize to landscape orientation because profile ROI coordinates use label artwork orientation.
    if warped.shape[0] > warped.shape[1]:
        warped = cv2.rotate(warped, cv2.ROTATE_90_COUNTERCLOCKWISE)

    return warped, float(best_score), box_full.astype(int)


def normalize_for_ocr(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)
