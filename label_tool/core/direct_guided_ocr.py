from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
import time
import cv2

from .models import FieldResult
from .ocr_engine import OCREngine


def normalize_text(value: str) -> str:
    s = (value or "").upper()
    s = s.replace("：", ":")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", normalize_text(value))


def similarity(a: str, b: str) -> float:
    aa, bb = normalize_text(a), normalize_text(b)
    if not aa or not bb:
        return 0.0
    return SequenceMatcher(None, aa, bb).ratio()


def best_line_similarity(text: str, expected: str) -> tuple[float, str]:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    if not lines:
        return 0.0, ""
    candidates = list(lines)
    # OCR may split one printed phrase across adjacent lines.
    candidates += [
        f"{lines[i]} {lines[i+1]}"
        for i in range(len(lines)-1)
    ]
    best = max(candidates, key=lambda x: similarity(x, expected))
    return similarity(best, expected), best


def crop_relative(frame, rect):
    if frame is None:
        return None
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = rect
    xa = max(0, min(w-1, int(x1*w)))
    ya = max(0, min(h-1, int(y1*h)))
    xb = max(xa+1, min(w, int(x2*w)))
    yb = max(ya+1, min(h, int(y2*h)))
    return frame[ya:yb, xa:xb].copy()


def sharpness(image) -> float:
    if image is None or image.size == 0:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


@dataclass
class GuidedTarget:
    item: str
    title: str
    instruction: str
    target_rect: list[float] = field(default_factory=lambda: [0.08, 0.28, 0.92, 0.62])
    mode: str = "fuzzy"
    expected: str = ""
    threshold: float = 0.90


DEFAULT_TARGETS = [
    GuidedTarget(
        "Fixed: GPON VoIP Gateway", "GPON VoIP Gateway",
        "Put ONLY the printed phrase 'GPON VoIP Gateway' inside the yellow target box.",
        [0.22,0.415,0.78,0.585], "fuzzy", "GPON VoIP Gateway", 0.86
    ),
    GuidedTarget(
        "Fixed: model", "Model",
        "Put the complete 'Model: GRG-4297u' line inside the yellow target box.",
        [0.20,0.415,0.80,0.585], "model", "GRG-4297u", 0.96
    ),
    GuidedTarget(
        "Variable: P/N Format", "P/N",
        "Put the complete P/N line inside the yellow target box.",
        [0.20,0.415,0.80,0.585], "pn", "", 1.0
    ),
    GuidedTarget(
        "Fixed: Input 12V 1.5A", "Input Rating",
        "Put the complete Input line inside the yellow target box.",
        [0.18,0.405,0.82,0.595], "input", "Input 12V 1.5A", 0.80
    ),
    GuidedTarget(
        "Fixed: USB 2.0 5V 500mA", "USB Rating",
        "Put the complete USB 2.0 line inside the yellow target box.",
        [0.18,0.405,0.82,0.595], "usb", "USB 2.0 5V 500mA", 0.80
    ),
    GuidedTarget(
        "Fixed: ip", "IP Address",
        "Put the complete IP address line inside the yellow target box.",
        [0.22,0.415,0.78,0.585], "ip", "192.168.1.1", 1.0
    ),
    GuidedTarget(
        "Fixed: username", "Username",
        "Put the complete Username line inside the yellow target box.",
        [0.24,0.415,0.76,0.585], "username", "user", 0.88
    ),
    GuidedTarget(
        "Variable: Password Format", "Password",
        "Put the printed Password line inside the yellow target box.",
        [0.20,0.415,0.80,0.585], "password", "", 1.0
    ),
    GuidedTarget(
        "Variable: WiFi Key Format", "WiFi Key",
        "Put the printed WiFi Key line inside the yellow target box. QR decoded WiFi Key is used as ground truth when available.",
        [0.17,0.405,0.83,0.595], "wifi_key", "", 1.0
    ),
    GuidedTarget(
        "Variable: SSID Format", "SSID",
        "Put the printed SSID line inside the yellow target box. QR/MAC locked data is used as ground truth when available.",
        [0.15,0.405,0.85,0.595], "ssid", "", 1.0
    ),
    GuidedTarget(
        "Variable: S/N Human Readable Format", "S/N Human-readable",
        "Put the S/N human-readable text inside the yellow target box. The locked S/N barcode is the expected value.",
        [0.16,0.405,0.84,0.595], "sn_text", "", 1.0
    ),
    GuidedTarget(
        "Variable: MAC Human Readable Format", "MAC Human-readable",
        "Put the MAC human-readable text inside the yellow target box. The locked MAC barcode is the expected value.",
        [0.19,0.415,0.81,0.585], "mac_text", "", 1.0
    ),
    GuidedTarget(
        "Variable: GPON S/N Human Readable Format", "GPON S/N Human-readable",
        "Put the GPON S/N human-readable text inside the yellow target box. The locked GPON barcode is the expected value.",
        [0.16,0.405,0.84,0.595], "gpon_text", "", 1.0
    ),
    GuidedTarget(
        "Variable: Made in Format", "Made in",
        "Put the complete 'Made in China/Taiwan' line inside the yellow target box.",
        [0.20,0.415,0.80,0.585], "made_in", "", 1.0
    ),
    GuidedTarget(
        "Fixed: Comtrend Central Europe address", "Comtrend Address",
        "Put the Comtrend Central Europe / Jankovcova address block inside the yellow target box.",
        [0.15,0.325,0.85,0.675], "address", "Comtrend Central Europe Jankovcova", 0.68
    ),
    GuidedTarget(
        "Fixed: CLASS 1 LASER PRODUCT", "CLASS 1 LASER PRODUCT",
        "Put the complete CLASS 1 LASER PRODUCT phrase inside the yellow target box.",
        [0.18,0.405,0.82,0.595], "fuzzy", "CLASS 1 LASER PRODUCT", 0.84
    ),
]


