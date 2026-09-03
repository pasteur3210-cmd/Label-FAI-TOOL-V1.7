from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from .profile_manager import external_profile_dir


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(text: str) -> str:
    s = re.sub(r'[^A-Za-z0-9._-]+', '_', str(text or '').strip()).strip('_.')
    return s or 'dynamic_profile'


def _candidate_label_type(source_name: str, text: str, fallback: str='') -> str:
    low=(str(source_name or '')+' '+str(text or '')[:1600]).lower()
    # V1.9.23: label family belongs in Label Type, never in Internal Model.
    # Support common controlled-form wording and legacy filename typo "Caron".
    if 'inner box' in low or 'inner_box' in low:
        return 'Inner Box Label'
    if 'chassis' in low:
        return 'Chassis Label'
    if 'carton label' in low or 'carton_label' in low or 'caron label' in low:
        return 'Carton Label'
    return fallback or 'Label'


def _normalize_internal_model(model: str, label_type: str='') -> str:
    """Keep physical label family out of Internal Model metadata.

    Dynamic Profile identity has separate Model and Label Type fields.  When an
    operator accidentally enters e.g. "GRG-4297u Carton" while Label Type is
    Carton Label, strip only that trailing descriptor.  Product-model text in
    the middle of a model name is not changed.
    """
    value=' '.join(str(model or '').split()).strip()
    ltype=' '.join(str(label_type or '').split()).strip().lower()
    suffixes=[]
    if 'carton' in ltype:
        suffixes=[r'\s+Carton(?:\s+Label)?$']
    elif 'inner box' in ltype:
        suffixes=[r'\s+Inner\s+Box(?:\s+Label)?$']
    elif 'chassis' in ltype:
        suffixes=[r'\s+Chassis(?:\s+Label)?$']
    for pat in suffixes:
        value=re.sub(pat,'',value,flags=re.I).strip()
    return value


def canonical_profile_identity(model: str, label_type: str, label_pn: str='') -> dict:
    label_type=str(label_type or '').strip() or 'Label'
    model=_normalize_internal_model(model,label_type) or 'New Model'
    label_pn=str(label_pn or '').strip()
    display_name=f'{model} {label_type}'.strip()
    file_stem=_safe_name('_'.join(x for x in (model,label_type,label_pn) if x))
    return {
        'model': model,
        'label_type': label_type,
        'label_pn': label_pn,
        'display_name': display_name,
        'file_stem': file_stem,
    }


def dynamic_identity_errors(profile: dict, path: Path|None=None) -> list[str]:
    if not profile.get('dynamic_profile'):
        return []
    expected=canonical_profile_identity(profile.get('model',''), profile.get('label_type',''), profile.get('label_pn',''))
    errors=[]
    identity=profile.get('profile_identity') or {}
    if str(profile.get('profile_name','')).strip() != expected['display_name']:
        errors.append(f"Profile name mismatch: expected '{expected['display_name']}'")
    for key in ('model','label_type','label_pn'):
        if str(identity.get(key,'')).strip() != expected[key]:
            errors.append(f'profile_identity.{key} mismatch')
    if identity.get('display_name') != expected['display_name']:
        errors.append('profile_identity.display_name mismatch')
    source_sha=str((profile.get('golden_import') or {}).get('source_sha256','')).strip()
    if source_sha and identity.get('source_sha256') != source_sha:
        errors.append('profile_identity.source_sha256 mismatch')
    if path is not None and path.stem != expected['file_stem']:
        errors.append(f"Profile filename mismatch: expected '{expected['file_stem']}.json'")
    return errors


def _doc_to_docx(path: Path) -> Path:
    if os.name != 'nt':
        raise RuntimeError('Legacy .doc import requires Windows + Microsoft Word. Convert the file to .docx first on this computer.')
    out = Path(tempfile.gettempdir()) / f'label_golden_{path.stem}_{os.getpid()}.docx'
    # Keep this Python 3.11-compatible: do not place quote-heavy string
    # operations directly inside an f-string expression (PEP 701 syntax is
    # only accepted by Python 3.12+). Escape PowerShell single-quoted string
    # literals before composing the command.
    source_ps = "'" + str(path).replace("'", "''") + "'"
    output_ps = "'" + str(out).replace("'", "''") + "'"
    ps = (
        "$ErrorActionPreference='Stop'; "
        "$w=New-Object -ComObject Word.Application; $w.Visible=$false; "
        f"$d=$w.Documents.Open({source_ps}); "
        f"$d.SaveAs2({output_ps},16); "
        "$d.Close(); $w.Quit();"
    )
    cp = subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',ps], capture_output=True, text=True, timeout=90)
    if cp.returncode != 0 or not out.exists():
        raise RuntimeError('Microsoft Word could not convert .doc to .docx: ' + (cp.stderr or cp.stdout or 'unknown error').strip())
    return out


def _docx_final_label_media_names(path: Path) -> list[str]:
    """Return media basenames referenced at/after the 'Label Example' marker.

    This is a structural signal from the controlled Word document and is more
    reliable than OCR similarity when the document also embeds password rules,
    process screenshots or other support images.
    """
    if path.suffix.lower()!='.docx' or not path.exists():
        return []
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    a='http://schemas.openxmlformats.org/drawingml/2006/main'
    v='urn:schemas-microsoft-com:vml'
    r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    pr='http://schemas.openxmlformats.org/package/2006/relationships'
    try:
        with zipfile.ZipFile(path,'r') as z:
            if 'word/document.xml' not in z.namelist() or 'word/_rels/document.xml.rels' not in z.namelist():
                return []
            rel_root=ET.fromstring(z.read('word/_rels/document.xml.rels'))
            rels={x.attrib.get('Id',''):x.attrib.get('Target','') for x in rel_root.findall(f'{{{pr}}}Relationship')}
            root=ET.fromstring(z.read('word/document.xml'))
            after=False; out=[]
            for para in root.findall(f'.//{{{w}}}p'):
                txt=''.join((x.text or '') for x in para.findall(f'.//{{{w}}}t')).strip()
                if 'label example' in txt.lower():
                    after=True
                if not after:
                    continue
                # Modern DOCX uses DrawingML <a:blip r:embed=...>; legacy
                # .doc -> .docx Word conversion frequently keeps pictures as
                # VML <v:imagedata r:id=...>. Support BOTH. Missing the VML
                # path was the root cause of password/support screenshots being
                # selected as the Final Label after old .doc imports.
                rel_ids=[]
                for blip in para.findall(f'.//{{{a}}}blip'):
                    rid=blip.attrib.get(f'{{{r}}}embed','')
                    if rid: rel_ids.append(rid)
                for image_data in para.findall(f'.//{{{v}}}imagedata'):
                    rid=image_data.attrib.get(f'{{{r}}}id','') or image_data.attrib.get(f'{{{r}}}embed','')
                    if rid: rel_ids.append(rid)
                for rid in rel_ids:
                    target=rels.get(rid,'')
                    if target:
                        name=Path(target).name
                        if name and name not in out: out.append(name)
            return out
    except Exception:
        return []


def _extract_docx(path: Path, dest: Path) -> tuple[str, list[Path]]:
    text_parts=[]; images=[]
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(path,'r') as z:
        if 'word/document.xml' in z.namelist():
            root=ET.fromstring(z.read('word/document.xml'))
            # Legacy .doc -> .docx conversion often stores the visible Request-
            # Form numbers as Word list metadata (w:numPr), not literal text.
            # Reconstruct those numbers so the form-driven parser sees 1..N.
            counters={}
            for para in root.findall('.//w:p',ns):
                parts=[(x.text or '') for x in para.findall('.//w:t',ns)]
                line=''.join(parts).strip()
                numpr=para.find('./w:pPr/w:numPr',ns)
                if numpr is not None:
                    num_el=numpr.find('w:numId',ns); lvl_el=numpr.find('w:ilvl',ns)
                    num_id=(num_el.attrib.get('{%s}val'%ns['w']) if num_el is not None else '')
                    ilvl=(lvl_el.attrib.get('{%s}val'%ns['w']) if lvl_el is not None else '0')
                    if num_id:
                        key=(num_id,ilvl)
                        counters[key]=counters.get(key,0)+1
                        # Do not duplicate explicit numbering already present in
                        # DOCX text. Keep blank numbered rows (e.g. item #17).
                        if not re.match(r'^\s*\d{1,3}[.)]\s*',line):
                            line=f'{counters[key]}. {line}'.rstrip()
                if line: text_parts.append(line)
        media=[n for n in z.namelist() if n.startswith('word/media/') and not n.endswith('/')]
        media_dir=dest/'imported_media'; media_dir.mkdir(parents=True,exist_ok=True)
        for idx,n in enumerate(media,1):
            suffix=Path(n).suffix.lower() or '.bin'
            out=media_dir/f'{idx:02d}_{Path(n).name}'
            out.write_bytes(z.read(n)); images.append(out)
    return '\n'.join(text_parts), images


def _extract_text_and_media(source: Path, dest: Path) -> tuple[str,list[Path],Path]:
    suffix=source.suffix.lower()
    actual=source
    if suffix=='.doc':
        actual=_doc_to_docx(source); suffix='.docx'
    if suffix=='.docx':
        text,images=_extract_docx(actual,dest)
        return text,images,actual
    if suffix in ('.png','.jpg','.jpeg','.bmp','.webp'):
        img_dir=dest/'imported_media'; img_dir.mkdir(parents=True,exist_ok=True)
        out=img_dir/source.name; shutil.copy2(source,out)
        return '',[out],actual
    raise ValueError('Supported Golden files: DOC, DOCX, PNG, JPG, JPEG, BMP, WEBP')


def _candidate_model(text: str, fallback: str='') -> str:
    for pat in (r'\b(?:GRG|NL|VG|ES|STB|DPU|JRDU|RMDU|RDMU)-?[A-Za-z0-9]+(?:u|xs|PoE)?\b', r'\b[A-Z]{2,6}-\d{3,6}[A-Za-z0-9-]*\b'):
        m=re.search(pat,text,re.I)
        if m: return m.group(0)
    return fallback


