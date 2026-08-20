from pathlib import Path
import cv2


def crop_fraction(image, frac):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = frac
    x1 = max(0, min(w - 1, int(round(x1 * w))))
    x2 = max(x1 + 1, min(w, int(round(x2 * w))))
    y1 = max(0, min(h - 1, int(round(y1 * h))))
    y2 = max(y1 + 1, min(h, int(round(y2 * h))))
    return image[y1:y2, x1:x2].copy()


def build_rois(image, profile):
    rois = {}
    for name, frac in profile.get("rois", {}).items():
        if isinstance(frac, list) and len(frac) == 4:
            rois[name] = crop_fraction(image, frac)
    return rois


def save_rois(rois, debug_dir):
    out = Path(debug_dir) / "roi"
    out.mkdir(parents=True, exist_ok=True)
    for name, img in rois.items():
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        cv2.imencode(".jpg", img)[1].tofile(str(out / f"{safe}.jpg"))


def barcode_variants(image):
    """Generate decoder-friendly variants without changing semantic content."""
    variants = []
    if image is None or image.size == 0:
        return variants
    for rot_name, im in [
        ("0", image),
        ("90", cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)),
        ("270", cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)),
    ]:
        for scale in (1.0, 1.6, 2.2):
            src = im if scale == 1.0 else cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            variants.append((f"{rot_name}_s{scale}", src))
            gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY) if src.ndim == 3 else src
            eq = cv2.equalizeHist(gray)
            variants.append((f"{rot_name}_s{scale}_eq", eq))
            _, bw = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append((f"{rot_name}_s{scale}_bw", bw))
    return variants