def targets_from_profile(profile: dict):
    """Return default targets plus profile-defined custom targets.

    Custom targets let a new label profile add fixed/fuzzy OCR fields without
    rewriting the core OCR scheduler. A custom target with the same item name
    replaces the default definition.
    """
    targets = list(DEFAULT_TARGETS)
    custom = profile.get("live", {}).get("custom_targets", []) or []
    required=set(profile.get("live",{}).get("required_items",[]) or [])
    if not custom:
        return [t for t in targets if (not required) or t.item in required]

    by_item = {t.item: t for t in targets}
    order = [t.item for t in targets]
    for raw in custom:
        item = str(raw["item"])
        target = GuidedTarget(
            item=item,
            title=str(raw.get("title", item)),
            instruction=str(raw.get("instruction", f"Put {item} inside the target.")),
            target_rect=list(raw.get("target_rect", [0.12,0.35,0.88,0.65])),
            mode=str(raw.get("mode", "fuzzy")),
            expected=str(raw.get("expected", "")),
            threshold=float(raw.get("threshold", 0.86)),
        )
        if item not in by_item:
            order.append(item)
        by_item[item] = target
    if required:
        order=[item for item in order if item in required]
    return [by_item[item] for item in order]



class GuidedItemScheduler:
    """Manual-camera friendly scheduler.

    It NEVER auto-rotates because of timeout/failure.
    It advances only when the current guided item becomes LOCKED.
    Operator may explicitly Previous / Retry / Next.
    """
    def __init__(self, targets=None):
        self.targets = list(targets or DEFAULT_TARGETS)
        self.index = 0

    @property
    def current(self):
        if not self.targets:
            return None
        return self.targets[self.index]

    def reset(self):
        self.index = 0

    @staticmethod
    def _target_complete(locks, target):
        if target.item not in locks.fields or not locks.is_locked(target.item):
            return False
        # Optional work-order checks share the same camera target and must also
        # complete before advancing.
        if target.item == "Variable: P/N Format" and "Work Order: P/N" in locks.fields:
            return locks.is_locked("Work Order: P/N")
        if target.item == "Variable: Made in Format" and "Work Order: Made in" in locks.fields:
            return locks.is_locked("Work Order: Made in")
        return True

    def select_next_incomplete(self, locks):
        if not self.targets:
            return None
        for _ in range(len(self.targets)):
            t = self.current
            if t.item in locks.fields and not self._target_complete(locks, t):
                return t
            self.index = (self.index + 1) % len(self.targets)
        return None

    def advance_if_locked(self, locks):
        t = self.current
        if t and self._target_complete(locks, t):
            self.index = (self.index + 1) % len(self.targets)
            self.select_next_incomplete(locks)
            return True
        return False

    def next(self, locks):
        if not self.targets:
            return None
        self.index = (self.index + 1) % len(self.targets)
        self.select_next_incomplete(locks)
        return self.current

    def previous(self):
        if not self.targets:
            return None
        self.index = (self.index - 1) % len(self.targets)
        return self.current

    def retry(self):
        return self.current


