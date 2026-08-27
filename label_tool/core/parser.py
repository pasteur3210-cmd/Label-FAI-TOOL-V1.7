import re
from typing import Dict, Iterable

# Legacy GRG-4297u patterns are intentionally preserved for bundled profiles.
LEGACY_MAC_RE = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{12}(?![0-9A-Fa-f])")
LEGACY_GPON_RE = re.compile(r"(?<![0-9A-Fa-f])434D5444[0-9A-Fa-f]{8}(?![0-9A-Fa-f])", re.I)
LEGACY_SN_RE = re.compile(r"(?<![A-Za-z0-9])\d{2}[1-9A-Ca-c]4297UF-[A-Za-z0-9]{2}\d{6}(?![A-Za-z0-9])")
LEGACY_PN_RE = re.compile(r"\b738125-00\d\b")
LEGACY_SSID_RE = re.compile(r"Telekom\s+Slovenije[_\s-]*([0-9A-Fa-f]{6})", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _search(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def _is_dynamic(profile):
    return bool((profile or {}).get("dynamic_profile"))


def _rule_re(profile, key, fallback):
    raw = str(((profile or {}).get("rules", {}) or {}).get(key, fallback) or fallback)
    try:
        return re.compile(raw, re.I)
    except re.error:
        return re.compile(fallback, re.I)


def _first_labeled(text: str, labels, value_re: str):
    labels_alt = "|".join(labels)
    m = re.search(rf"(?:{labels_alt})\s*[:：.]?\s*({value_re})", text or "", re.I)
    return m.group(1).strip() if m else ""


def _parse_ocr_fields_dynamic(ocr_text: str, roi_texts=None, profile=None) -> Dict[str, str]:
    roi_texts = roi_texts or {}
    roi_join = {k: _clean(v) for k, v in roi_texts.items()}
    t = _clean(ocr_text)
    source = _clean(" ".join([*roi_join.values(), t]))
    rules = (profile or {}).get("rules", {}) or {}
    f = {}

    # Prefer explicit label anchors. Dynamic Goldens may have completely
    # different model/SN/P/N formats, so do not use GRG-4297u literals here.
    sn = _first_labeled(source, [r"S\s*/\s*N", r"Serial\s*No(?:\.|umber)?"], r"[A-Z0-9-]{8,40}")
    if sn and _rule_re(profile, "sn_regex", r"[A-Z0-9-]{8,40}").fullmatch(sn):
        f["sn_text"] = sn.upper()

    gp = _first_labeled(source, [r"GPON\s*S\s*/?\s*N", r"GPON\s*SN"], r"[A-Z0-9]{12,24}")
    if gp and _rule_re(profile, "gpon_regex", r"[A-Z0-9]{12,24}").fullmatch(gp):
        f["gpon_sn_text"] = gp.upper()

    mac = _first_labeled(source, [r"MAC(?:\s*Address)?"], r"[0-9A-F]{12}")
    if mac and _rule_re(profile, "mac_regex", r"[0-9A-F]{12}").fullmatch(mac):
        f["mac_text"] = mac.upper()

    pn = _first_labeled(source, [r"P\s*/\s*N", r"Part\s*No(?:\.|\s*Number)?"], r"[0-9A-Z-]{5,32}")
    if pn and _rule_re(profile, "pn_regex", r"[0-9A-Z-]{5,32}").fullmatch(pn):
        f["pn"] = pn.upper()

    ssid = _first_labeled(source, [r"SSID"], r"[A-Za-z0-9_.-]{3,64}")
    if ssid:
        f["ssid"] = ssid

    wifi_key = _first_labeled(source, [r"WiFi\s*Key", r"WIFI\s*KEY"], r"[A-Za-z0-9]{4,64}")
    if wifi_key:
        f["wifi_key"] = wifi_key

    password = _first_labeled(source, [r"Password"], r"[A-Za-z0-9]{4,64}")
    if password:
        f["password"] = password

    model = _first_labeled(source, [r"Model(?:\s*Name)?"], r"[A-Za-z0-9_.-]{3,40}")
    if model:
        f["model"] = model

    made = _search(r"Made\s+in\s+(China|Taiwan)", source, re.I)
    if made:
        f["made_in"] = made.title()

    # Generic presence flags retained because role classification uses them.
    low = source.lower()
    f["has_gateway_text"] = "gpon voip gateway" in low or "home gateway" in low
    f["has_comtrend_address"] = "comtrend" in low and ("czech" in low or "iberia" in low)
    f["has_laser_text"] = "class 1 laser product" in low
    f["has_input_text"] = bool(re.search(r"\bInput\s*[:：]?\s*12\s*V(?:DC)?", source, re.I))
    f["has_usb_text"] = bool(re.search(r"\bUSB\s*3(?:\.0)?\s*[:：]?\s*5\s*V", source, re.I))
    return f


def _parse_ocr_fields_legacy(ocr_text: str, roi_texts=None) -> Dict[str, str]:
    roi_texts = roi_texts or {}
    t = _clean(ocr_text)
    f = {}
    roi_join = {k: _clean(v) for k, v in roi_texts.items()}

    candidates = [roi_join.get("sn_text", ""), t]
    for c in candidates:
        m = LEGACY_SN_RE.search(c)
        if m:
            f["sn_text"] = m.group(0).upper(); break

    candidates = [roi_join.get("gpon_text", ""), t]
    for c in candidates:
        m = LEGACY_GPON_RE.search(c)
        if m:
            f["gpon_sn_text"] = m.group(0).upper(); break

    candidates = [roi_join.get("mac_text", ""), t]
    for c in candidates:
        tmp = LEGACY_GPON_RE.sub(" ", LEGACY_SN_RE.sub(" ", c))
        ms = [m.group(0).upper() for m in LEGACY_MAC_RE.finditer(tmp)]
        if ms:
            f["mac_text"] = ms[0]; break

    for c in [roi_join.get("pn", ""), t]:
        m = LEGACY_PN_RE.search(c)
        if m:
            f["pn"] = m.group(0); break

    for c in [roi_join.get("ssid_password_wifi", ""), t]:
        m = LEGACY_SSID_RE.search(c)
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


def parse_ocr_fields(ocr_text: str, roi_texts=None, profile=None) -> Dict[str, str]:
    if _is_dynamic(profile):
        return _parse_ocr_fields_dynamic(ocr_text, roi_texts=roi_texts, profile=profile)
    return _parse_ocr_fields_legacy(ocr_text, roi_texts=roi_texts)


def _parse_generic_qr_payload(text: str, out: Dict[str, str], profile=None):
    # Production-programming QR used by controlled Golden forms. Example:
    # S/N: ... MAC: ... WPA: <WiFiKey>. Preserve full payload and expose facts.
    compact = _clean(text)
    sn_pat = _rule_re(profile, "sn_regex", r"[A-Z0-9-]{8,40}").pattern
    m = re.search(r"(?:S\s*/\s*N|SN)\s*[:：.]?\s*(" + sn_pat + r")", compact, re.I)
    sn = m.group(1) if m else ""
    mac = _first_labeled(compact, [r"MAC"], r"[0-9A-F]{12}")
    key = _first_labeled(compact, [r"WPA", r"WiFi\s*Key", r"KEY"], r"[A-Za-z0-9]{4,64}")
    ssid = _first_labeled(compact, [r"SSID"], r"[A-Za-z0-9_.-]{3,64}")
    if sn or mac or key or ssid:
        out.setdefault("wifi_qr", compact)
        if sn: out.setdefault("qr_sn", sn.upper())
        if mac: out.setdefault("qr_mac", mac.upper())
        if key: out.setdefault("qr_wifi_key", key)
        if ssid: out.setdefault("qr_ssid", ssid)
        return True
    return False

def parse_decoded_fields(decoded_texts: Iterable[str], profile=None, preferred_fields=None) -> Dict[str, str]:
    f = {}
    preferred_fields = preferred_fields or {}
    dynamic = _is_dynamic(profile)
    sn_re = _rule_re(profile, "sn_regex", r"[A-Z0-9-]{8,40}") if dynamic else LEGACY_SN_RE
    mac_re = _rule_re(profile, "mac_regex", r"[0-9A-F]{12}") if dynamic else LEGACY_MAC_RE
    gp_re = _rule_re(profile, "gpon_regex", r"[A-Z0-9]{12,24}") if dynamic else LEGACY_GPON_RE
    sn_candidates=[]; mac_candidates=[]; gp_candidates=[]

    for raw in decoded_texts:
        text = (raw or "").strip()
        if not text:
            continue
        if text.upper().startswith("WIFI:"):
            f.setdefault("wifi_qr", text)
            sm = re.search(r"(?:^|;)S:([^;]+)", text, re.I)
            pm = re.search(r"(?:^|;)P:([^;]+)", text, re.I)
            if sm: f.setdefault("qr_ssid", sm.group(1))
            if pm: f.setdefault("qr_wifi_key", pm.group(1))
        elif dynamic and _parse_generic_qr_payload(text, f, profile=profile):
            pass
        elif dynamic and str((profile or {}).get('rules',{}).get('gpon_prefix','') or '') and text.upper().startswith(str((profile or {}).get('rules',{}).get('gpon_prefix','')).upper()) and gp_re.fullmatch(text):
            # Controlled GPON prefix wins over a broad S/N pattern. This avoids
            # a GPON barcode becoming a second S/N and triggering false identity mismatch.
            gp_candidates.append(text.upper())
        elif mac_re.fullmatch(text):
            # A 12-HEX MAC also matches broad generic GPON regexes. MAC wins.
            mac_candidates.append(text.upper())
        elif sn_re.fullmatch(text):
            sn_candidates.append(text.upper())
        elif gp_re.fullmatch(text):
            gp_candidates.append(text.upper())
        else:
            f.setdefault("other_decoded", text)

    def choose(candidates, preferred):
        if preferred:
            for c in candidates:
                if c.upper() == str(preferred).upper():
                    return c
        return candidates[0] if candidates else ""

    sn = choose(sn_candidates, preferred_fields.get("sn_text"))
    mac = choose(mac_candidates, preferred_fields.get("mac_text"))
    gp = choose(gp_candidates, preferred_fields.get("gpon_sn_text"))
    if sn: f["sn_barcode"] = sn
    if mac: f["mac_barcode"] = mac
    if gp: f["gpon_sn_barcode"] = gp
    if sn_candidates: f["_sn_barcode_candidates"] = sn_candidates
    if mac_candidates: f["_mac_barcode_candidates"] = mac_candidates
    if gp_candidates: f["_gpon_barcode_candidates"] = gp_candidates
    return f


def merge_fields(ocr_text: str, decoded_texts: Iterable[str], roi_texts=None, profile=None) -> Dict[str, str]:
    f = parse_ocr_fields(ocr_text, roi_texts=roi_texts, profile=profile)
    decoded = parse_decoded_fields(decoded_texts, profile=profile, preferred_fields=f)
    f.update(decoded)
    f["sn"] = f.get("sn_barcode") or f.get("sn_text", "")
    f["mac"] = f.get("mac_barcode") or f.get("mac_text", "")
    f["gpon_sn"] = f.get("gpon_sn_barcode") or f.get("gpon_sn_text", "")
    return f


def parse_fields(ocr_text: str, decoded_texts=(), roi_texts=None, profile=None):
    return merge_fields(ocr_text, decoded_texts, roi_texts=roi_texts, profile=profile)
