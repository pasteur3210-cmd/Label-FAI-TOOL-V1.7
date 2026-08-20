from __future__ import annotations

from dataclasses import dataclass, field
import time

from .direct_guided_ocr import (
    DirectGuidedOCR, DEFAULT_TARGETS, targets_from_profile, crop_relative, sharpness
)
from .artwork_presence import ArtworkPresenceDetector


@dataclass
class ProductionZone:
    id: str
    title: str
    instruction: str
    target_rect: list[float]
    items: list[str]

    def snapshot(self) -> dict:
        return {
            "id": str(self.id),
            "title": str(self.title),
            "instruction": str(self.instruction),
            "target_rect": tuple(float(v) for v in self.target_rect),
            "items": list(self.items),
        }

    @classmethod
    def from_snapshot(cls, data: dict):
        return cls(
            id=str(data["id"]), title=str(data["title"]),
            instruction=str(data["instruction"]),
            target_rect=list(data["target_rect"]),
            items=list(data["items"]),
        )


DEFAULT_PRODUCTION_ZONES = [
    ProductionZone(
        "A", "ZONE A - Basic Information",
        "請將 Label 上方基本資訊完整放入黃色區域。程式會一次辨識 GPON / Model / P/N / Input / USB / IP / Username。",
        [0.08,0.18,0.92,0.80],
        [
            "Fixed: GPON VoIP Gateway", "Fixed: model", "Variable: P/N Format",
            "Fixed: Input 12V 1.5A", "Fixed: USB 2.0 5V 500mA",
            "Fixed: ip", "Fixed: username",
        ],
    ),
    ProductionZone(
        "B", "ZONE B - Wi-Fi Information",
        "請將 Password / WiFi Key / SSID 區域完整放入黃色區域。WiFi QR 仍由 Full-frame Fast Machine Reader 獨立掃描。",
        [0.08,0.24,0.92,0.76],
        ["Variable: Password Format", "Variable: WiFi Key Format", "Variable: SSID Format"],
    ),
    ProductionZone(
        "C", "ZONE C - Device Identity",
        "請將 S/N / MAC / GPON S/N 人眼文字區域完整放入黃色區域。三個 Barcode 仍由 Full-frame Fast Machine Reader 獨立掃描。",
        [0.08,0.18,0.92,0.82],
        [
            "Variable: S/N Human Readable Format",
            "Variable: MAC Human Readable Format",
            "Variable: GPON S/N Human Readable Format",
        ],
    ),
    ProductionZone(
        "D", "ZONE D - Compliance / Bottom Label",
        "請將 Made in / Comtrend Central Europe 地址 / CLASS 1 LASER PRODUCT 區域完整放入黃色區域。",
        [0.06,0.14,0.94,0.86],
        [
            "Variable: Made in Format",
            "Fixed: Comtrend Central Europe address",
            "Fixed: CLASS 1 LASER PRODUCT",
        ],
    ),
]


