from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import json
import logging
import shutil
import uuid
import time

import cv2
import numpy as np
import xlsxwriter

from .engine import InspectionEngine
from .artwork_presence import ArtworkPresenceDetector
from .models import FieldResult

log = logging.getLogger(__name__)

IDENTITY_ITEMS = {
    "Variable: S/N Barcode Format": "sn",
    "Variable: MAC Barcode Format": "mac",
    "Variable: GPON S/N Barcode Format": "gpon_sn",
}

@dataclass
class ImageEvidence:
    item: str
    result: str
    actual: str = ""
    expected: str = ""
    source_image: str = ""
    quality_score: float = 0.0
    message: str = ""
    error_code: str = ""

@dataclass
class MultiImageResult:
    overall: str = "NEED_MORE_IMAGE"
    session_id: str = ""
    session_dir: str = ""
    image_count: int = 0
    initial_image_count: int = 0
    additional_image_count: int = 0
    identity_status: str = "UNKNOWN"
    identity_values: dict = field(default_factory=dict)
    evidence: dict[str, ImageEvidence] = field(default_factory=dict)
    conflicts: dict[str, list[ImageEvidence]] = field(default_factory=dict)
    unresolved_items: list[str] = field(default_factory=list)
    report_path: str = ""

class MultiImageInspectionEngine:
    """Batch multi-photo inspection with per-item evidence fusion.

    A single inspection session may contain multiple photos of the same label.
    Each item keeps its best usable evidence. Blurry/unreadable observations are
    NEED_MORE_IMAGE rather than hard NG. Conflicting high-quality evidence is
    surfaced as CONFLICT and is never silently overwritten.
    """

    def __init__(self, profile: dict, software_version: str = ""):
        self.profile = profile
        self.software_version = software_version
        self.base = InspectionEngine(profile)
        self.artwork = ArtworkPresenceDetector(profile)

    def set_profile(self, profile: dict):
        self.profile = profile
        self.base.set_profile(profile)
        self.artwork.set_profile(profile)

    @staticmethod
    def _safe_load(path: str):
        try:
            return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:
            return None

    @staticmethod
    def _quality_score(q) -> float:
        if q is None:
            return 0.0
        # Bounded ranking score. Sharpness dominates while contrast contributes.
        return float(min(1.0, max(0.0, q.sharpness / 300.0)) * 0.75 + min(1.0, max(0.0, q.contrast / 80.0)) * 0.25)

    @staticmethod
    def _classify_field(row: FieldResult, quality_ok: bool) -> str:
        status = (row.status or "").upper()
        if status == "PASS":
            return "PASS"
        if status in ("WARN", "INFO", "SKIP", "ERROR"):
            return "NEED_MORE_IMAGE" if status != "ERROR" else "ERROR"
        if status == "FAIL":
            # Empty/undetected values on a weak photo are not reliable NG evidence.
            if not quality_ok or not (row.actual or "").strip():
                return "NEED_MORE_IMAGE"
            return "FAIL"
        return "NEED_MORE_IMAGE"

    def _inspect_one(self, image_path: str, session_dir: Path, expected: dict, index: int, target_items=None):
        per_root = session_dir / "per_image"
        per_root.mkdir(parents=True, exist_ok=True)
        one = self.base.inspect(image_path, str(per_root), expected)
        image = self._safe_load(image_path)
        art_rows = []
        if image is not None:
            art_requested=None if target_items is None else [x for x in target_items if str(x).startswith("Artwork: ")]
            art_rows, _ = self.artwork.evaluate(image, requested_items=art_requested)
        rows = list(one.fields)
        existing = {r.name for r in rows}
        for r in art_rows:
            if r.name not in existing:
                rows.append(r)
            else:
                # Artwork engine is authoritative for artwork items.
                rows = [r if x.name == r.name else x for x in rows]
        qscore = self._quality_score(one.quality)
        quality_ok = bool(one.quality and one.quality.passed)
        obs = []
        for row in rows:
            if target_items is not None and row.name not in target_items:
                continue
            obs.append(ImageEvidence(
                item=row.name,
                result=self._classify_field(row, quality_ok),
                actual=row.actual,
                expected=row.expected,
                source_image=Path(image_path).name,
                quality_score=qscore,
                message=row.message,
                error_code=row.error_code,
            ))
        return one, obs

    @staticmethod
    def _better(new: ImageEvidence, old: ImageEvidence | None) -> bool:
        if old is None:
            return True
        rank = {"PASS": 4, "FAIL": 3, "ERROR": 2, "NEED_MORE_IMAGE": 1}
        nr, orr = rank.get(new.result, 0), rank.get(old.result, 0)
        if nr != orr:
            return nr > orr
        return new.quality_score > old.quality_score

    def _required_items(self):
        items = list(self.profile.get("live", {}).get("required_items", []) or [])
        art = self.profile.get("artwork_verification", {}) or {}
        for s in art.get("symbols", []) or []:
            if s.get("required"):
                item = s.get("item") or f"Artwork: {s.get('name', s.get('id','Symbol'))}"
                if item not in items:
                    items.append(item)
        return items

    def inspect_batch(self, image_paths: list[str], output_root="image_records", expected=None,
                      previous_session: MultiImageResult | None = None, progress_callback=None,
                      cancel_event=None, target_items=None) -> MultiImageResult:
        if not image_paths:
            raise ValueError("No images selected")
        expected = dict(expected or {})
        started = datetime.now()
        sid = previous_session.session_id if previous_session else f"{started:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        session_dir = Path(previous_session.session_dir) if previous_session else Path(output_root) / sid
        session_dir.mkdir(parents=True, exist_ok=True)
        src_dir = session_dir / "source_images"; src_dir.mkdir(exist_ok=True)
        execution_log = session_dir / "execution.log"
        test_log = session_dir / "test.log"
        debug_log = session_dir / "debug.log"
        performance_log = session_dir / "performance.log"

        def write(path: Path, text: str):
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().isoformat(timespec='milliseconds')} | {text}\n")

        result = previous_session or MultiImageResult(session_id=sid, session_dir=str(session_dir))
        targets = None if target_items is None else set(target_items)
        def progress(stage, index=0, total=0, image="", elapsed_ms=None, **extra):
            if progress_callback:
                try: progress_callback({"stage":stage,"index":index,"total":total,"image":image,"elapsed_ms":elapsed_ms,**extra})
                except Exception: pass
        def cancelled():
            return bool(cancel_event is not None and getattr(cancel_event,"is_set",lambda:False)())
        if not previous_session:
            result.initial_image_count = len(image_paths)
        else:
            result.additional_image_count += len(image_paths)
        write(execution_log, f"IMAGE_INSPECTION_START profile={self.profile.get('profile_name','')} add_count={len(image_paths)} targets={sorted(targets) if targets is not None else 'ALL'}")
        progress("batch_start",0,len(image_paths),"")

        # Gather existing evidence/conflicts for incremental add-images flow.
        best = dict(result.evidence)
        conflicts = {k:list(v) for k,v in result.conflicts.items()}
        identity_sets = {k:set([v]) if v else set() for k,v in result.identity_values.items()}

        for idx, src in enumerate(image_paths, 1):
            if cancelled():
                write(execution_log, f"IMAGE_INSPECTION_CANCELLED before_index={idx}")
                progress("cancelled",idx-1,len(image_paths),"")
                raise RuntimeError("Image inspection cancelled by user")
            image_started=time.perf_counter()
            src_path = Path(src)
            progress("processing",idx,len(image_paths),src_path.name)
            copy_started=time.perf_counter()
            dest = src_dir / f"{result.image_count + idx:02d}_{src_path.name}"
            if not dest.exists():
                shutil.copy2(src_path, dest)
            copy_ms=(time.perf_counter()-copy_started)*1000.0
            inspect_started=time.perf_counter()
            if targets is None:
                one, observations = self._inspect_one(str(src_path), session_dir, expected, result.image_count + idx)
            else:
                one, observations = self._inspect_one(str(src_path), session_dir, expected, result.image_count + idx, target_items=targets)
            inspect_ms=(time.perf_counter()-inspect_started)*1000.0
            q = one.quality
            total_ms=(time.perf_counter()-image_started)*1000.0
            write(performance_log, f"IMAGE index={idx}/{len(image_paths)} file={src_path.name} copy_ms={copy_ms:.1f} inspect_ms={inspect_ms:.1f} total_ms={total_ms:.1f} target_count={len(targets) if targets is not None else 'ALL'}")
            write(debug_log, f"IMAGE file={src_path.name} overall={one.overall} quality_pass={bool(q and q.passed)} sharpness={getattr(q,'sharpness',0):.1f} errors={one.error_codes}")

            for ev in observations:
                write(debug_log, f"EVIDENCE item={ev.item} result={ev.result} q={ev.quality_score:.3f} source={ev.source_image} actual={ev.actual!r} code={ev.error_code} msg={ev.message}")
                if ev.item in IDENTITY_ITEMS and ev.result == "PASS" and ev.actual:
                    identity_sets.setdefault(IDENTITY_ITEMS[ev.item], set()).add(ev.actual.strip().upper())
                old = best.get(ev.item)
                # High-quality contradictory PASS/FAIL => explicit conflict.
                if old and {old.result, ev.result} == {"PASS", "FAIL"} and min(old.quality_score, ev.quality_score) >= 0.45:
                    bucket = conflicts.setdefault(ev.item, [])
                    if not bucket:
                        bucket.append(old)
                    bucket.append(ev)
                    continue
                if self._better(ev, old):
                    best[ev.item] = ev
            progress("image_done",idx,len(image_paths),src_path.name,elapsed_ms=total_ms)

        result.image_count += len(image_paths)
        result.evidence = best
        result.conflicts = conflicts
        result.identity_values = {k:(sorted(v)[0] if len(v)==1 else " | ".join(sorted(v))) for k,v in identity_sets.items() if v}
        mismatch = {k:v for k,v in identity_sets.items() if len(v)>1}
        result.identity_status = "MISMATCH" if mismatch else ("PASS" if any(identity_sets.values()) else "UNKNOWN")

        required = self._required_items()
        unresolved = []
        hard_fail = []
        for item in required:
            if item in conflicts:
                continue
            ev = best.get(item)
            if ev is None or ev.result in ("NEED_MORE_IMAGE", "ERROR"):
                unresolved.append(item)
            elif ev.result == "FAIL":
                hard_fail.append(item)
        result.unresolved_items = unresolved

        if result.identity_status == "MISMATCH":
            result.overall = "IDENTITY_MISMATCH"
        elif conflicts:
            result.overall = "CONFLICT"
        elif hard_fail:
            result.overall = "FAIL"
        elif unresolved:
            result.overall = "NEED_MORE_IMAGE"
        else:
            result.overall = "PASS"

        write(test_log, f"RESULT overall={result.overall} images={result.image_count} identity={result.identity_status} unresolved={unresolved} conflicts={list(conflicts)} hard_fail={hard_fail}")
        write(execution_log, f"IMAGE_INSPECTION_END overall={result.overall} total_images={result.image_count}")

        report_started=time.perf_counter()
        progress("report",len(image_paths),len(image_paths),"")
        result.report_path = self._write_excel(result, expected)
        (session_dir / "result.json").write_text(json.dumps(self._serialize(result), ensure_ascii=False, indent=2), encoding="utf-8")
        report_ms=(time.perf_counter()-report_started)*1000.0
        write(performance_log,f"REPORT excel_json_ms={report_ms:.1f} overall={result.overall}")
        progress("completed",len(image_paths),len(image_paths),"",elapsed_ms=report_ms)
        return result

    def _serialize(self, result: MultiImageResult):
        return {
            "overall": result.overall,
            "session_id": result.session_id,
            "image_count": result.image_count,
            "initial_image_count": result.initial_image_count,
            "additional_image_count": result.additional_image_count,
            "identity_status": result.identity_status,
            "identity_values": result.identity_values,
            "unresolved_items": result.unresolved_items,
            "evidence": {k:asdict(v) for k,v in result.evidence.items()},
            "conflicts": {k:[asdict(x) for x in v] for k,v in result.conflicts.items()},
            "report_path": result.report_path,
        }

    def _write_excel(self, result: MultiImageResult, expected: dict):
        p = Path(result.session_dir) / f"Label_Image_Inspection_Report_{result.session_id}.xlsx"
        wb=xlsxwriter.Workbook(str(p))
        h=wb.add_format({"bold":True,"bg_color":"#4472C4","font_color":"#FFFFFF","border":1})
        c=wb.add_format({"border":1,"text_wrap":True,"valign":"top"})
        good=wb.add_format({"border":1,"bg_color":"#E2F0D9","font_color":"#006100","bold":True})
        bad=wb.add_format({"border":1,"bg_color":"#FCE4D6","font_color":"#9C0006","bold":True})
        warn=wb.add_format({"border":1,"bg_color":"#FFF2CC","font_color":"#7F6000","bold":True})
        ws=wb.add_worksheet("Summary")
        rows=[
            ("Overall",result.overall),("Inspection Mode","MULTI_IMAGE"),("Profile",self.profile.get("profile_name","")),
            ("Label Type",self.profile.get("label_type","")),("Software Version",self.software_version),
            ("Session ID",result.session_id),("Images Loaded",result.image_count),("Initial Batch",result.initial_image_count),
            ("Additional Images",result.additional_image_count),("Identity Check",result.identity_status),
            ("S/N",result.identity_values.get("sn","")),("MAC",result.identity_values.get("mac","")),
            ("GPON S/N",result.identity_values.get("gpon_sn","")),("Work Order P/N",expected.get("pn","")),
            ("Made in",expected.get("made_in","")),("Need More Image",", ".join(result.unresolved_items)),
            ("Conflicts",", ".join(result.conflicts.keys())),
        ]
        ws.set_column(0,0,24); ws.set_column(1,1,80)
        for r,(k,v) in enumerate(rows):
            ws.write(r,0,k,h)
            fmt=good if k=="Overall" and result.overall=="PASS" else bad if k=="Overall" and result.overall in ("FAIL","IDENTITY_MISMATCH","CONFLICT") else warn if k=="Overall" else c
            ws.write(r,1,str(v),fmt)
        out=wb.add_worksheet("Inspection_Result")
        heads=["Item","Result","Actual","Expected","Evidence Image","Quality Score","Message","Error Code"]
        for col,name in enumerate(heads): out.write(0,col,name,h)
        out.set_column(0,0,42); out.set_column(1,1,18); out.set_column(2,3,30); out.set_column(4,4,36); out.set_column(5,5,14); out.set_column(6,7,55)
        all_items=self._required_items()
        for r,item in enumerate(all_items,1):
            ev=result.evidence.get(item)
            if item in result.conflicts:
                vals=[item,"CONFLICT","","","Multiple images","", "Conflicting high-quality evidence",""]
            elif ev:
                vals=[item,ev.result,ev.actual,ev.expected,ev.source_image,round(ev.quality_score,3),ev.message,ev.error_code]
            else:
                vals=[item,"NEED_MORE_IMAGE","","","","","No usable evidence",""]
            for col,v in enumerate(vals): out.write(r,col,v,c)
        imgs=wb.add_worksheet("Image_Evidence")
        imgs.write_row(0,0,["Item","Evidence Image","Result","Quality Score","Actual","Message"],h)
        rr=1
        for item,ev in result.evidence.items():
            imgs.write_row(rr,0,[item,ev.source_image,ev.result,round(ev.quality_score,3),ev.actual,ev.message],c); rr+=1
        for item,evs in result.conflicts.items():
            for ev in evs:
                imgs.write_row(rr,0,[item,ev.source_image,"CONFLICT:"+ev.result,round(ev.quality_score,3),ev.actual,ev.message],c); rr+=1
        wb.close()
        return str(p)