def _candidate_label_pn(text: str, fallback: str='') -> str:
    t=str(text or '').replace('：',':')
    # V1.9.23: a controlled form may list the blank-stock P/N before the
    # finished printed-label P/N.  The blank material number is NOT Label P/N.
    # Prefer the explicit shipped/finished label family first and deliberately
    # exclude lines beginning with "Blank Label Part Number".
    for pat in (
        r'Carton\s+Label\s+Part\s+Number\s*:\s*(\d{6}-\d{3})',
        r'Chassis\s+Label\s+Part\s+Number\s*:\s*(\d{6}-\d{3})',
        r'Inner\s+Box\s+Label\s+Part\s+Number\s*:\s*(\d{6}-\d{3})',
        r'Finished\s+Label\s+Part\s+Number\s*:\s*(\d{6}-\d{3})',
        r'(?im)^\s*(?!Blank\b)(?:Final\s+)?Label\s+Part\s+Number\s*:\s*(\d{6}-\d{3})',
    ):
        m=re.search(pat,t,re.I|re.M)
        if m: return m.group(1)
    # Last-resort numeric scan also skips the exact P/N found on a Blank Label
    # Part Number line when another 6-3 candidate exists later in the form.
    blank={m.group(1) for m in re.finditer(r'Blank\s+Label\s+Part\s+Number\s*:\s*(\d{6}-\d{3})',t,re.I)}
    for m in re.finditer(r'\b\d{6}-\d{3}\b',t):
        if m.group(0) not in blank:
            return m.group(0)
    return fallback


def _fixed_text_candidates(text: str) -> list[dict]:
    lines=[]
    for raw in text.splitlines():
        s=' '.join(raw.split()).strip()
        if 5 <= len(s) <= 160 and s not in lines: lines.append(s)
    preferred=[]
    keys=('gpon voip gateway','class 1 laser','input ','input:','usb ','usb:','http://','https://','comtrend','made in')
    for s in lines:
        low=s.lower()
        if any(k in low for k in keys):
            preferred.append(s)
    out=[]
    for i,s in enumerate(preferred[:20],1):
        short=s[:42].rstrip()
        low=s.lower()
        role='BASIC' if any(k in low for k in ('comtrend','gpon voip gateway','input','usb')) else ('COMPLIANCE' if any(k in low for k in ('class 1 laser','made in','http://','https://')) else 'DETAIL')
        out.append({'id':f'fixed_{i:02d}','name':short,'item':f'Golden Text: {short}','text':s,'threshold':0.74,'required':True,'role':role,'manual_review_allowed':True})
    return out



def _ocr_golden_images(images: list[Path]) -> tuple[str, list[dict]]:
    """Best-effort OCR of embedded Golden artwork/layout images.

    This is intentionally non-fatal: DOC text still imports if OCR runtime is
    unavailable. In a GitHub-built EXE RapidOCR is bundled, so label-example
    screenshots can contribute fields that Word stores only as pixels.
    """
    if not images:
        return '', []
    try:
        import cv2
        import numpy as np
        from .ocr_engine import OCREngine
        engine=OCREngine()
    except Exception:
        return '', []
    rows=[]; texts=[]
    candidates=sorted((p for p in images if p.exists()), key=lambda p:p.stat().st_size, reverse=True)[:4]
    for img_path in candidates:
        try:
            arr=np.fromfile(str(img_path),dtype=np.uint8)
            image=cv2.imdecode(arr,cv2.IMREAD_COLOR)
            if image is None: continue
            text,structured=engine.read(image)
            if text.strip():
                texts.append(text.strip())
                line_rows=[]
                for box,txt,score in structured:
                    try:
                        pts=[[float(pt[0]),float(pt[1])] for pt in box]
                    except Exception:
                        pts=[]
                    line_rows.append({'text':str(txt),'score':float(score),'box':pts})
                rows.append({'file':str(img_path),'line_count':len(structured),'text':text.strip(),'lines':line_rows})
        except Exception as exc:
            rows.append({'file':str(img_path),'line_count':0,'error':repr(exc),'text':''})
    return '\n'.join(texts), rows

def _detect_golden_machine_codes(images: list[Path]) -> list[dict]:
    """Decode QR/barcodes embedded in the Golden example image.

    This is best-effort and non-fatal, but when codes are found their type and
    polygon are persisted so Profile completeness and Manual Review can use
    them even if the request-form prose does not explain the payload.
    """
    if not images:
        return []
    try:
        import cv2
        import numpy as np
        from .decoder import decode_codes
    except Exception:
        return []
    out=[]; seen=set()
    for img_path in sorted((p for p in images if p.exists()), key=lambda p:p.stat().st_size, reverse=True)[:4]:
        try:
            arr=np.fromfile(str(img_path),dtype=np.uint8)
            image=cv2.imdecode(arr,cv2.IMREAD_COLOR)
            if image is None:
                continue
            for d in decode_codes(image):
                fmt=str(getattr(d,'format','') or '')
                txt=str(getattr(d,'text','') or '')
                kind='QR' if 'QR' in fmt.upper() else 'BARCODE'
                key=(kind,fmt,txt)
                if key in seen:
                    continue
                seen.add(key)
                pts=[]
                try:
                    pts=[[int(x),int(y)] for x,y in (getattr(d,'points',None) or [])]
                except Exception:
                    pts=[]
                out.append({'file':str(img_path),'kind':kind,'format':fmt,'text':txt,'points':pts})
        except Exception:
            continue
    return out