@dataclass
class GuidedOCRResult:
    item: str
    rows: list[FieldResult]
    raw_text: str
    target_image: object
    sharpness: float
    elapsed_ms: float
    ready: bool
    expected_display: str = ""
    match_score: float = 0.0


class DirectGuidedOCR:
    def __init__(self, profile: dict, ocr_backend=None):
        self.profile = profile
        self.ocr = ocr_backend or OCREngine()

    def set_ocr_backend(self, ocr_backend):
        self.ocr = ocr_backend or OCREngine()

    def set_profile(self, profile: dict):
        self.profile = profile

    def _row(self, name, actual, expected, status, message="", code=""):
        return FieldResult(
            name=name, actual=actual or "", expected=expected or "",
            status=status, message=message, error_code=code
        )

    @staticmethod
    def _extract_labeled_value(text: str, label_pattern: str, value_pattern: str):
        m = re.search(r"(?:" + label_pattern + r")\s*[:.]?\s*(" + value_pattern + r")", text or "", re.I)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _ground_truth(key: str, known: dict) -> str:
        mapping = {
            "sn_text": "sn_barcode",
            "mac_text": "mac_barcode",
            "gpon_text": "gpon_sn_barcode",
            "wifi_key": "qr_wifi_key",
            "ssid": "qr_ssid",
        }
        return (known.get(mapping.get(key, ""), "") or "").strip()

    def _evaluate(self, target: GuidedTarget, text: str, known: dict, expected_wo: dict):
        rules = self.profile.get("rules", {})
        norm = normalize_text(text)
        comp = compact(text)
        rows = []
        score = 0.0
        expected_display = target.expected

        if target.mode == "fuzzy":
            score, best = best_line_similarity(text, target.expected)
            ok = score >= target.threshold
            rows.append(self._row(
                target.item, "Present" if ok else (best or norm),
                target.expected, "PASS" if ok else "WARN",
                f"OCV similarity={score:.3f}" if text else "Target OCR empty",
                "" if ok else "OCR-FUZZY"
            ))
            return rows, target.expected, score

        if target.mode == "model":
            expected = self.profile.get("fixed_fields", {}).get("model", target.expected)
            # Ignore punctuation/spaces but NOT alphanumeric content.
            ok = compact(expected) in comp
            rows.append(self._row(target.item, expected if ok else norm, expected,
                                  "PASS" if ok else "WARN",
                                  "Direct target OCR" if ok else "Model not recognized",
                                  "" if ok else "OCR-MODEL"))
            return rows, expected, 1.0 if ok else 0.0

        if target.mode == "pn":
            expected = (expected_wo.get("pn") or "").strip()
            pattern = rules.get("pn_regex", r"738125-00\d")
            matches = re.findall(pattern, norm, re.I)
            actual = matches[0].upper() if matches else ""
            format_ok = bool(actual)
            rows.append(self._row(
                "Variable: P/N Format", actual, rules.get("pn_display", "738125-00X"),
                "PASS" if format_ok else "WARN",
                "Direct target OCR" if format_ok else "P/N not recognized",
                "" if format_ok else "OCR-PN"
            ))
            if "Work Order: P/N" in known.get("_required_items", []) or expected:
                if actual and expected:
                    rows.append(self._row(
                        "Work Order: P/N", actual, expected,
                        "PASS" if actual.upper() == expected.upper() else "FAIL",
                        "Work-order exact comparison",
                        "" if actual.upper() == expected.upper() else "WO-PN"
                    ))
            return rows, expected or rules.get("pn_display","738125-00X"), 1.0 if format_ok else 0.0

        if target.mode == "input":
            # OCR tolerance for punctuation, but both electrical values must exist.
            has_12v = bool(re.search(r"12\s*V", norm, re.I))
            has_15a = bool(re.search(r"1[\s.,]*5\s*A", norm, re.I))
            ok = has_12v and has_15a
            rows.append(self._row(target.item, "Present" if ok else norm, "12V / 1.5A",
                                  "PASS" if ok else "WARN",
                                  "Structured value match" if ok else "Need both 12V and 1.5A",
                                  "" if ok else "OCR-INPUT"))
            return rows, "12V / 1.5A", 1.0 if ok else 0.0

        if target.mode == "usb":
            has_5v = bool(re.search(r"5\s*V", norm, re.I))
            has_500 = bool(re.search(r"500\s*M?A", norm, re.I))
            ok = has_5v and has_500
            rows.append(self._row(target.item, "Present" if ok else norm, "5V / 500mA",
                                  "PASS" if ok else "WARN",
                                  "Structured value match" if ok else "Need both 5V and 500mA",
                                  "" if ok else "OCR-USB"))
            return rows, "5V / 500mA", 1.0 if ok else 0.0

        if target.mode == "ip":
            expected = self.profile.get("fixed_fields", {}).get("ip", "192.168.1.1")
            matches = re.findall(r"(?:\d{1,3}\.){3}\d{1,3}", norm)
            actual = matches[0] if matches else ""
            ok = actual == expected
            rows.append(self._row(target.item, actual, expected, "PASS" if ok else "WARN",
                                  "Exact IP match" if ok else "IP not recognized/mismatch",
                                  "" if ok else "OCR-IP"))
            return rows, expected, 1.0 if ok else 0.0

        if target.mode == "username":
            expected = self.profile.get("fixed_fields", {}).get("username", "user")
            actual = self._extract_labeled_value(norm, r"USER\s*NAME|USERNAME", r"[A-Z0-9_-]+")
            if not actual and compact(expected) in comp:
                actual = expected
            ok = actual.lower() == expected.lower() if actual else False
            rows.append(self._row(target.item, actual, expected, "PASS" if ok else "WARN",
                                  "Exact username match" if ok else "Username not recognized",
                                  "" if ok else "OCR-USERNAME"))
            return rows, expected, 1.0 if ok else 0.0

        if target.mode == "password":
            value = self._extract_labeled_value(text, r"PASSWORD", r"[A-Za-z0-9]{6,20}")
            required_len = int(rules.get("password_length", 8))
            ok = len(value) == required_len
            rows.append(self._row(target.item, value, f"{required_len} characters",
                                  "PASS" if ok else "WARN",
                                  "Password length match" if ok else "Password not recognized/length mismatch",
                                  "" if ok else "OCR-PASSWORD"))
            return rows, f"{required_len} characters", 1.0 if ok else 0.0

        if target.mode == "wifi_key":
            # Prefer QR decoded value as truth; otherwise validate 14-char format.
            expected = self._ground_truth("wifi_key", known)
            value = self._extract_labeled_value(text, r"WIFI\s*KEY", r"[A-Za-z0-9]{8,24}")
            required_len = int(rules.get("wifi_key_length", 14))
            if expected:
                ok = (expected in (text or "")) or value == expected
                actual = expected if ok else value
                expected_display = expected
            else:
                ok = len(value) == required_len
                actual = value
                expected_display = f"{required_len} characters"
            rows.append(self._row(target.item, actual, expected_display,
                                  "PASS" if ok else "WARN",
                                  "Barcode/QR ground-truth match" if ok and expected else (
                                      "WiFi Key format match" if ok else "WiFi Key not recognized"
                                  ),
                                  "" if ok else "OCR-WIFIKEY"))
            return rows, expected_display, 1.0 if ok else 0.0

        if target.mode == "ssid":
            expected = self._ground_truth("ssid", known)
            if not expected:
                mac = known.get("mac_barcode", "")
                if mac:
                    expected = rules.get("ssid_prefix","Telekom Slovenije_") + mac[-6:]
            # Search expected compact form first, because OCR may alter whitespace.
            if expected and compact(expected) in comp:
                actual = expected
                ok = True
            else:
                m = re.search(r"TELEKOM\s+SLOVENIJE[_\s-]*([0-9A-F]{6})", norm, re.I)
                actual = ("Telekom Slovenije_" + m.group(1).upper()) if m else ""
                ok = bool(actual and (not expected or actual.upper() == expected.upper()))
            expected_display = expected or (rules.get("ssid_prefix","Telekom Slovenije_") + "XXXXXX")
            rows.append(self._row(target.item, actual, expected_display,
                                  "PASS" if ok else "WARN",
                                  "QR/MAC ground-truth match" if ok and expected else (
                                      "SSID format match" if ok else "SSID not recognized/mismatch"
                                  ),
                                  "" if ok else "OCR-SSID"))
            return rows, expected_display, 1.0 if ok else 0.0

        if target.mode in ("sn_text", "mac_text", "gpon_text"):
            expected = self._ground_truth(target.mode, known)
            field_name = {
                "sn_text":"Variable: S/N Human Readable Format",
                "mac_text":"Variable: MAC Human Readable Format",
                "gpon_text":"Variable: GPON S/N Human Readable Format",
            }[target.mode]
            if not expected:
                rows.append(self._row(
                    field_name, "", "Waiting for barcode ground truth", "WARN",
                    "Fast Machine Read must LOCK the barcode first", "WAIT-BARCODE"
                ))
                return rows, "Waiting for barcode", 0.0
            # Alphanumeric comparison ignores label prefix punctuation but requires
            # the complete barcode value to exist in OCR output.
            ok = compact(expected) in comp
            rows.append(self._row(
                field_name, expected if ok else norm, expected,
                "PASS" if ok else "WARN",
                "Matched locked barcode ground truth" if ok else "Human-readable text not matched",
                "" if ok else "OCR-GROUNDTRUTH"
            ))
            return rows, expected, 1.0 if ok else 0.0

        if target.mode == "made_in":
            expected = (expected_wo.get("made_in") or "").strip().title()
            m = re.search(r"MADE\s+IN\s+(CHINA|TAIWAN)", norm, re.I)
            actual = m.group(1).title() if m else ""
            allowed = rules.get("made_in_allowed", ["China","Taiwan"])
            ok = actual in allowed
            rows.append(self._row(
                "Variable: Made in Format", actual, "China / Taiwan",
                "PASS" if ok else "WARN",
                "Direct target OCR" if ok else "Made in not recognized",
                "" if ok else "OCR-MADEIN"
            ))
            if expected:
                rows.append(self._row(
                    "Work Order: Made in", actual, expected,
                    "PASS" if actual and actual.lower() == expected.lower() else "FAIL",
                    "Production-site exact comparison",
                    "" if actual and actual.lower() == expected.lower() else "WO-MADEIN"
                ))
            return rows, expected or "China / Taiwan", 1.0 if ok else 0.0

        if target.mode == "address":
            # Address is multi-line; verify distinctive stable tokens instead of
            # requiring exact OCR of punctuation/ZIP formatting.
            up = normalize_text(text)
            tokens = ["COMTREND", "CENTRAL", "EUROPE", "JANKOVCOVA"]
            hits = sum(1 for t in tokens if t in up)
            score = hits / len(tokens)
            ok = hits >= 3
            rows.append(self._row(
                target.item, "Present" if ok else norm,
                "Comtrend Central Europe + Jankovcova", "PASS" if ok else "WARN",
                f"Address key-token score={hits}/{len(tokens)}",
                "" if ok else "OCR-ADDRESS"
            ))
            return rows, "Comtrend Central Europe / Jankovcova", score

        rows.append(self._row(target.item, norm, target.expected, "WARN", "Unknown target mode"))
        return rows, target.expected, 0.0

    def analyze(self, frame, target: GuidedTarget, known_fields=None, expected_work_order=None,
                min_sharpness: float = 18.0):
        started = time.perf_counter()
        known = dict(known_fields or {})
        expected_wo = dict(expected_work_order or {})
        roi = crop_relative(frame, target.target_rect)
        sp = sharpness(roi)

        if roi is None or roi.size == 0:
            return GuidedOCRResult(
                target.item, [], "", roi, 0.0,
                (time.perf_counter()-started)*1000.0, False, "", 0.0
            )

        # Target-quality gate only. The rest of the frame is irrelevant.
        if sp < min_sharpness:
            return GuidedOCRResult(
                target.item, [
                    self._row(target.item, "", "", "WARN",
                              f"Target too blurry: sharpness={sp:.1f}", "TARGET-BLUR")
                ],
                "", roi, sp, (time.perf_counter()-started)*1000.0,
                False, "", 0.0
            )

        # Do not hide OCR backend/runtime exceptions.
        # The caller owns watchdog/restart/error reporting.
        text, _ = self.ocr.read(roi)

        rows, expected_display, score = self._evaluate(target, text, known, expected_wo)
        return GuidedOCRResult(
            target.item, rows, text, roi, sp,
            (time.perf_counter()-started)*1000.0,
            True, expected_display, score
        )
