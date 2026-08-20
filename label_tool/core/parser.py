import re
from typing import Dict, Iterable

MAC_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{12}(?![0-9A-Fa-f])")
GPON_RE = re.compile(r"(?<![0-9A-Fa-f])434D5444[0-9A-Fa-f]{8}(?![0-9A-Fa-f])", re.I)
SN_RE = re.compile(r"(?<![A-Za-z0-9])\d{2}[1-9A-Ca-c]4297UF-[A-Za-z0-9]{2}\d{6}(?![A-Za-z0-9])")
PN_RE = re.compile(r"\b738125-00\d\b")
SSID_RE = re.compile(r"Telekom\s+Slovenije[_\s-]*([0-9A-Fa-f]{6})", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _search(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def parse_ocr_fields(ocr_text: str, roi_texts=None) -> Dict[str, str]:
    roi_texts = roi_texts or {}
    t = _clean(ocr_text)
    f = {}

    # Dedicated ROI text has priority for variable human-readable values.
    roi_join = {k: _clean(v) for k, v in roi_texts.items()}

    candidates = [roi_join.get("sn_text", ""), t]
    for c in candidates:
        m = SN_RE.search(c)
        if m:
            f["sn_text"] = m.group(0).upper(); break

    candidates = [roi_join.get("gpon_text", ""), t]
    for c in candidates:
        m = GPON_RE.search(c)
        if m:
            f["gpon_sn_text"] = m.group(0).upper(); break

    candidates = [roi_join.get("mac_text", ""), t]
    for c in candidates:
        tmp = GPON_RE.sub(" ", SN_RE.sub(" ", c))
        ms = [m.group(0).upper() for m in MAC_RE.finditer(tmp)]
        if ms:
            f["mac_text"] = ms[0]; break

    for c in [roi_join.get("pn", ""), t]:
        m = PN_RE.search(c)
        if m:
            f["pn"] = m.group(0); break

    for c in [roi_join.get("ssid_password_wifi", ""), t]:
        m = SSID_RE.search(c)
        if m:
            f["ssid"] = "Telekom Slovenije_" + m.group(1).upper(); break

    source = _clean(" ".join([roi_join.get("fixed_text", ""), roi_join.get("ssid_password_wifi", ""), t]))
    patterns = {
        "password": r"Password\s*[:.]?\s*([A-Za-z0-9]{6,20})",
        "wifi_key": r"WiFi\s*Key\s*[:.]?\s*([A-Za-z0-9]{8,24})",
        "ip": r"IP\s*address\s*[:.]?\s*([0-9.]{7,15})",
        "username": r"Username\s*[:.]?\s*([A-Za-z0-9_-]+)",
        "model": r"Model\s*[:.]?\s*(GRG[- ]?4297[uU])",
        "made_in": r"Made\s+in\s+(China|Taiwan)",
    }
    for key, pattern in patterns.items():
        value = _search(pattern, source, re.I)
        if value:
            if key == "model": value = "GRG-4297u"
            if key == "made_in": value = value.title()
            f[key] = value

    low = source.lower()
    f["has_gateway_text"] = "gpon voip gateway" in low
    f["has_comtrend_address"] = "comtrend central europe" in low and "jankovcova" in low
    f["has_laser_text"] = "class 1 laser product" in low
    f["has_input_text"] = bool(re.search(r"Input\s*[:.]?\s*12V.*1[.]?5A", source, re.I))
    f["has_usb_text"] = bool(re.search(r"USB\s*2[.]0.*5V.*500mA", source, re.I))
    return f


def parse_decoded_fields(decoded_texts: Iterable[str]) -> Dict[str, str]:
    f = {}
    for raw in decoded_texts:
        text = (raw or "").strip()
        if not text:
            continue
        if text.upper().startswith("WIFI:"):
            f["wifi_qr"] = text
            sm = re.search(r"(?:^|;)S:([^;]+)", text, re.I)
            pm = re.search(r"(?:^|;)P:([^;]+)", text, re.I)
            if sm: f["qr_ssid"] = sm.group(1)
            if pm: f["qr_wifi_key"] = pm.group(1)
        elif GPON_RE.fullmatch(text):
            f["gpon_sn_barcode"] = text.upper()
        elif SN_RE.fullmatch(text):
            f["sn_barcode"] = text.upper()
        elif MAC_RE.fullmatch(text):
            f["mac_barcode"] = text.upper()
        else:
            # Keep non-WiFi QR payload for debug/future test-programming QR parsing.
            f.setdefault("other_decoded", text)
    return f


def merge_fields(ocr_text: str, decoded_texts: Iterable[str], roi_texts=None) -> Dict[str, str]:
    f = parse_ocr_fields(ocr_text, roi_texts=roi_texts)
    f.update(parse_decoded_fields(decoded_texts))
    f["sn"] = f.get("sn_barcode") or f.get("sn_text", "")
    f["mac"] = f.get("mac_barcode") or f.get("mac_text", "")
    f["gpon_sn"] = f.get("gpon_sn_barcode") or f.get("gpon_sn_text", "")
    return f


def parse_fields(ocr_text: str, decoded_texts=(), roi_texts=None):
    return merge_fields(ocr_text, decoded_texts, roi_texts=roi_texts)