class ProductionZoneScheduler:
    def __init__(self, zones=None):
        self.zones=list(zones or DEFAULT_PRODUCTION_ZONES)
        self.index=0

    @classmethod
    def from_profile(cls, profile: dict):
        configured=profile.get("live",{}).get("production_zones",[])
        if not configured:
            return cls()
        return cls([
            ProductionZone(
                str(z["id"]),str(z["title"]),str(z["instruction"]),
                list(z["target_rect"]),list(z["items"])
            ) for z in configured
        ])

    @property
    def current(self):
        return self.zones[self.index] if self.zones else None

    def reset(self): self.index=0

    @staticmethod
    def effective_items(zone: ProductionZone, locks) -> list[str]:
        items=[x for x in zone.items if x in locks.fields]
        if "Variable: P/N Format" in zone.items and "Work Order: P/N" in locks.fields:
            items.append("Work Order: P/N")
        if "Variable: Made in Format" in zone.items and "Work Order: Made in" in locks.fields:
            items.append("Work Order: Made in")
        return items

    def is_complete(self, zone: ProductionZone, locks) -> bool:
        items=self.effective_items(zone,locks)
        return bool(items) and all(locks.is_locked(x) for x in items)

    def select_next_incomplete(self, locks):
        if not self.zones: return None
        for _ in range(len(self.zones)):
            z=self.current
            if not self.is_complete(z,locks): return z
            self.index=(self.index+1)%len(self.zones)
        return None

    def advance_if_complete(self, locks) -> bool:
        z=self.current
        if z and self.is_complete(z,locks):
            self.index=(self.index+1)%len(self.zones)
            self.select_next_incomplete(locks)
            return True
        return False

    def next(self, locks):
        if not self.zones:return None
        self.index=(self.index+1)%len(self.zones)
        self.select_next_incomplete(locks)
        return self.current

    def previous(self):
        if not self.zones:return None
        self.index=(self.index-1)%len(self.zones)
        return self.current

    def retry(self): return self.current

    def progress(self, zone: ProductionZone, locks):
        items=self.effective_items(zone,locks)
        return sum(1 for x in items if locks.is_locked(x)),len(items)


@dataclass
class ZoneOCRResult:
    zone_id: str
    zone_title: str
    rows: list
    raw_text: str
    target_image: object
    sharpness: float
    elapsed_ms: float
    ready: bool
    evaluated_items: list[str]=field(default_factory=list)
    pass_items: list[str]=field(default_factory=list)


class MultiFieldZoneOCR:
    """Run OCR ONCE for a zone, then evaluate multiple existing field rules."""
    def __init__(self, profile: dict, ocr_backend=None):
        self.profile=profile
        self.direct=DirectGuidedOCR(profile,ocr_backend=ocr_backend)
        self._target_by_item={t.item:t for t in targets_from_profile(profile)}
        self.artwork=ArtworkPresenceDetector(profile)

    def set_profile(self, profile: dict):
        self.profile=profile
        self.direct.set_profile(profile)
        self._target_by_item={t.item:t for t in targets_from_profile(profile)}
        self.artwork.set_profile(profile)

    def set_ocr_backend(self, backend):
        self.direct.set_ocr_backend(backend)

    def analyze(self, frame, zone: ProductionZone, known: dict, expected_wo: dict,
                min_sharpness: float=18.0, requested_items=None):
        started=time.perf_counter()
        requested=set(requested_items or zone.items)
        eval_items=[x for x in zone.items if x in requested]

        # V1.7.2 artwork detector receives the FULL frame, internally normalizes the label,
        # then judges shape + relative position. Printed size is intentionally ignored.
        artwork_items=[x for x in eval_items if x.startswith("Artwork: ")]
        art_rows,_=self.artwork.evaluate(frame,artwork_items)

        roi=crop_relative(frame,zone.target_rect)
        sh=sharpness(roi) if roi is not None and getattr(roi,"size",0) else 0.0
        rows=list(art_rows)
        pass_items=[r.name for r in art_rows if r.status=="PASS"]
        raw_text=""

        text_items=[x for x in eval_items if not x.startswith("Artwork: ")]
        ocr_ready=bool(roi is not None and getattr(roi,"size",0) and sh>=min_sharpness)
        if text_items and ocr_ready:
            raw_text,_=self.direct.ocr.read(roi)
            for item in text_items:
                target=self._target_by_item.get(item)
                if not target:
                    continue
                target_rows,_,_=self.direct._evaluate(target,raw_text,known,expected_wo)
                rows.extend(target_rows)
                if any(r.name==item and r.status=="PASS" for r in target_rows):
                    pass_items.append(item)

        return ZoneOCRResult(
            zone.id,zone.title,rows,raw_text or "",roi,sh,
            (time.perf_counter()-started)*1000.0,
            ocr_ready or bool(art_rows),eval_items,pass_items
        )
