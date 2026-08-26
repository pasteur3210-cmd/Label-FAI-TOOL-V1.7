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
    low=(str(source_name or '')+' '+str(text or '')[:1200]).lower()
    if 'inner box' in low or 'inner_box' in low:
        return 'Inner Box Label'
    if 'chassis' in low:
        return 'Chassis Label'
    return fallback or 'Label'


def canonical_profile_identity(model: str, label_type: str, label_pn: str='') -> dict:
    model=str(model or '').strip() or 'New Model'
    label_type=str(label_type or '').strip() or 'Label'
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


def _extract_docx(path: Path, dest: Path) -> tuple[str, list[Path]]:
    text_parts=[]; images=[]
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with zipfile.ZipFile(path,'r') as z:
        if 'word/document.xml' in z.namelist():
            root=ET.fromstring(z.read('word/document.xml'))
            for p in root.findall('.//w:p',ns):
                parts=[(x.text or '') for x in p.findall('.//w:t',ns)]
                line=''.join(parts).strip()
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
    m=re.search(r'\b\d{6}-\d{3}\b',text)
    return m.group(0) if m else fallback


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
                rows.append({'file':str(img_path),'line_count':len(structured),'text':text.strip()})
        except Exception as exc:
            rows.append({'file':str(img_path),'line_count':0,'error':repr(exc),'text':''})
    return '\n'.join(texts), rows

def _largest_image(images: list[Path]) -> Path|None:
    if not images: return None
    return max(images,key=lambda p:p.stat().st_size if p.exists() else 0)



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
    countries=[]
    for c in ('China','Taiwan'):
        if re.search(r'Made\s+in\s+'+c,t,re.I): countries.append(c)
    if countries: rules['made_in_allowed']=countries
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
    """Return editable inspection rows for Profile Manager/tests."""
    required=set((profile.get('live',{}) or {}).get('required_items',[]) or [])
    dynamic={r.get('item'):r for r in (profile.get('dynamic_fixed_texts',[]) or []) if isinstance(r,dict)}
    meta={r.get('item'):r for r in (profile.get('dynamic_standard_items',[]) or []) if isinstance(r,dict)}
    role_lookup={}
    for role,items in ((profile.get('image_inspection',{}) or {}).get('role_items',{}) or {}).items():
        for item in items or []: role_lookup[item]=role
    names=[]
    for item in list(required)+list(dynamic)+list(meta):
        if item and item not in names: names.append(item)
    rows=[]
    for item in names:
        d=dynamic.get(item,{})
        m=meta.get(item,{})
        rows.append({
            'item':item,
            'type':'Golden Text' if item in dynamic else m.get('type',('Artwork' if str(item).startswith('Artwork:') else 'Standard')),
            'role':role_lookup.get(item,d.get('role',m.get('role','DETAIL'))),
            'required':item in required,
            'threshold':d.get('threshold',''),
            'expected':d.get('text',''),
            'origin':d.get('origin',m.get('origin','MANUAL' if item not in required else 'PROFILE')),
            'manual_review_allowed':bool(d.get('manual_review_allowed',str(item).startswith(('Golden Text:','Artwork:')))),
        })
    return rows


