import re
from typing import Dict, List
from .models import FieldResult


def _fr(name, actual="", expected="", status="INFO", message="", code=""):
    return FieldResult(name=name, actual=str(actual or ""), expected=str(expected or ""), status=status, message=message, error_code=code)


def _eq(a, b):
    return str(a).strip().lower() == str(b).strip().lower()


def _missing_or_result(name, actual, expected, ok, mismatch_code, format_message):
    if not actual:
        return _fr(name, "", expected, "WARN", "Actual value not recognized", "OCR-MISSING")
    return _fr(name, actual, expected, "PASS" if ok else "FAIL", "" if ok else format_message, "" if ok else mismatch_code)


def validate(fields: Dict[str, str], profile: Dict, expected_work_order=None) -> List[FieldResult]:
    expected_work_order = expected_work_order or {}
    rules = profile.get("rules", {})
    out = []

    # FIXED: actual image text must match SPEC/Profile fixed values.
    fixed = profile.get("fixed_fields", {})
    for key, spec_value in fixed.items():
        actual = fields.get(key, "")
        if not actual:
            out.append(_fr(f"Fixed: {key}", "", spec_value, "WARN", "Fixed value not recognized from image", f"OCR-{key.upper()}"))
        else:
            accepted=[str(spec_value)]
            if key=='model': accepted=list(profile.get('model_aliases',[]) or accepted)
            ok = any(_eq(actual, x) for x in accepted)
            expected_display=' / '.join(accepted)
            out.append(_fr(f"Fixed: {key}", actual, expected_display, "PASS" if ok else "FAIL", "" if ok else "Does not match SPEC", "" if ok else f"SPEC-{key.upper()}"))

    for title, key in [
        ("Fixed: GPON VoIP Gateway", "has_gateway_text"),
        ("Fixed: Input 12V 1.5A", "has_input_text"),
        ("Fixed: USB 2.0 5V 500mA", "has_usb_text"),
        ("Fixed: Comtrend Central Europe address", "has_comtrend_address"),
        ("Fixed: CLASS 1 LASER PRODUCT", "has_laser_text"),
    ]:
        present = bool(fields.get(key))
        out.append(_fr(title, "Present" if present else "", "Present in SPEC", "PASS" if present else "WARN", "" if present else "Fixed text not recognized", "" if present else "OCR-FIXED"))

    # VARIABLE: compare against format/rule, not against sample text in SPEC.
    pn = fields.get("pn", "")
    pn_ok = bool(re.fullmatch(rules.get("pn_regex", r"738125-00\d"), pn)) if pn else False
    out.append(_missing_or_result("Variable: P/N Format", pn, rules.get("pn_display", "738125-00X"), pn_ok, "FMT-PN", "P/N format does not match SPEC"))
    if expected_work_order.get("pn") and pn:
        wo = expected_work_order["pn"]
        out.append(_fr("Work Order: P/N", pn, wo, "PASS" if _eq(pn, wo) else "FAIL", "" if _eq(pn, wo) else "Does not match work order", "" if _eq(pn, wo) else "WO-PN"))

    made = fields.get("made_in", "")
    made_ok = made in rules.get("made_in_allowed", ["China", "Taiwan"])
    out.append(_missing_or_result("Variable: Made in Format", made, "China / Taiwan", made_ok, "FMT-MADEIN", "Made in must be China or Taiwan"))
    if expected_work_order.get("made_in") and made:
        wo = expected_work_order["made_in"]
        out.append(_fr("Work Order: Made in", made, wo, "PASS" if _eq(made, wo) else "FAIL", "" if _eq(made, wo) else "Does not match production site", "" if _eq(made, wo) else "WO-MADEIN"))

    # S/N variable
    sn_text = fields.get("sn_text", "")
    sn_bc = fields.get("sn_barcode", "")
    sn_regex = rules["sn_regex"]
    out.append(_missing_or_result("Variable: S/N Human Readable Format", sn_text, rules["sn_display"], bool(sn_text and re.fullmatch(sn_regex, sn_text, re.I)), "FMT-SN-TEXT", "S/N text format invalid"))
    out.append(_missing_or_result("Variable: S/N Barcode Format", sn_bc, f"Code128 data: {rules['sn_display']}", bool(sn_bc and re.fullmatch(sn_regex, sn_bc, re.I)), "FMT-SN-BC", "S/N barcode data format invalid"))
    if sn_text and sn_bc:
        out.append(_fr("Consistency: S/N Text vs Barcode", sn_text, sn_bc, "PASS" if _eq(sn_text, sn_bc) else "FAIL", "" if _eq(sn_text, sn_bc) else "Human-readable differs from barcode", "" if _eq(sn_text, sn_bc) else "XCHK-SN"))
    else:
        out.append(_fr("Consistency: S/N Text vs Barcode", sn_text, sn_bc, "WARN", "Need both values to cross-check"))

    # MAC variable
    mac_text = fields.get("mac_text", "")
    mac_bc = fields.get("mac_barcode", "")
    mac_regex = rules.get("mac_regex", r"[0-9A-F]{12}")
    out.append(_missing_or_result("Variable: MAC Human Readable Format", mac_text, "12 HEX", bool(mac_text and re.fullmatch(mac_regex, mac_text, re.I)), "FMT-MAC-TEXT", "MAC text format invalid"))
    out.append(_missing_or_result("Variable: MAC Barcode Format", mac_bc, "Code128 data: 12 HEX", bool(mac_bc and re.fullmatch(mac_regex, mac_bc, re.I)), "FMT-MAC-BC", "MAC barcode data format invalid"))
    if mac_text and mac_bc:
        out.append(_fr("Consistency: MAC Text vs Barcode", mac_text, mac_bc, "PASS" if _eq(mac_text, mac_bc) else "FAIL", "" if _eq(mac_text, mac_bc) else "Human-readable differs from barcode", "" if _eq(mac_text, mac_bc) else "XCHK-MAC"))
    else:
        out.append(_fr("Consistency: MAC Text vs Barcode", mac_text, mac_bc, "WARN", "Need both values to cross-check"))

    # GPON S/N variable
    gp_text = fields.get("gpon_sn_text", "")
    gp_bc = fields.get("gpon_sn_barcode", "")
    gp_regex = rules.get("gpon_regex", r"434D5444[0-9A-F]{8}")
    out.append(_missing_or_result("Variable: GPON S/N Human Readable Format", gp_text, "434D5444XXXXXXXX", bool(gp_text and re.fullmatch(gp_regex, gp_text, re.I)), "FMT-GPON-TEXT", "GPON S/N text format invalid"))
    out.append(_missing_or_result("Variable: GPON S/N Barcode Format", gp_bc, "Code128 data: 434D5444XXXXXXXX", bool(gp_bc and re.fullmatch(gp_regex, gp_bc, re.I)), "FMT-GPON-BC", "GPON S/N barcode data format invalid"))
    if gp_text and gp_bc:
        out.append(_fr("Consistency: GPON S/N Text vs Barcode", gp_text, gp_bc, "PASS" if _eq(gp_text, gp_bc) else "FAIL", "" if _eq(gp_text, gp_bc) else "Human-readable differs from barcode", "" if _eq(gp_text, gp_bc) else "XCHK-GPON"))
    else:
        out.append(_fr("Consistency: GPON S/N Text vs Barcode", gp_text, gp_bc, "WARN", "Need both values to cross-check"))

    # Variable relationship rules are profile-aware.
    required=set(profile.get("live",{}).get("required_items",[]) or [])
    def needs(*names):
        return (not required) or any(name in required for name in names)

    mac = fields.get("mac", "")

    if needs("Variable: SSID Format","Rule: SSID = MAC Last 6",
             "Consistency: QR SSID vs Printed SSID"):
        ssid = fields.get("ssid", "")
        ssid_prefix = rules.get("ssid_prefix", "")
        if ssid_prefix:
            if ssid:
                ssid_syntax=bool(re.fullmatch(re.escape(ssid_prefix)+r"[0-9A-F]{6}",ssid,re.I))
                out.append(_fr("Variable: SSID Format",ssid,ssid_prefix+"XXXXXX","PASS" if ssid_syntax else "FAIL","" if ssid_syntax else "SSID format invalid","" if ssid_syntax else "FMT-SSID"))
            else:
                out.append(_fr("Variable: SSID Format","",ssid_prefix+"XXXXXX","WARN","SSID not recognized","OCR-SSID"))
            if mac and ssid:
                exp=ssid_prefix+mac[-6:]
                out.append(_fr("Rule: SSID = MAC Last 6",ssid,exp,"PASS" if ssid==exp else "FAIL","" if ssid==exp else "SSID suffix does not match MAC","" if ssid==exp else "RULE-SSID-MAC"))
            else:
                out.append(_fr("Rule: SSID = MAC Last 6",ssid,"Need MAC + SSID","WARN","Cannot evaluate relation"))

    if needs("Rule: GPON S/N = Prefix + MAC Last 8"):
        gpon=fields.get("gpon_sn","")
        gp_prefix=rules.get("gpon_prefix","")
        if mac and gpon and gp_prefix:
            exp=gp_prefix+mac[-8:]
            out.append(_fr("Rule: GPON S/N = Prefix + MAC Last 8",gpon,exp,"PASS" if gpon==exp else "FAIL","" if gpon==exp else "GPON S/N relation invalid","" if gpon==exp else "RULE-GPON-MAC"))
        else:
            out.append(_fr("Rule: GPON S/N = Prefix + MAC Last 8",gpon,"Need MAC + GPON S/N","WARN","Cannot evaluate relation"))

    if needs("Variable: Password Format"):
        password=fields.get("password","")
        pwd_len=int(rules.get("password_length",0) or 0)
        out.append(_missing_or_result("Variable: Password Format",password,f"{pwd_len} characters",bool(pwd_len and len(password)==pwd_len),"FMT-PASSWORD","Password length invalid"))

    if needs("Variable: WiFi Key Format","Consistency: QR Key vs Printed WiFi Key"):
        wifi_key=fields.get("wifi_key","")
        key_len=int(rules.get("wifi_key_length",0) or 0)
        out.append(_missing_or_result("Variable: WiFi Key Format",wifi_key,f"{key_len} characters",bool(key_len and len(wifi_key)==key_len),"FMT-WIFIKEY","WiFi Key length invalid"))
    else:
        wifi_key=""

    if needs("Variable: WiFi QR Format","Consistency: QR SSID vs Printed SSID",
             "Consistency: QR Key vs Printed WiFi Key"):
        wifi_qr=fields.get("wifi_qr","")
        ssid=fields.get("ssid","")
        if wifi_qr:
            qr_ok=bool(re.fullmatch(r"WIFI:T:WPA;S:[^;]+;P:[^;]+;;",wifi_qr))
            out.append(_fr("Variable: WiFi QR Format",wifi_qr,"WIFI:T:WPA;S:<SSID>;P:<WiFi Key>;;","PASS" if qr_ok else "FAIL","" if qr_ok else "WiFi QR syntax invalid","" if qr_ok else "FMT-WIFIQR"))
            qssid=fields.get("qr_ssid","")
            qkey=fields.get("qr_wifi_key","")
            if (not required) or "Consistency: QR SSID vs Printed SSID" in required:
                if ssid:
                    out.append(_fr("Consistency: QR SSID vs Printed SSID",qssid,ssid,"PASS" if qssid==ssid else "FAIL","" if qssid==ssid else "QR SSID differs from printed SSID","" if qssid==ssid else "XCHK-QR-SSID"))
                else:
                    out.append(_fr("Consistency: QR SSID vs Printed SSID",qssid,"Printed SSID unavailable","WARN","Cannot cross-check"))
            if (not required) or "Consistency: QR Key vs Printed WiFi Key" in required:
                if wifi_key:
                    out.append(_fr("Consistency: QR Key vs Printed WiFi Key",qkey,wifi_key,"PASS" if qkey==wifi_key else "FAIL","" if qkey==wifi_key else "QR key differs from printed WiFi Key","" if qkey==wifi_key else "XCHK-QR-KEY"))
                else:
                    out.append(_fr("Consistency: QR Key vs Printed WiFi Key",qkey,"Printed WiFi Key unavailable","WARN","Cannot cross-check"))
        elif (not required) or "Variable: WiFi QR Format" in required:
            out.append(_fr("Variable: WiFi QR Format","","WIFI:T:WPA;S:<SSID>;P:<WiFi Key>;;","WARN","WiFi QR not decoded","DEC-WIFIQR"))

    # Vision fixed graphics remain staged for next version.
    for title in ("Fixed Graphic: COMTREND Logo", "Fixed Graphic: RoHS Logo", "Fixed Graphic: CE Logo", "Fixed Graphic: WEEE Logo", "Fixed Graphic: Green Dot Logo"):
        out.append(_fr(title, "", "Match SPEC artwork", "SKIP", "V1.0.2 keeps graphic-template validation for V1.1"))
    return out


def overall_status(results: List[FieldResult], image_quality_passed=True):
    if not image_quality_passed:
        return "IMAGE_NG"
    if any(r.status == "FAIL" for r in results):
        return "FAIL"
    if any(r.status == "WARN" for r in results):
        return "REVIEW"
    return "PASS"
