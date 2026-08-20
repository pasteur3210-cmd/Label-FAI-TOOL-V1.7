from typing import List, Dict
from .models import DecodeItem
from .roi import barcode_variants


def _reader():
    try:
        import zxingcpp
        return zxingcpp
    except Exception as e:
        raise RuntimeError("zxing-cpp is unavailable. Install requirements.txt or use the GitHub build.") from e


def _to_item(r):
    pts = None
    try:
        p = r.position
        pts = [
            (int(p.top_left.x), int(p.top_left.y)),
            (int(p.top_right.x), int(p.top_right.y)),
            (int(p.bottom_right.x), int(p.bottom_right.y)),
            (int(p.bottom_left.x), int(p.bottom_left.y)),
        ]
    except Exception:
        pass
    return DecodeItem(format=str(r.format), text=(r.text or "").strip(), points=pts)


def decode_codes(image) -> List[DecodeItem]:
    zxingcpp = _reader()
    return [_to_item(r) for r in zxingcpp.read_barcodes(image)]


def decode_codes_multi(image, rois: Dict[str, object], include_full: bool = True) -> List[DecodeItem]:
    """
    V1.0.2: decode the full corrected label and dedicated barcode/QR ROIs.
    Barcode values are variables; this only extracts Actual values.
    """
    zxingcpp = _reader()
    unique = {}

    def read(source):
        for _, variant in barcode_variants(source):
            try:
                results = zxingcpp.read_barcodes(variant)
            except Exception:
                continue
            for r in results:
                item = _to_item(r)
                if item.text:
                    unique[(item.format, item.text)] = item

    if include_full and image is not None:
        read(image)
    for name, roi in rois.items():
        if any(token in name.lower() for token in ("barcode", "qr", "sn", "mac", "gpon")):
            read(roi)
    return list(unique.values())