def _largest_image(images: list[Path]) -> Path|None:
    if not images: return None
    # Manual Review uses PIL/Tk. Prefer common raster formats over EMF/WMF
    # artwork objects embedded in Word, even when the vector file is larger.
    raster=[p for p in images if p.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.webp') and p.exists()]
    candidates=raster or [p for p in images if p.exists()]
    if not candidates: return None
    return max(candidates,key=lambda p:p.stat().st_size)


def _layout_candidate_score(text: str, code_count: int=0) -> tuple[float,list[str]]:
    """Score whether OCR text looks like a final printed label, not a support screenshot.

    Controlled Golden documents often embed password proposals, process notes and
    other screenshots in addition to the final Label Example.  Manual Review must
    use the final label as its visual reference.  The score therefore rewards
    compact label anchors and machine codes, while penalising prose-heavy images.
    """
    t=' '.join(str(text or '').split())
    low=t.lower()
    anchors={
        'model':2.0, 'p/n':2.0, 'part no':1.5, 'input':1.2, 'usb':1.0,
        's/n':2.2, 'serial':1.4, 'mac':2.4, 'gpon':1.6, 'ssid':1.7,
        'wifi key':1.7, 'password':0.8, 'made in':1.6, 'username':0.7,
        'fcc id':1.4, 'ic id':1.4, 'class 1 laser':1.2, 'comtrend':1.0,
    }
    hit=[]; score=0.0
    for key,weight in anchors.items():
        if key in low:
            score += weight; hit.append(key)
    score += min(9.0, max(0,int(code_count))*3.0)
    # Support documents tend to be paragraphs/bullets rather than a compact label.
    support_terms=('entropy','password proposal','software upgrade','reset button','production process',
                   'characters are from','requirement','procedure','office','randomly generated')
    penalties=[x for x in support_terms if x in low]
    score -= 2.2*len(penalties)
    words=t.split()
    if len(words)>120: score -= 3.0
    elif len(words)>80: score -= 1.5
    return score,hit


def select_final_label_image(images: list[Path], image_ocr_rows: list[dict], machine_codes: list[dict], preferred_names: list[str]|None=None) -> tuple[Path|None,float,str]:
    """Choose the embedded image that most likely is the final Label Example.

    This replaces the old `largest image wins` rule which could select a password
    proposal/support screenshot.  Matching is by basename so it works before and
    after the transactional Golden asset paths are committed.
    """
    raster=[p for p in images if p.exists() and p.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.webp')]
    candidates=raster or [p for p in images if p.exists()]
    if not candidates: return None,0.0,'no embedded image'
    ocr_by_name={Path(str(r.get('file',''))).name:r for r in (image_ocr_rows or [])}
    code_count={}
    for c in machine_codes or []:
        name=Path(str(c.get('file',''))).name
        code_count[name]=code_count.get(name,0)+1
    preferred={str(x) for x in (preferred_names or []) if str(x)}
    ranked=[]
    for img in candidates:
        row=ocr_by_name.get(img.name,{})
        score,hits=_layout_candidate_score(str(row.get('text','')),code_count.get(img.name,0))
        # Strongest signal: the image is structurally located after the
        # controlled document's 'Label Example' marker.
        original_name=img.name.split('_',1)[1] if re.match(r'^\d+_',img.name) else img.name
        if img.name in preferred or original_name in preferred:
            score += 100.0
            hits=list(hits)+['document:Label Example']
        # Tiny bonus for image size only as a tie breaker, never as the main rule.
        try: score += min(0.5,img.stat().st_size/10_000_000.0)
        except Exception: pass
        ranked.append((score,img,hits,code_count.get(img.name,0)))
    ranked.sort(key=lambda x:(x[0],x[1].stat().st_size if x[1].exists() else 0),reverse=True)
    score,img,hits,codes=ranked[0]
    # If OCR runtime was unavailable, preserve old safe raster fallback.
    if score <= 0.2 and not any(ocr_by_name.get(x.name,{}).get('text') for x in candidates):
        fallback=_largest_image(candidates)
        return fallback,0.0,'OCR unavailable; raster-size fallback'
    return img,float(score),f'label anchors={hits}; machine_codes={codes}'





STANDARD_LIBRARY = [
    {'item':'Fixed: model','label':'Model / Customer model','role':'BASIC'},
    {'item':'Variable: P/N Format','label':'Part Number format','role':'BASIC'},
    {'item':'Variable: Made in Format','label':'Made in country','role':'COMPLIANCE'},
    {'item':'Variable: S/N Human Readable Format','label':'S/N human readable','role':'IDENTITY'},
    {'item':'Variable: S/N Barcode Format','label':'S/N barcode','role':'IDENTITY'},
    {'item':'Consistency: S/N Text vs Barcode','label':'S/N text vs barcode consistency','role':'IDENTITY'},
    {'item':'Variable: MAC Human Readable Format','label':'MAC human readable','role':'IDENTITY'},
    {'item':'Variable: MAC Barcode Format','label':'MAC barcode','role':'IDENTITY'},
    {'item':'Consistency: MAC Text vs Barcode','label':'MAC text vs barcode consistency','role':'IDENTITY'},
    {'item':'Variable: GPON S/N Human Readable Format','label':'GPON S/N human readable','role':'IDENTITY'},
    {'item':'Variable: GPON S/N Barcode Format','label':'GPON S/N barcode','role':'IDENTITY'},
    {'item':'Consistency: GPON S/N Text vs Barcode','label':'GPON S/N text vs barcode consistency','role':'IDENTITY'},
    {'item':'Variable: SSID Format','label':'SSID format','role':'WIFI'},
    {'item':'Variable: WiFi Key Format','label':'WiFi Key format','role':'WIFI'},
    {'item':'Variable: WiFi QR Format','label':'QR content / WiFi QR','role':'WIFI'},
    {'item':'Consistency: QR SSID vs Printed SSID','label':'QR SSID vs printed SSID','role':'WIFI'},
    {'item':'Consistency: QR Key vs Printed WiFi Key','label':'QR Key vs printed WiFi Key','role':'WIFI'},
    {'item':'Rule: SSID = MAC Last 6','label':'SSID = MAC last 6','role':'IDENTITY'},
    {'item':'Rule: GPON S/N = Prefix + MAC Last 8','label':'GPON S/N = prefix + MAC last 8','role':'IDENTITY'},
    {'item':'Variable: Password Format','label':'Password format','role':'WIFI'},
]


def _split_numbered_form_items(text: str) -> list[tuple[int,str]]:
    """Extract the top-level numbered Label Request items in sequence.

    Controlled request forms may contain nested numbered rule lists inside a
    parent item (for example password rules that restart at 1).  Those nested
    numbers are *not* new label inspection items.  The top-level form itself is
    monotonic (1, 2, 3, ...), so only the next expected number starts a new
    inspection item.  Empty items are retained because the visual part of the
    Word form/final-label example may carry the actual requirement.
    """
    raw_lines=[str(x).replace('\u00a0',' ').strip() for x in str(text or '').splitlines()]
    stop_markers=('Finished Information:', 'Manufacture Attention:', 'Label Example:')
    items=[]
    started=False
    expected_no=1
    current_no=None
    buf=[]

    def flush():
        nonlocal current_no,buf
        if current_no is not None:
            items.append((current_no,' '.join(' '.join(x.split()) for x in buf if x.strip()).strip()))
        current_no=None; buf=[]

    for raw in raw_lines:
        line=' '.join(raw.split())
        if any(line.startswith(m) for m in stop_markers):
            flush(); break
        m=re.match(r'^\s*(\d{1,2})[.)]\s*(.*)$',line)
        if not started:
            if m and int(m.group(1))==1:
                started=True; current_no=1; expected_no=2; buf=[m.group(2).strip()]
            continue
        if m:
            no=int(m.group(1)); body=m.group(2).strip()
            if no==expected_no:
                flush(); current_no=no; expected_no+=1; buf=[body]
                continue
            # A number that resets/skips is a nested rule/list entry belonging
            # to the current top-level request item. Preserve it as specification.
            if current_no is not None:
                buf.append(line)
            continue
        if current_no is not None and line:
            buf.append(line)
    else:
        flush()
    return items


def _checkbox_selection(body: str) -> str:
    t=str(body or '').replace('：',':')
    if re.search(r'■\s*Yes',t,re.I): return 'YES'
    if re.search(r'■\s*No',t,re.I): return 'NO'
    if '■' in t:
        after=t.split('■',1)[1].strip()
        return ('SELECTED: '+after[:120]).strip()
    return ''


def _form_label(no: int, text: str) -> str:
    t=' '.join(str(text or '').split())
    if not t:
        return f'Item {no} (visual/unspecified)'
    head=re.split(r'[:：]',t,maxsplit=1)[0].strip()
    # Keep concise identifiers while avoiding whole rule paragraphs in the UI.
    return (head or f'Item {no}')[:72]



def _scope_reference_only_text(body: str) -> bool:
    """Return True for request-form entries that are process/reference notes, not shipped-label content."""
    low=' '.join(str(body or '').replace('：',':').split()).lower()
    refs=(
        '匯入列印方式', '列印方式參考', 'print method', 'printing method',
        '以上所有密碼規則說明', 'password proposal', 'rules explanation',
    )
    return any(x in low for x in refs)


def _extract_notch_direction(text: str) -> tuple[str,str]:
    """Extract label-notch orientation from the controlled Request Form text.

    The form often states this beside the final Label Example, e.g.
    "印出後貼紙缺角處在左上角".  This is a shipped-label geometry requirement,
    even though it is not a numbered item.
    """
    t=' '.join(str(text or '').replace('：',':').split())
    patterns=(
        ('TOP_LEFT', r'(?:缺角|切角)[^。；;\n]{0,30}(?:左上角|左上|top[ -]?left|upper[ -]?left)'),
        ('TOP_RIGHT', r'(?:缺角|切角)[^。；;\n]{0,30}(?:右上角|右上|top[ -]?right|upper[ -]?right)'),
        ('BOTTOM_LEFT', r'(?:缺角|切角)[^。；;\n]{0,30}(?:左下角|左下|bottom[ -]?left|lower[ -]?left)'),
        ('BOTTOM_RIGHT', r'(?:缺角|切角)[^。；;\n]{0,30}(?:右下角|右下|bottom[ -]?right|lower[ -]?right)'),
    )
    for key,pat in patterns:
        m=re.search(pat,t,re.I)
        if m:
            return key,m.group(0)
    return '',''


def _final_label_scope_y(final_label: Path|None, image_ocr_rows: list[dict]) -> tuple[float,float,float]:
    """Infer the dense shipped-label vertical band from Final Label OCR.

    Returns (y0, y1, confidence).  It deliberately uses text clustering rather
    than a model-specific hard-coded crop, so lower production/test blocks in a
    request-form screenshot can be excluded while full-size label examples are
    retained.
    """
    if not final_label:
        return 0.0,1.0,0.0
    name=final_label.name
    row=next((r for r in (image_ocr_rows or []) if Path(str(r.get('file',''))).name==name),None)
    if not row:
        return 0.0,1.0,0.0
    spans=[]
    max_coord=0.0
    for ln in row.get('lines',[]) or []:
        pts=ln.get('box') or []
        if len(pts)<2: continue
        ys=[float(pt[1]) for pt in pts if len(pt)>=2]
        if not ys: continue
        y0,y1=min(ys),max(ys); yc=(y0+y1)/2.0
        spans.append((yc,y0,y1))
        max_coord=max(max_coord,y1)
    if len(spans)<4 or max_coord<=0:
        return 0.0,1.0,0.0
    spans.sort()
    gap=max(32.0,max_coord*0.35)
    groups=[]; cur=[spans[0]]
    for item in spans[1:]:
        if item[0]-cur[-1][0] > gap:
            groups.append(cur); cur=[item]
        else:
            cur.append(item)
    groups.append(cur)
    main=max(groups,key=lambda g:(len(g),sum(x[2]-x[1] for x in g)))
    # If there is no dominant cluster, treat the whole OCR span as one label.
    # This avoids splitting sparse but legitimate full-label layouts (e.g.
    # GRG-4366) into two artificial zones. A real lower production/test block
    # is typically a small separated tail while the main label remains dominant.
    if len(main)/max(1,len(spans)) < 0.60:
        main=spans
    lo=min(x[1] for x in main); hi=max(x[2] for x in main)
    margin=max(10.0,max_coord*0.04)
    lo=max(0.0,lo-margin); hi=hi+margin
    return lo/max_coord,min(1.0,hi/max_coord),min(1.0,len(main)/max(1,len(spans)))


def _code_center_y(code: dict) -> float|None:
    pts=code.get('points') or []
    ys=[float(p[1]) for p in pts if isinstance(p,(list,tuple)) and len(p)>=2]
    return (sum(ys)/len(ys)) if ys else None


def _apply_chassis_scope_filter(form_items: list[dict], final_label: Path|None,
                                image_ocr_rows: list[dict], machine_codes: list[dict]) -> dict:
    """CMP-001: keep Request Form traceability but exclude non-shipped test/process zones.

    Process/reference rows stay visible in Profile Manager with Required=False.
    A "test programming" QR is excluded only when the Final Label screenshot
    contains a QR outside the dense shipped-label band.  This preserves products
    where the same test QR is physically printed inside the outgoing label.
    """
    scope={'policy':'CHASSIS_SHIPPED_LABEL_ONLY','excluded_items':[],'scope_y':[0.0,1.0],'confidence':0.0}
    if final_label:
        y0,y1,conf=_final_label_scope_y(final_label,image_ocr_rows)
        scope['scope_y']=[round(y0,4),round(y1,4)]; scope['confidence']=round(conf,3)
    else:
        y0,y1,conf=0.0,1.0,0.0
    final_name=final_label.name if final_label else ''
    final_codes=[c for c in (machine_codes or []) if Path(str(c.get('file',''))).name==final_name]
    outside_qr=False
    if final_codes and conf>0:
        # Normalize centers using the largest observed Y coordinate in points.
        all_y=[float(p[1]) for c in final_codes for p in (c.get('points') or []) if len(p)>=2]
        max_y=max(all_y) if all_y else 0.0
        if max_y>0:
            for c in final_codes:
                if str(c.get('kind','')).upper()!='QR': continue
                cy=_code_center_y(c)
                if cy is not None and (cy/max_y > y1+0.03 or cy/max_y < max(0.0,y0-0.03)):
                    outside_qr=True; break
    # Track whether an earlier numbered shipped-label item already defines a QR.
    # GRG-4297u is the important case: #10 defines the QR actually printed on
    # the outgoing label, while #19 is a separate test-programming QR reference.
    # Other products (for example VG-8043u) may have only one numbered QR item
    # whose wording includes 'for test programming' but which is visibly printed
    # on the shipped label.  Therefore the later test QR is excluded when either
    # (a) a shipped-label QR was already defined earlier, or (b) the Final Label
    # image proves a QR exists outside the dense shipped-label band.
    prior_shipped_qr=False
    for row in form_items:
        raw=str(row.get('raw_text','') or '')
        reason=''
        is_qr=bool(row.get('machine_code_field')=='qr' or row.get('type')=='Golden QR' or re.search(r'\bqr\s*code\b',raw,re.I))
        is_test_qr=bool(re.search(r'(?:測試刷入使用|test\s*(?:program|programming|flash))',raw,re.I))
        if _scope_reference_only_text(raw):
            reason='Process/reference instruction; not printed on shipped Chassis Label'
        elif is_test_qr and (prior_shipped_qr or outside_qr):
            reason=('Test-programming QR is reference-only because a shipped-label QR is already defined earlier'
                    if prior_shipped_qr else
                    'Test-programming code is outside shipped-label scope in Final Label Example')
        if reason:
            row['inspection_scope']='REFERENCE_ONLY'
            row['scope_reason']=reason
            row['required']=False
            row['review_status']='REFERENCE_ONLY'
            row['engine_items']=[]
            row['presence_item']=''
            scope['excluded_items'].append({'form_no':row.get('form_no'),'item':row.get('item'),'reason':reason})
        else:
            row['inspection_scope']='CHASSIS_LABEL'
            if is_qr:
                prior_shipped_qr=True
    return scope

def _classify_form_item(no: int, body: str) -> dict:
    t=' '.join(str(body or '').split())
    low=t.lower()
    selected=_checkbox_selection(t)
    required=(selected != 'NO')
    typ='Needs Review'; role='DETAIL'; mapping=[]; expected=''
    field_key=''
    rule_known=False

    # A printed WiFi Key item may contain an attached QR rule in its
    # continuation text. Keep the numbered item as WiFi Key and attach the QR
    # as a mandatory secondary machine-code check instead of changing its type.
    if low.startswith('wifi key'):
        typ='Golden Variable'; role='WIFI'; mapping=['Variable: WiFi Key Format']; rule_known=True
    # Machine-code semantics are classified before generic text.  A code item
    # is never bypassed merely because its payload/format is not fully defined.
    elif 'qr code' in low or re.search(r'\bqr\b',low):
        typ='Golden QR'; role='WIFI'; field_key='qr'
        # The existing automatic QR engine can validate SSID/SN/MAC/WiFi-Key
        # style payloads. If the controlled QR also includes an unsupported
        # field such as Password, retain the QR item but route it to manual
        # review rather than pretending the full payload was auto-validated.
        unsupported=('password' in low)
        mapping=[] if unsupported else ['Variable: WiFi QR Format']
        rule_known=bool(re.search(r'(?:內容|含|content|payload)',t,re.I)) and not unsupported
    elif 'gpon sn' in low or 'gpon s/n' in low:
        typ='Golden Barcode'; role='IDENTITY'; field_key='gpon_sn'
        mapping=['Variable: GPON S/N Human Readable Format','Variable: GPON S/N Barcode Format','Consistency: GPON S/N Text vs Barcode']
        rule_known=bool(re.search(r'(?:434D5444|last\s+8|16\s*characters)',t,re.I))
    elif 's/n number' in low or re.match(r'^s\s*/\s*n\s*:',low) or ('serial' in low and 'number' in low):
        typ='Golden Barcode'; role='IDENTITY'; field_key='sn'
        mapping=['Variable: S/N Human Readable Format','Variable: S/N Barcode Format','Consistency: S/N Text vs Barcode']
        rule_known=bool(re.search(r'(?:\d+\s*(?:characters|碼)|YYM|fixed|固定)',t,re.I))
    elif 'mac number' in low or re.match(r'^mac\s*:',low):
        typ='Golden Barcode'; role='IDENTITY'; field_key='mac'
        mapping=['Variable: MAC Human Readable Format','Variable: MAC Barcode Format','Consistency: MAC Text vs Barcode']
        # MAC syntax itself is a known validated engine field even when the form
        # only says Code128 / N MACs per unit.
        rule_known=True
    elif 'barcode' in low or 'bar code' in low or 'code 128' in low or 'code type' in low:
        typ='Golden Barcode'; role='DETAIL'; field_key='barcode'; rule_known=False
    elif any(k in low for k in ('comtrend logo','fcc mark','weee mark','ce mark','ic mark','ul file listing','安規 logo','安規logo')) or (low.endswith('logo') and low):
        typ='Golden Artwork'; role='COMPLIANCE' if 'comtrend logo' not in low else 'BASIC'
        if 'comtrend' in low: mapping=['Artwork: COMTREND Logo']
        elif 'weee' in low: mapping=['Artwork: WEEE Mark']
        elif 'ce mark' in low: mapping=['Artwork: CE Mark']
    elif low.startswith('ssid') or ' ssid' in low:
        typ='Golden Variable'; role='WIFI'; mapping=['Variable: SSID Format']; rule_known=True
    elif re.match(r'^password\b',low):
        typ='Golden Variable'; role='WIFI'; mapping=['Variable: Password Format']; rule_known=True
    elif 'part no' in low or 'part number' in low or low.startswith('p/n'):
        typ='Golden Variable'; role='BASIC'; mapping=['Variable: P/N Format']; rule_known=True
    elif 'model name' in low or low.startswith('model'):
        typ='Golden Choice'; role='BASIC'; mapping=['Fixed: model']; rule_known=True
    elif 'made in' in low:
        typ='Golden Choice'; role='COMPLIANCE'; mapping=['Variable: Made in Format']; rule_known=True
    elif low.startswith('input') or low.startswith('usb ') or 'encryption type' in low or low.startswith('product'):
        typ='Golden Text'; role='BASIC'; rule_known=True
        expected=(re.split(r'[:：]',t,maxsplit=1)[1].strip() if re.search(r'[:：]',t) else t)
    elif any(k in low for k in ('ip address','username','gpon voip gateway','class 1 laser product','comtrend central europe','fcc id','ic id')):
        typ='Golden Text'; role='COMPLIANCE' if any(k in low for k in ('class 1 laser','comtrend central europe','fcc id','ic id')) else 'BASIC'
        rule_known=True
        # For literal label text, preserve the controlled phrase itself.
        expected=t
    elif t:
        # The user requirement is non-bypass: every numbered form item remains
        # visible even if the engine cannot infer a safe automatic rule.
        typ='Needs Review'; role='DETAIL'; rule_known=False

    # A numbered item may define a printed field AND a machine code in its
    # continuation text (for example WiFi Key + QR payload). Preserve both.
    if typ=='Golden Variable' and ('qr code' in low or re.search(r'\bqr\b',low)):
        if 'Variable: WiFi QR Format' not in mapping:
            mapping.append('Variable: WiFi QR Format')
        field_key='qr'
        rule_known=bool(re.search(r'(?:內容|含|content|payload)',t,re.I))
    label=_form_label(no,t)
    presence_item=''
    if field_key=='qr':
        presence_item=f'Golden Machine Code: QR #{no}'
    elif typ=='Golden Barcode':
        suffix={'sn':'S/N','mac':'MAC','gpon_sn':'GPON S/N'}.get(field_key,'Barcode')
        presence_item=f'Golden Machine Code: {suffix} #{no}'
    return {
        'form_no':no,'item':f'Golden #{no}: {label}','type':typ,'role':role,
        'required':required,'selected':selected,'expected':expected,'raw_text':t,
        'origin':'GOLDEN','source':'Golden','engine_items':mapping,
        'presence_item':presence_item,'machine_code_field':field_key,
        'machine_code_rule_known':bool(rule_known),
        'manual_review_allowed':True,
        'inspection_scope':'CHASSIS_LABEL',
        'review_status':'NEEDS_REVIEW' if (typ=='Needs Review' or (typ in ('Golden QR','Golden Barcode') and not rule_known)) else 'AUTO_CLASSIFIED',
    }


def extract_golden_form_items(text: str) -> list[dict]:
    return [_classify_form_item(no,body) for no,body in _split_numbered_form_items(text)]

SUPPORTED_STANDARD_ITEMS = {
    'Fixed: model', 'Variable: P/N Format', 'Variable: Made in Format',
    'Variable: S/N Human Readable Format', 'Variable: S/N Barcode Format', 'Consistency: S/N Text vs Barcode',
    'Variable: MAC Human Readable Format', 'Variable: MAC Barcode Format', 'Consistency: MAC Text vs Barcode',
    'Variable: GPON S/N Human Readable Format', 'Variable: GPON S/N Barcode Format', 'Consistency: GPON S/N Text vs Barcode',
    'Variable: SSID Format', 'Variable: WiFi Key Format', 'Variable: WiFi QR Format',
    'Consistency: QR SSID vs Printed SSID', 'Consistency: QR Key vs Printed WiFi Key',
    'Rule: SSID = MAC Last 6', 'Rule: GPON S/N = Prefix + MAC Last 8',
    'Variable: Password Format',
}

MODEL_SPECIFIC_TOP_LEVEL = {
    'fixed_fields', 'rules', 'rois', 'notes', 'artwork_verification',
}
MODEL_SPECIFIC_LIVE_KEYS = {
    'required_items', 'custom_targets', 'production_zones', 'zones', 'fast_machine_items',
}


def _clean_engine_template(base_profile: dict) -> dict:
    """Keep only reusable engine/runtime settings from a bundled profile.

    A Dynamic Golden profile must never inherit another model's inspection
    requirements, expected text, artwork templates/ROIs or relationship rules.
    This is the V1.9.4 anti-contamination boundary.
    """
    src=deepcopy(base_profile or {})
    out={}
    # Runtime / camera / generic quality settings are reusable.
    for key in ('image_quality','vision'):
        if key in src:
            out[key]=deepcopy(src[key])
    live=deepcopy(src.get('live',{}) or {})
    for key in MODEL_SPECIFIC_LIVE_KEYS:
        live.pop(key,None)
    live['required_items']=[]
    live['custom_targets']=[]
    out['live']=live
    img=deepcopy(src.get('image_inspection',{}) or {})
    # role_items is inspection-content mapping, not reusable.
    img.pop('role_items',None)
    img['role_items']={}
    out['image_inspection']=img
    # Start with no model-specific artwork. The Golden review can add/replace
    # artwork later; never reuse another model's templates or coordinates.
    out['artwork_verification']={
        'status':'DYNAMIC_DRAFT', 'enabled':False, 'blocking':True,
        'mode':'shape_and_relative_position', 'symbols':[],
    }
    out['fixed_fields']={}
    out['rules']={}
    out['notes']=[]
    return out



def _rules_from_golden_text(text: str) -> dict:
    """Build safe runtime format rules from the imported Golden text/OCR."""
    t=str(text or '').replace('：',':')
    rules={
        'sn_regex':r'[A-Z0-9-]{8,32}', 'sn_display':'8-32 A-Z / 0-9 / -',
        'mac_regex':r'[0-9A-F]{12}',
        'gpon_regex':r'[A-Z0-9]{12,20}',
        'made_in_allowed':['China','Taiwan'],
    }
    m=re.search(r'\bP\s*/\s*N\s*:\s*([0-9A-Z-]{5,32})',t,re.I)
    if m and 'X' not in m.group(1).upper():
        pn=m.group(1).upper()
        # A Golden example ending in digits usually represents a revision digit.
        mm=re.fullmatch(r'(.+?)(\d{1,3})',pn)
        if mm:
            rules['pn_regex']=re.escape(mm.group(1))+r'\d{'+str(len(mm.group(2)))+r'}'
        else:
            rules['pn_regex']=re.escape(pn)
        rules['pn_display']=pn
    else:
        rules['pn_regex']=r'[0-9A-Z-]{5,32}'; rules['pn_display']='Golden P/N format'
    ssid=re.search(r'(?:WiFi\s*(?:2\.4|5)\s*GHz\s*:|SSID\s*:)\s*([A-Z0-9_-]+?)(X{3,}|\*{3,})',t,re.I)
    if ssid:
        rules['ssid_prefix']=ssid.group(1)
    key=re.search(r'(?:WiFi\s*Key|\bKey)\s*:\s*(X{4,}|[A-Z0-9]{6,32})',t,re.I)
    if key:
        rules['wifi_key_length']=len(key.group(1))
    # Controlled Request Forms often specify the key as 'Random 10 digits'
    # rather than showing a Golden sample. This explicit rule must win.
    km=re.search(r'WiFi\s*Key\s*:\s*Random\s*(\d{1,2})\s*(?:digits|characters|char|碼)?',t,re.I)
    if km:
        rules['wifi_key_length']=int(km.group(1))
    # Password length is controlled independently from WiFi Key.  Request
    # Forms such as GRG-4297u define "Password: Random 8 characters".
    # Missing this rule previously left password_length at 0 and made every
    # printed password fail even when OCR read the correct 8-character value.
    pm=re.search(r'\bPassword\s*:\s*Random\s*(\d{1,2})\s*(?:digits|characters?|char|碼)?',t,re.I)
    if pm:
        rules['password_length']=int(pm.group(1))
    # Generic SSID forms may put the example on the next line: SSID / ComtrendXXXX.
    if not rules.get('ssid_prefix'):
        sm=re.search(r'\bSSID\b\s+([A-Za-z][A-Za-z0-9_-]*?)(X{3,})',str(text or ''),re.I)
        if sm:
            rules['ssid_prefix']=sm.group(1)
    suffix=re.search(r'last\s+(\d{1,2})\s+(?:digits|characters|chars?)\s+of\s+(?:the\s+)?MAC',t,re.I)
    if suffix:
        rules['ssid_mac_suffix_length']=int(suffix.group(1))
    # Test-programming QR content is defined by the Golden request form.
    qm=re.search(r'QR\s*Code[^\n\r]{0,160}',str(text or ''),re.I)
    if qm:
        qlow=qm.group(0).lower(); qfields=[]
        if 's/n' in qlow or 'sn' in qlow: qfields.append('sn')
        if 'mac' in qlow: qfields.append('mac')
        if 'wifi key' in qlow or 'wifikey' in qlow: qfields.append('wifi_key')
        if 'ssid' in qlow: qfields.append('ssid')
        if qfields: rules['qr_payload_fields']=qfields
    # S/N length is explicitly controlled in these forms. Support both
    # 'S/N Number ... Comtrend (20 碼)' and legacy 'S/N: pattern (18 characters)'.
    snm=re.search(r'S\s*/\s*N\s*Number.*?Comtrend\s*\((\d{1,2})\s*碼\)',t,re.I)
    if not snm:
        snm=re.search(r'(?<!GPON\s)S\s*/\s*N\s*:[^\n]{0,120}?\((\d{1,2})\s*characters?\)',t,re.I)
    if snm:
        n=int(snm.group(1)); rules['sn_regex']=rf'[A-Z0-9-]{{{n}}}'; rules['sn_display']=f'{n} A-Z / 0-9 / -'
    # GPON formats are often structurally related to MAC and may overlap broad
    # S/N regexes. Persist prefix/length so decoder classification is field-safe.
    gpm=re.search(r'GPON\s*S\s*/?\s*N\s*:\s*([0-9A-F]{4,16})X+\s*\((\d{1,2})\s*characters?\)',t,re.I)
    if gpm:
        prefix=gpm.group(1).upper(); n=int(gpm.group(2))
        rules['gpon_prefix']=prefix
        rules['gpon_regex']=re.escape(prefix)+rf'[0-9A-F]{{{max(0,n-len(prefix))}}}'
    countries=[]
    if re.search(r'Made\s+in\s+Taiwan\s*/\s*China|Made\s+in\s+China\s*/\s*Taiwan',t,re.I):
        countries=['China','Taiwan']
    else:
        for c in ('China','Taiwan'):
            if re.search(r'Made\s+in\s+'+c,t,re.I): countries.append(c)
    if countries: rules['made_in_allowed']=countries
    notch,notch_text=_extract_notch_direction(text)
    if notch:
        rules['notch_direction']=notch
        rules['notch_direction_source']=notch_text
    return rules

def _standard_item_candidates(text: str) -> list[dict]:
    """Conservative standard-field discovery from Golden text/OCR.

    These names map to existing validated engine checks. Exact fixed strings
    stay as Dynamic Golden Text rows instead of model-specific Python names.
    """
    t=' '.join(str(text or '').replace('：',':').split())
    low=t.lower()
    rows=[]
    def add(item, role):
        if item not in {x['item'] for x in rows}:
            rows.append({'item':item,'type':'Standard','role':role,'required':True,'origin':'AUTO_GOLDEN'})
    if re.search(r'\bModel\s*:',t,re.I) or _candidate_model(t,''):
        add('Fixed: model','BASIC')
    if re.search(r'\bP\s*/\s*N\s*:',t,re.I) or 'part number' in low:
        add('Variable: P/N Format','BASIC')
    if re.search(r'\bGPON\s*S\s*/\s*N\b',t,re.I):
        add('Variable: GPON S/N Human Readable Format','IDENTITY')
        if 'barcode' in low or 'code128' in low: add('Variable: GPON S/N Barcode Format','IDENTITY')
        if 'barcode' in low or 'code128' in low: add('Consistency: GPON S/N Text vs Barcode','IDENTITY')
    # Avoid counting GPON S/N as ordinary S/N by removing that phrase first.
    sn_text=re.sub(r'GPON\s*S\s*/\s*N','',t,flags=re.I)
    if re.search(r'\bS\s*/\s*N\s*:',sn_text,re.I):
        add('Variable: S/N Human Readable Format','IDENTITY')
        if 'barcode' in low or 'code128' in low: add('Variable: S/N Barcode Format','IDENTITY')
        if 'barcode' in low or 'code128' in low: add('Consistency: S/N Text vs Barcode','IDENTITY')
    if re.search(r'\bMAC\s*:',t,re.I):
        add('Variable: MAC Human Readable Format','IDENTITY')
        if 'barcode' in low or 'code128' in low: add('Variable: MAC Barcode Format','IDENTITY')
        if 'barcode' in low or 'code128' in low: add('Consistency: MAC Text vs Barcode','IDENTITY')
    if 'ssid' in low or 'wifi 2.4' in low or 'wifi 5g' in low:
        add('Variable: SSID Format','WIFI')
    if 'wifi key' in low or re.search(r'\bkey\s*:',t,re.I):
        add('Variable: WiFi Key Format','WIFI')
    if 'made in' in low:
        add('Variable: Made in Format','COMPLIANCE')
    return rows


def _dynamic_item_rows(profile: dict) -> list[dict]:
    """Return Visual Profile rows. Golden form items are primary.

    V1.9.8 deliberately does not flood the table with automatically inferred
    Standard checks. Standard checks appear only after the engineer adds them
    from the Standard Library.
    """
    rows=[]
    for raw in profile.get('golden_form_items',[]) or []:
        if not isinstance(raw,dict): continue
        r=deepcopy(raw)
        r.setdefault('source','Golden'); r.setdefault('origin','GOLDEN')
        r.setdefault('threshold',''); r.setdefault('expected',r.get('expected',''))
        rows.append(r)
    # Explicit Standard Library / manual additions only.
    for raw in profile.get('dynamic_standard_items',[]) or []:
        if not isinstance(raw,dict): continue
        origin=str(raw.get('origin',''))
        if origin in ('AUTO_GOLDEN','AUTO_INFERRED'):
            continue
        r=deepcopy(raw)
        r.setdefault('source','Standard Library' if origin=='STANDARD_LIBRARY' else 'Manual')
        r.setdefault('threshold',''); r.setdefault('expected','')
        rows.append(r)
    # Backward-compatible Dynamic Golden Text rows for image-only Goldens.
    if not profile.get('golden_form_items'):
        for raw in profile.get('dynamic_fixed_texts',[]) or []:
            if not isinstance(raw,dict): continue
            rows.append({
                'item':raw.get('item',''),'type':'Golden Text','role':raw.get('role','DETAIL'),
                'required':bool(raw.get('required',True)),'threshold':raw.get('threshold',0.74),
                'expected':raw.get('text',''),'origin':'GOLDEN','source':'Golden',
                'manual_review_allowed':bool(raw.get('manual_review_allowed',True)),
                'engine_items':[], 'review_status':'AUTO_CLASSIFIED',
            })
    return rows


def apply_editable_items(profile: dict, rows: list[dict]) -> dict:
    """Apply Visual Profile Editor rows while keeping Legacy CAM/Image engine stable.

    Golden rows describe the controlled document. Known Golden semantics map to
    existing Legacy engine item names behind the scenes; Standard Library rows
    are explicit engineer additions. Unknown Golden rows remain visible and
    block validation instead of silently disappearing.
    """
    profile=deepcopy(profile)
    live=profile.setdefault('live',{})
    req=[]; dynamic=[]; standard=[]; golden=[]; role_items={}
    def add_req(item,role):
        if item and item not in req: req.append(item)
        if item:
            role_items.setdefault(role,[])
            if item not in role_items[role]: role_items[role].append(item)
    for idx,row0 in enumerate(rows,1):
        row=deepcopy(row0 or {})
        item=str(row.get('item','')).strip()
        if not item: continue
        typ=str(row.get('type','Needs Review')).strip() or 'Needs Review'
        role=str(row.get('role','DETAIL')).strip().upper() or 'DETAIL'
        required=bool(row.get('required',False))
        origin=str(row.get('origin','MANUAL_EDIT') or 'MANUAL_EDIT')
        is_golden=(origin=='GOLDEN' or str(row.get('source','')).lower()=='golden' or item.startswith('Golden #'))
        if is_golden:
            row.update({'item':item,'type':typ,'role':role,'required':required,'origin':'GOLDEN','source':'Golden'})
            row.setdefault('engine_items',[])
            golden.append(row)
            if required:
                for mapped in row.get('engine_items',[]) or []:
                    add_req(str(mapped),role)
                presence=str(row.get('presence_item','') or '')
                if presence:
                    add_req(presence,role)
            if typ=='Golden Text':
                expected=str(row.get('expected','')).strip() or str(row.get('raw_text','')).strip()
                if expected and required:
                    dyn_item=item
                    add_req(dyn_item,role)
                    try: threshold=float(row.get('threshold',0.74) or 0.74)
                    except Exception: threshold=0.74
                    dynamic.append({
                        'id':f'golden_{idx:02d}','name':item.replace('Golden ','',1)[:64],
                        'item':dyn_item,'text':expected,'threshold':min(1.0,max(0.1,threshold)),
                        'required':True,'role':role,'manual_review_allowed':True,'origin':'GOLDEN',
                    })
            continue
        # Explicit Standard Library / custom engine item.
        if typ=='Golden Text':
            expected=str(row.get('expected','')).strip()
            if not expected: continue
            try: threshold=float(row.get('threshold',0.74) or 0.74)
            except Exception: threshold=0.74
            if required: add_req(item,role)
            dynamic.append({
                'id':f'fixed_{idx:02d}','name':item.replace('Golden Text: ','',1)[:64],
                'item':item,'text':expected,'threshold':min(1.0,max(0.1,threshold)),
                'required':required,'role':role,'manual_review_allowed':True,'origin':origin,
            })
        else:
            if required: add_req(item,role)
            standard.append({'item':item,'type':'Standard','role':role,'required':required,'origin':origin,
                             'source':'Standard Library' if origin=='STANDARD_LIBRARY' else 'Manual'})
    live['required_items']=req
    live['custom_targets']=[{
        'item':r['item'],'title':r['name'],'instruction':f"Place '{r['name']}' inside the target area.",
        'target_rect':[0.08,0.20,0.92,0.80],'mode':'fuzzy','expected':r['text'],'threshold':r['threshold']
    } for r in dynamic]
    profile['golden_form_items']=golden
    if isinstance(profile.get('golden_completeness'),dict):
        doc_nums=[x for x in profile['golden_completeness'].get('document_item_numbers',[]) if x is not None]
        got_nums={x.get('form_no') for x in golden if isinstance(x,dict)}
        profile['golden_completeness']['profile_item_count']=len(golden)
        profile['golden_completeness']['missing_item_numbers']=[x for x in doc_nums if x not in got_nums]
    profile['dynamic_fixed_texts']=dynamic
    profile['dynamic_standard_items']=standard
    profile.setdefault('image_inspection',{})['role_items']=role_items
    profile['profile_status']='DRAFT'
    profile.setdefault('profile_edit_log',[]).append({
        'edited_at':datetime.now().isoformat(timespec='seconds'),
        'action':'VISUAL_ITEMS_SAVE','item_count':len(rows),
    })
    return profile

def build_dynamic_profile(source_path: str, base_profile: dict, profile_name: str|None=None) -> tuple[Path,dict]:
    source=Path(source_path).resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    # Extract Golden first. Identity MUST come from the imported Golden, not
    # from the seed/baseline profile. This prevents a GRG-4355u Golden from
    # inheriting a GRG-4297u display name or filename.
    staging=external_profile_dir()/'golden_assets'/'_import_staging'
    staging.mkdir(parents=True,exist_ok=True)
    text,images,actual_source=_extract_text_and_media(source,staging)
    final_label_media_names=_docx_final_label_media_names(actual_source) if actual_source.suffix.lower()=='.docx' else []

    profile=_clean_engine_template(base_profile)
    model=_candidate_model(text, '') or _candidate_model(source.name, '')
    if not model:
        raise ValueError('Cannot determine Model from the imported Golden. Use a DOC/DOCX containing the model name, or include the model in the Golden filename.')
    label_pn=_candidate_label_pn(text, '') or _candidate_label_pn(source.name, '')
    label_type=_candidate_label_type(source.name,text,'Label')
    identity=canonical_profile_identity(model,label_type,label_pn)
    # profile_name is intentionally ignored for runtime import. It remains in
    # the signature for backwards-compatible tests/API calls, but imported
    # Golden identity is canonical and cannot inherit a seed model name.
    base_name=identity['display_name']
    root=external_profile_dir()/'golden_assets'/identity['file_stem']
    # V1.9.8 stale-Golden guard: build the newly imported asset set in a fresh
    # transaction directory.  Re-importing the same Model/Label P/N must never
    # leave images/templates from the previous Golden in the canonical folder.
    # The canonical folder is replaced only after the new Profile has passed
    # identity/structure checks, so a failed import cannot destroy the last
    # usable Golden assets.
    tx_root=root.parent/f".{identity['file_stem']}__incoming_{os.getpid()}_{datetime.now().strftime('%H%M%S%f')}"
    if tx_root.exists():
        shutil.rmtree(tx_root,ignore_errors=True)
    tx_root.mkdir(parents=True,exist_ok=True)

    tx_images=[]
    canonical_images=[]
    for img in images:
        tx_dst=tx_root/'imported_media'/img.name
        tx_dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(img,tx_dst)
        tx_images.append(tx_dst)
        canonical_images.append(root/'imported_media'/img.name)

    # The request-form body often stores the actual approved label as an
    # embedded image. OCR those images once during import so inspection items
    # are derived from the Golden, not from the seed profile.
    image_ocr_text,image_ocr_rows=_ocr_golden_images(tx_images)
    machine_codes=_detect_golden_machine_codes(tx_images)
    # Metadata must point at the canonical committed Golden asset directory,
    # not the temporary incoming transaction directory used during import.
    for row in image_ocr_rows:
        try:
            row['file']=str(root/'imported_media'/Path(str(row.get('file',''))).name)
        except Exception:
            pass
    for row in machine_codes:
        try:
            row['file']=str(root/'imported_media'/Path(str(row.get('file',''))).name)
        except Exception:
            pass
    source_text=text
    if image_ocr_text:
        text=(text + '\n' + image_ocr_text).strip()

    source_sha=_sha256(source)
    profile.update({
        'profile_name':base_name,
        'profile_version':'1.9.23',
        'profile_status':'DRAFT',
        'dynamic_profile':True,
        'model':identity['model'],
        'label_type':identity['label_type'],
        'label_pn':identity['label_pn'],
        'source_spec':source.name,
        'profile_identity':{
            **identity,
            'source_sha256':source_sha,
        },
        'golden_import':{
            'source_file':str(source),
            'source_sha256':source_sha,
            'imported_at':datetime.now().isoformat(timespec='seconds'),
            'converted_source':str(actual_source) if actual_source != source else '',
            'asset_dir':str(root),
            'extracted_text_file':str(root/'golden_text.txt'),
            'document_text_length':len(source_text),
            'image_ocr_text_length':len(image_ocr_text),
            'image_ocr_results':image_ocr_rows,
            'machine_codes':machine_codes,
            'final_label_document_candidates':final_label_media_names,
        },
    })
    if identity['model']:
        profile.setdefault('fixed_fields',{})['model']=identity['model']
    (tx_root/'golden_text.txt').write_text(text,encoding='utf-8')
    # V1.9.8: controlled Request Forms are parsed item-by-item. Every numbered
    # Golden item is retained in Profile review; unknown semantics become
    # Needs Review instead of disappearing. Standard engine checks are mapped
    # behind the Golden row or added explicitly from Standard Library.
    form_items=extract_golden_form_items(source_text)
    # V1.9.20 CMP-001: determine the actual shipped Chassis Label boundary from
    # the structurally selected Final Label image, then retain process/test
    # rows as Reference Only instead of runtime inspection requirements.
    layout,layout_score,layout_reason=select_final_label_image(tx_images,image_ocr_rows,machine_codes,final_label_media_names)
    scope_meta=_apply_chassis_scope_filter(form_items,layout,image_ocr_rows,machine_codes)
    # CMP-008: the notch/cut-corner direction is stated beside Label Example,
    # outside the numbered list. Add it as an explicit inspectable Golden item.
    notch_dir,notch_text=_extract_notch_direction(source_text)
    if notch_dir:
        form_items.append({
            'form_no':None,'item':'Golden Geometry: Label Notch Direction','type':'Golden Geometry','role':'FULL',
            'required':True,'selected':'TEXT_DEFINED','expected':notch_dir,'raw_text':notch_text,
            'origin':'GOLDEN','source':'Golden','engine_items':['Geometry: Label Notch Direction'],
            'presence_item':'','machine_code_field':'','machine_code_rule_known':True,
            'manual_review_allowed':True,'inspection_scope':'CHASSIS_LABEL','review_status':'AUTO_CLASSIFIED',
        })
    # Hard non-bypass rule: a machine code visible in the Golden example must
    # exist as a Profile inspection item even when the prose does not define
    # its payload/format. Add visual-only entries only when the numbered form
    # does not already cover that code type/count.
    qr_existing=sum(1 for r in form_items if r.get('type')=='Golden QR')
    bc_existing=sum(1 for r in form_items if r.get('type')=='Golden Barcode')
    layout_name=layout.name if layout else ''
    scoped_codes=[c for c in machine_codes if (not layout_name or Path(str(c.get('file',''))).name==layout_name)]
    qr_seen=[c for c in scoped_codes if c.get('kind')=='QR']
    bc_seen=[c for c in scoped_codes if c.get('kind')=='BARCODE']
    for idx,c in enumerate(qr_seen[qr_existing:],1):
        item=f'Golden Visual QR #{qr_existing+idx}'
        form_items.append({'form_no':None,'item':item,'type':'Golden QR','role':'DETAIL','required':True,
            'selected':'IMAGE_DETECTED','expected':'','raw_text':'Detected in Golden label example image',
            'origin':'GOLDEN','source':'Golden','engine_items':[],'presence_item':f'Golden Machine Code: QR Visual #{qr_existing+idx}',
            'manual_review_allowed':True,'review_status':'NEEDS_REVIEW','machine_code_ref':c})
    for idx,c in enumerate(bc_seen[bc_existing:],1):
        item=f'Golden Visual Barcode #{bc_existing+idx}'
        form_items.append({'form_no':None,'item':item,'type':'Golden Barcode','role':'DETAIL','required':True,
            'selected':'IMAGE_DETECTED','expected':'','raw_text':'Detected in Golden label example image',
            'origin':'GOLDEN','source':'Golden','engine_items':[],'presence_item':f'Golden Machine Code: Barcode Visual #{bc_existing+idx}',
            'manual_review_allowed':True,'review_status':'NEEDS_REVIEW','machine_code_ref':c})
    if not form_items:
        # Image-only / non-numbered fallback preserves the previously validated
        # inference path. In Profile Manager these inferred Standard rows stay
        # hidden; controlled numbered Request Forms use Golden-only review.
        fixed=_fixed_text_candidates(text)
        rows=[{
            'item':row['item'],'type':'Golden Text','role':row.get('role','DETAIL'),
            'required':bool(row.get('required',True)),'threshold':row.get('threshold',0.74),
            'expected':row.get('text',''),'origin':'GOLDEN','source':'Golden',
            'manual_review_allowed':True,'engine_items':[],
        } for row in fixed]
        rows += [{**row,'threshold':'','expected':'','manual_review_allowed':False,'origin':'AUTO_GOLDEN','source':'Auto inferred'}
                 for row in _standard_item_candidates(text)]
    else:
        rows=form_items
    profile['dynamic_standard_items']=[]
    profile=apply_editable_items(profile,rows)
    profile['golden_item_bindings']=_build_golden_item_bindings(profile)
    profile['runtime_form_driven_version']='1.9.23'
    profile['golden_scope']=scope_meta
    profile['golden_completeness']={
        'document_item_count':len(form_items),
        'profile_item_count':len(profile.get('golden_form_items',[]) or []),
        'document_item_numbers':[x.get('form_no') for x in form_items],
        'missing_item_numbers':[],
    }
    profile['rules']=_rules_from_golden_text(text)
    # Keep internal model and selected customer model as aliases. The Golden
    # form uses a filled square to indicate which printed model name is used.
    customer_model=''
    internal_model=identity['model']
    for _row in form_items:
        raw=str(_row.get('raw_text',''))
        if _row.get('form_no')==6 or 'model name' in raw.lower():
            cm=re.search(r'■\s*\(客戶\)\s*([A-Za-z0-9_.-]+)',raw,re.I)
            im=re.search(r'(?:■|□)\s*\(康全\)\s*([A-Za-z0-9_.-]+)',raw,re.I)
            if cm: customer_model=cm.group(1)
            if im and not internal_model: internal_model=im.group(1)
            break
    profile['customer_model']=customer_model
    profile['model_aliases']=list(dict.fromkeys([x for x in (identity['model'],customer_model) if x]))
    # Import itself is not a manual edit; retain a clean audit marker.
    profile['profile_edit_log']=[{
        'edited_at':datetime.now().isoformat(timespec='seconds'),
        'action':'AUTO_GOLDEN_IMPORT','item_count':len(rows),
        'document_item_count':len(form_items),
    }]
    if layout:
        try:
            rel=layout.relative_to(tx_root)
            profile.setdefault('golden_import',{})['candidate_layout_image']=str(root/rel)
        except Exception:
            profile.setdefault('golden_import',{})['candidate_layout_image']=str(root/'imported_media'/layout.name)
        profile.setdefault('golden_import',{})['candidate_layout_score']=round(float(layout_score),3)
        profile.setdefault('golden_import',{})['candidate_layout_reason']=layout_reason
        profile.setdefault('golden_import',{})['candidate_layout_policy']='FINAL_LABEL_SCORE_V2_STRUCTURAL'
        profile.setdefault('golden_import',{})['final_label_image']=profile['golden_import']['candidate_layout_image']
    profile['golden_import']['embedded_image_count']=len(tx_images)
    profile['golden_import']['import_generation']=source_sha[:12]

    out=external_profile_dir()/f"{identity['file_stem']}.json"
    errors=validate_profile_structure(profile,out)
    if errors:
        shutil.rmtree(tx_root,ignore_errors=True)
        raise RuntimeError('Imported Golden profile check failed: ' + '; '.join(errors))

    # Commit assets first, then JSON. Any previous asset directory for this
    # exact identity is removed in one controlled step so stale media cannot
    # be selected by Manual Review after re-import.
    backup=None
    try:
        if root.exists():
            backup=root.parent/f".{root.name}__backup_{os.getpid()}"
            if backup.exists(): shutil.rmtree(backup,ignore_errors=True)
            root.rename(backup)
        tx_root.rename(root)
        out.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
        if backup and backup.exists(): shutil.rmtree(backup,ignore_errors=True)
    except Exception:
        if root.exists() and root != tx_root:
            shutil.rmtree(root,ignore_errors=True)
        if backup and backup.exists(): backup.rename(root)
        shutil.rmtree(tx_root,ignore_errors=True)
        raise
    return out,profile



def _build_golden_item_bindings(profile: dict) -> dict[str,int]:
    """Build exact inspection-item -> Request-Form number bindings.

    Numbered Golden forms are authoritative. Manual Review must NEVER infer an
    item specification by fuzzy similarity once a numbered form exists.
    """
    bindings={}
    for row in profile.get('golden_form_items',[]) or []:
        if not isinstance(row,dict) or row.get('form_no') is None:
            continue
        try:no=int(row.get('form_no'))
        except Exception:continue
        keys=[row.get('item',''),row.get('presence_item','')]
        keys.extend(row.get('engine_items',[]) or [])
        for key in keys:
            key=str(key or '').strip()
            if key and key not in bindings:
                bindings[key]=no
    return bindings


def normalize_dynamic_profile_for_runtime(profile: dict) -> tuple[dict,bool,list[str]]:
    """Migrate stale Dynamic profiles to the current form-driven boundary.

    Profiles imported by V1.9.13 and earlier may still contain generated
    Golden-Text requirements derived from password/support screenshots. Those
    stale requirements survive an EXE upgrade because external Profile JSON is
    persistent. Rebuild runtime requirements exclusively from numbered Golden
    rows + explicit Standard/Manual additions so upgrading the EXE also fixes
    already-imported Profiles without forcing the operator to re-import.
    """
    if not profile.get('dynamic_profile') or not (profile.get('golden_form_items') or []):
        return profile,False,[]
    if str(profile.get('runtime_form_driven_version','')) in ('1.9.22','1.9.23') and profile.get('golden_item_bindings'):
        return profile,False,[]
    before=deepcopy(profile)
    rows=_dynamic_item_rows(profile)
    # V1.9.20 migration: retrofit CMP-001 scope and CMP-008 notch to existing
    # external profiles so operators do not have to re-import every Golden.
    gi=profile.get('golden_import',{}) or {}
    full_text=''
    try:
        txt_path=Path(str(gi.get('extracted_text_file','') or ''))
        if txt_path.exists(): full_text=txt_path.read_text(encoding='utf-8',errors='ignore')
    except Exception:
        full_text=''
    if not full_text:
        full_text='\n'.join(str(r.get('raw_text','')) for r in rows if isinstance(r,dict))
    layout_path=None
    try:
        lp=Path(str(gi.get('final_label_image') or gi.get('candidate_layout_image') or ''))
        if lp.exists(): layout_path=lp
    except Exception:
        layout_path=None
    scope_meta=_apply_chassis_scope_filter(rows,layout_path,list(gi.get('image_ocr_results',[]) or []),list(gi.get('machine_codes',[]) or []))
    notch_dir,notch_text=_extract_notch_direction(full_text)
    if notch_dir and not any(str(r.get('item',''))=='Golden Geometry: Label Notch Direction' for r in rows if isinstance(r,dict)):
        rows.append({
            'form_no':None,'item':'Golden Geometry: Label Notch Direction','type':'Golden Geometry','role':'FULL',
            'required':True,'selected':'TEXT_DEFINED','expected':notch_dir,'raw_text':notch_text,
            'origin':'GOLDEN','source':'Golden','engine_items':['Geometry: Label Notch Direction'],
            'presence_item':'','machine_code_field':'','machine_code_rule_known':True,
            'manual_review_allowed':True,'inspection_scope':'CHASSIS_LABEL','review_status':'AUTO_CLASSIFIED',
        })
    cleaned=apply_editable_items(profile,rows)
    cleaned['golden_scope']=scope_meta
    cleaned['profile_version']='1.9.23'
    cleaned['runtime_form_driven_version']='1.9.23'
    cleaned['golden_item_bindings']=_build_golden_item_bindings(cleaned)
    # Runtime-rule migration for already-imported external profiles.  V1.9.16
    # could persist password_length=0 because Password: Random N characters was
    # not extracted.  Re-derive safe form rules and only fill missing/invalid
    # values so engineer-edited valid rules are preserved.
    form_text='\n'.join(str(r.get('raw_text','')) for r in (cleaned.get('golden_form_items',[]) or []) if isinstance(r,dict))
    derived_rules=_rules_from_golden_text(full_text or form_text)
    current_rules=cleaned.setdefault('rules',{})
    if int(current_rules.get('password_length',0) or 0) <= 0 and int(derived_rules.get('password_length',0) or 0) > 0:
        current_rules['password_length']=int(derived_rules['password_length'])
    if derived_rules.get('notch_direction'):
        current_rules['notch_direction']=derived_rules['notch_direction']
        current_rules['notch_direction_source']=derived_rules.get('notch_direction_source','')
    # Migration is a controlled engine update, not an operator edit. Preserve
    # a previously VALIDATED status only if every required item still has a
    # handling path under the new rules; otherwise DRAFT is safer.
    old_status=str(before.get('profile_status','DRAFT'))
    if old_status=='VALIDATED' and not validation_readiness_errors(cleaned):
        cleaned['profile_status']='VALIDATED'
    notes=[]
    stale_before={str(x.get('item','')) for x in before.get('dynamic_fixed_texts',[]) or [] if isinstance(x,dict)}
    stale_after={str(x.get('item','')) for x in cleaned.get('dynamic_fixed_texts',[]) or [] if isinstance(x,dict)}
    removed=sorted(x for x in stale_before-stale_after if x)
    if removed: notes.append('removed stale generated Golden Text: '+', '.join(removed[:12]))
    changed=(cleaned != before)
    return cleaned,changed,notes


def validation_readiness_summary(profile: dict) -> dict:
    """Summarize final Profile handling paths for operator confirmation."""
    summary={'auto':0,'manual':0,'disabled':0,'missing':0,'total':0}
    if not profile.get('dynamic_profile'):
        return summary
    for row in profile.get('golden_form_items',[]) or []:
        if not isinstance(row,dict): continue
        summary['total']+=1
        if not row.get('required',False):
            summary['disabled']+=1; continue
        typ=str(row.get('type','Needs Review'))
        auto=bool(row.get('engine_items') or row.get('presence_item'))
        if typ=='Golden Text':
            auto=True  # Dynamic Golden text engine is the automatic path.
        if auto:
            summary['auto']+=1
        elif bool(row.get('manual_review_allowed',True)):
            summary['manual']+=1
        else:
            summary['missing']+=1
    return summary

def validate_profile_structure(profile: dict, path: Path|None=None) -> list[str]:
    errors=[]
    errors.extend(dynamic_identity_errors(profile,path))
    for key in ('profile_name','profile_version','model','live'):
        if not profile.get(key): errors.append(f'Missing required profile key: {key}')
    live=profile.get('live',{}) or {}
    if not isinstance(live.get('required_items',[]),list): errors.append('live.required_items must be a list')
    req=list(live.get('required_items',[]) or []) if isinstance(live.get('required_items',[]),list) else []
    if len(req) != len(set(req)): errors.append('live.required_items contains duplicates')
    if profile.get('dynamic_profile'):
        # Dynamic profiles may not silently carry bundled-model fixed settings.
        allowed_fixed={'model'}
        extra_fixed=set((profile.get('fixed_fields',{}) or {}))-allowed_fixed
        if extra_fixed: errors.append('Dynamic Profile contains model-specific inherited fixed_fields: ' + ', '.join(sorted(extra_fixed)))
        if not isinstance(profile.get('dynamic_standard_items',[]),list): errors.append('dynamic_standard_items must be a list')
        for row in profile.get('dynamic_standard_items',[]) or []:
            item=str((row or {}).get('item',''))
            typ=str((row or {}).get('type','Standard'))
            if typ=='Standard' and item and item not in SUPPORTED_STANDARD_ITEMS:
                errors.append(f'Unsupported Standard inspection item: {item}. Use Golden Text for custom fixed content.')
    art=profile.get('artwork_verification',{}) or {}
    if art.get('enabled'):
        for s in art.get('symbols',[]) or []:
            if s.get('required') and not s.get('template'): errors.append(f"Artwork template missing: {s.get('name') or s.get('id')}")
    for row in profile.get('dynamic_fixed_texts',[]) or []:
        if not row.get('item') or not row.get('text'): errors.append('dynamic_fixed_texts requires item + text')
        try:
            t=float(row.get('threshold',0.74))
            if not 0.0 < t <= 1.0: errors.append(f"Invalid threshold for {row.get('item')}: {t}")
        except Exception: errors.append(f"Invalid threshold for {row.get('item')}")
    return errors



def validation_readiness_errors(profile: dict) -> list[str]:
    """Block VALIDATED only when a Required item has no handling path.

    AUTO is preferred, but MANUAL REVIEW is a first-class, traceable inspection
    path. A missing automatic mapping/template must therefore not block final
    confirmation when Manual Review is allowed. This matches the factory-use
    workflow: nothing may be bypassed, but not everything must be automated.
    """
    errors=[]
    if not profile.get('dynamic_profile'):
        return errors
    comp=profile.get('golden_completeness',{}) or {}
    missing=list(comp.get('missing_item_numbers',[]) or [])
    if missing:
        errors.append('Golden completeness: missing form items ' + ', '.join(map(str,missing)))
    doc_count=int(comp.get('document_item_count',0) or 0)
    prof_count=len(profile.get('golden_form_items',[]) or [])
    if doc_count and prof_count < doc_count:
        errors.append(f'Golden completeness: document has {doc_count} items but Profile has {prof_count}')
    for row in profile.get('golden_form_items',[]) or []:
        if not isinstance(row,dict) or not row.get('required',False):
            continue
        typ=str(row.get('type','Needs Review'))
        no=row.get('form_no','?'); label=str(row.get('item',''))
        auto_path=bool(row.get('engine_items') or row.get('presence_item')) or typ=='Golden Text'
        manual_path=bool(row.get('manual_review_allowed',True))
        if not auto_path and not manual_path:
            errors.append(f'Golden item #{no} has no AUTO or MANUAL handling path: {label}')
    return errors


def save_profile_identity_edits(path: Path, profile: dict, model: str, label_type: str,
                                label_pn: str='', customer_model: str='') -> tuple[Path,dict]:
    """Safely edit Dynamic Profile metadata and rename the JSON if required."""
    if not profile.get('dynamic_profile'):
        raise ValueError('Bundled engineering profiles cannot be renamed in Profile Manager.')
    model=str(model or '').strip()
    label_type=str(label_type or '').strip()
    label_pn=str(label_pn or '').strip()
    customer_model=str(customer_model or '').strip()
    if not model: raise ValueError('Internal Model cannot be blank.')
    if not label_type: raise ValueError('Label Type cannot be blank.')
    identity=canonical_profile_identity(model,label_type,label_pn)
    new=deepcopy(profile)
    new['model']=identity['model']; new['label_type']=identity['label_type']; new['label_pn']=identity['label_pn']
    new['profile_name']=identity['display_name']; new['profile_version']='1.9.23'; new['profile_status']='DRAFT'
    sha=str((new.get('golden_import') or {}).get('source_sha256',''))
    new['profile_identity']={**identity,'source_sha256':sha}
    ff=new.setdefault('fixed_fields',{})
    ff['model']=identity['model']
    new['customer_model']=customer_model
    new['model_aliases']=list(dict.fromkeys([x for x in (identity['model'],customer_model) if x]))
    new.setdefault('profile_edit_log',[]).append({
        'edited_at':datetime.now().isoformat(timespec='seconds'),
        'action':'PROFILE_METADATA_EDIT','internal_model':identity['model'],
        'customer_model':customer_model,'label_type':identity['label_type'],'label_pn':identity['label_pn'],
    })
    new_path=path.parent/f"{identity['file_stem']}.json"
    errors=validate_profile_structure(new,new_path)
    if errors: raise ValueError('\n'.join(errors))
    new_path.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf-8')
    if path.resolve()!=new_path.resolve():
        try:path.unlink(missing_ok=True)
        except Exception:pass
    return new_path,new

def mark_validated(path: Path, profile: dict) -> dict:
    errors=validate_profile_structure(profile,path) + validation_readiness_errors(profile)
    if errors:
        raise ValueError('\n'.join(errors))
    profile=deepcopy(profile)
    identity=canonical_profile_identity(profile.get('model',''),profile.get('label_type',''),profile.get('label_pn',''))
    profile['profile_name']=identity['display_name']
    profile['profile_identity']={**identity,'source_sha256':str((profile.get('golden_import') or {}).get('source_sha256',''))}
    profile['profile_status']='VALIDATED'
    profile.setdefault('golden_import',{})['validated_at']=datetime.now().isoformat(timespec='seconds')
    path.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    return profile