def apply_editable_items(profile: dict, rows: list[dict]) -> dict:
    """Apply Visual Profile Editor rows back to runtime profile data."""
    profile=deepcopy(profile)
    live=profile.setdefault('live',{})
    req=[]; dynamic=[]; standard=[]; role_items={}
    for idx,row in enumerate(rows,1):
        item=str(row.get('item','')).strip()
        if not item: continue
        typ=str(row.get('type','Standard')).strip() or 'Standard'
        role=str(row.get('role','DETAIL')).strip().upper() or 'DETAIL'
        required=bool(row.get('required',False))
        if required and item not in req: req.append(item)
        role_items.setdefault(role,[])
        if item not in role_items[role]: role_items[role].append(item)
        if typ=='Golden Text':
            expected=str(row.get('expected','')).strip()
            if not expected: continue
            try: threshold=float(row.get('threshold',0.74) or 0.74)
            except Exception: threshold=0.74
            threshold=min(1.0,max(0.1,threshold))
            dynamic.append({
                'id':f'fixed_{idx:02d}','name':item.replace('Golden Text: ','',1)[:64],
                'item':item,'text':expected,'threshold':threshold,'required':required,
                'role':role,'manual_review_allowed':bool(row.get('manual_review_allowed',True)),
                'origin':str(row.get('origin','MANUAL_EDIT')) or 'MANUAL_EDIT',
            })
        else:
            standard.append({'item':item,'type':typ,'role':role,'required':required,'origin':str(row.get('origin','MANUAL_EDIT')) or 'MANUAL_EDIT'})
    live['required_items']=req
    # Custom targets only for dynamic text. They are generic fuzzy OCR targets.
    live['custom_targets']=[{
        'item':r['item'],'title':r['name'],'instruction':f"Place '{r['name']}' inside the target area.",
        'target_rect':[0.08,0.20,0.92,0.80],'mode':'fuzzy','expected':r['text'],'threshold':r['threshold']
    } for r in dynamic]
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
    root.mkdir(parents=True,exist_ok=True)

    # Move/copy extracted staging media into the canonical asset directory.
    canonical_images=[]
    for img in images:
        dst=root/'imported_media'/img.name
        dst.parent.mkdir(parents=True,exist_ok=True)
        if img.resolve() != dst.resolve():
            shutil.copy2(img,dst)
        canonical_images.append(dst)
    images=canonical_images

    # The request-form body often stores the actual approved label as an
    # embedded image. OCR those images once during import so inspection items
    # are derived from the Golden, not from the seed profile.
    image_ocr_text,image_ocr_rows=_ocr_golden_images(images)
    source_text=text
    if image_ocr_text:
        text=(text + '\n' + image_ocr_text).strip()

    source_sha=_sha256(source)
    profile.update({
        'profile_name':base_name,
        'profile_version':'1.9.4',
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
        },
    })
    if identity['model']:
        profile.setdefault('fixed_fields',{})['model']=identity['model']
    (root/'golden_text.txt').write_text(text,encoding='utf-8')
    fixed=_fixed_text_candidates(text)
    standard=_standard_item_candidates(text)
    profile['dynamic_fixed_texts']=fixed
    profile['dynamic_standard_items']=standard
    rows=[]
    for row in standard:
        rows.append({**row,'threshold':'','expected':'','manual_review_allowed':False})
    for row in fixed:
        rows.append({
            'item':row['item'],'type':'Golden Text','role':row.get('role','DETAIL'),
            'required':bool(row.get('required',True)),'threshold':row.get('threshold',0.74),
            'expected':row.get('text',''),'origin':'AUTO_GOLDEN','manual_review_allowed':True,
        })
    profile=apply_editable_items(profile,rows)
    profile['rules']=_rules_from_golden_text(text)
    profile['model_aliases']=[identity['model']]
    profile['customer_model']=''
    # Import itself is not a manual edit; retain a clean audit marker.
    profile['profile_edit_log']=[{
        'edited_at':datetime.now().isoformat(timespec='seconds'),
        'action':'AUTO_GOLDEN_IMPORT','item_count':len(rows),
    }]
    layout=_largest_image(images)
    if layout:
        profile.setdefault('golden_import',{})['candidate_layout_image']=str(layout)
    profile['golden_import']['embedded_image_count']=len(images)

    out=external_profile_dir()/f"{identity['file_stem']}.json"
    out.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    errors=dynamic_identity_errors(profile,out)
    if errors:
        try:
            out.unlink(missing_ok=True)
        finally:
            raise RuntimeError('Imported Golden identity check failed: ' + '; '.join(errors))
    return out,profile


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
        artwork_required=[x for x in req if str(x).startswith('Artwork: ')]
        if artwork_required:
            art=profile.get('artwork_verification',{}) or {}
            configured={str(x.get('item') or ('Artwork: '+str(x.get('name','')))) for x in art.get('symbols',[]) or [] if isinstance(x,dict) and x.get('template')}
            for item in artwork_required:
                if not art.get('enabled') or item not in configured:
                    errors.append(f'Artwork item requires a Golden template before validation: {item}')
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
    new['profile_name']=identity['display_name']; new['profile_version']='1.9.4'; new['profile_status']='DRAFT'
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
    errors=validate_profile_structure(profile,path)
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
