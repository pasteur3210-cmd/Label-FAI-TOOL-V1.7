from __future__ import annotations

from dataclasses import dataclass, field
import time
import cv2

from .parser import parse_decoded_fields
from .models import FieldResult


@dataclass
class FastMachineResult:
    decoded_texts: list[str] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    rows: list[FieldResult] = field(default_factory=list)
    elapsed_ms: float = 0.0


class FastMachineReader:
    """Fast path copied conceptually from the proven GRG-4297u FQC Tool.

    Important design:
    - use the raw/latest Camera frame
    - exactly one zxingcpp.read_barcodes() call per cycle
    - no Label Detection
    - no perspective correction
    - no ROI crop
    - no resize/threshold/rotation variant loop
    - no OCR
    """

    def __init__(self, profile: dict):
        self.profile = profile

    def set_profile(self, profile: dict):
        self.profile = profile

    @staticmethod
    def _zxing():
        try:
            import zxingcpp
            return zxingcpp
        except Exception as exc:
            raise RuntimeError(
                "zxing-cpp unavailable. Install requirements.txt or use GitHub Windows build."
            ) from exc

    def read(self, frame) -> FastMachineResult:
        started = time.perf_counter()
        if frame is None:
            return FastMachineResult(elapsed_ms=0.0)

        zxingcpp = self._zxing()

        # Match the proven FQC implementation: one RGB full-frame decode.
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        raw = zxingcpp.read_barcodes(rgb)
        texts = []
        seen = set()
        for item in raw:
            text = (getattr(item, "text", "") or "").strip()
            if text and text not in seen:
                seen.add(text)
                texts.append(text)

        fields = parse_decoded_fields(texts, profile=self.profile)
        rules = self.profile.get("rules", {})
        rows = []

        def add(name, key, expected):
            value = fields.get(key, "")
            if value:
                rows.append(FieldResult(
                    name=name,
                    actual=value,
                    expected=expected,
                    status="PASS",
                    message="Fast full-frame direct decode",
                    error_code="",
                ))

        add(
            "Variable: S/N Barcode Format",
            "sn_barcode",
            rules.get("sn_display", "Valid S/N Code128"),
        )
        add(
            "Variable: MAC Barcode Format",
            "mac_barcode",
            "12 HEX Code128",
        )
        add(
            "Variable: GPON S/N Barcode Format",
            "gpon_sn_barcode",
            "434D5444 + 8 HEX Code128",
        )
        add(
            "Variable: WiFi QR Format",
            "wifi_qr",
            "WIFI:T:WPA;S:<SSID>;P:<WiFi Key>;;",
        )

        return FastMachineResult(
            decoded_texts=texts,
            fields=fields,
            rows=rows,
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
        )
