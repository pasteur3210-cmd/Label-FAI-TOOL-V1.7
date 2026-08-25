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
    keys=('gpon voip gateway','class 1 laser','input ','usb ','http://','https://','comtrend','made in')
    for s in lines:
        low=s.lower()
        if any(k in low for k in keys):
            preferred.append(s)
    out=[]
    for i,s in enumerate(preferred[:20],1):
        short=s[:42].rstrip()
        out.append({'id':f'fixed_{i:02d}','name':short,'item':f'Golden Text: {short}','text':s,'threshold':0.74,'required':True,'role':'DETAIL','manual_review_allowed':True})
    return out


def _largest_image(images: list[Path]) -> Path|None:
    if not images: return None
    return max(images,key=lambda p:p.stat().st_size if p.exists() else 0)


def build_dynamic_profile(source_path: str, base_profile: dict, profile_name: str|None=None) -> tuple[Path,dict]:
    source=Path(source_path).resolve()
    if not source.exists(): raise FileNotFoundError(source)
    base_name=profile_name or f"{base_profile.get('model','New Model')} Dynamic Label"
    root=external_profile_dir()/'golden_assets'/_safe_name(base_name)
    root.mkdir(parents=True,exist_ok=True)
    text,images,actual_source=_extract_text_and_media(source,root)
    profile=deepcopy(base_profile)
    model=_candidate_model(text, str(profile.get('model','')))
    label_pn=_candidate_label_pn(text, str(profile.get('label_pn','')))
    profile.update({
        'profile_name':base_name,
        'profile_version':'1.9.0',
        'profile_status':'DRAFT',
        'dynamic_profile':True,
        'model':model,
        'label_pn':label_pn,
        'source_spec':source.name,
        'golden_import':{
            'source_file':str(source),
            'source_sha256':_sha256(source),
            'imported_at':datetime.now().isoformat(timespec='seconds'),
            'converted_source':str(actual_source) if actual_source != source else '',
            'asset_dir':str(root),
            'extracted_text_file':str(root/'golden_text.txt'),
        },
    })
    if model:
        profile.setdefault('fixed_fields',{})['model']=model
    low_source=(source.name+' '+text[:500]).lower()
    if 'inner box' in low_source:
        profile['label_type']='Inner Box Label'
    elif 'chassis' in low_source:
        profile['label_type']='Chassis Label'
    (root/'golden_text.txt').write_text(text,encoding='utf-8')
    fixed=_fixed_text_candidates(text)
    profile['dynamic_fixed_texts']=fixed
    live=profile.setdefault('live',{})
    req=list(live.get('required_items',[]) or [])
    for row in fixed:
        if row['item'] not in req: req.append(row['item'])
    live['required_items']=req
    # Dynamic targets are usable immediately in Manual Item Debug/live mode.
    custom=list(live.get('custom_targets',[]) or [])
    existing={x.get('item') for x in custom if isinstance(x,dict)}
    for row in fixed:
        if row['item'] not in existing:
            custom.append({'item':row['item'],'title':row['name'],'instruction':f"Place '{row['name']}' inside the target area.",
                           'target_rect':[0.08,0.20,0.92,0.80],'mode':'fuzzy','expected':row['text'],'threshold':row['threshold']})
    live['custom_targets']=custom
    # Profile-driven role map; copied legacy profiles become data, not code.
    img=profile.setdefault('image_inspection',{})
    img.setdefault('role_items',{})
    for row in fixed:
        img['role_items'].setdefault(row.get('role','DETAIL'),[])
        if row['item'] not in img['role_items'][row.get('role','DETAIL')]: img['role_items'][row.get('role','DETAIL')].append(row['item'])
    layout=_largest_image(images)
    if layout:
        profile.setdefault('golden_import',{})['candidate_layout_image']=str(layout)
    profile['golden_import']['embedded_image_count']=len(images)
    out=external_profile_dir()/f'{_safe_name(base_name)}.json'
    out.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    return out,profile


def validate_profile_structure(profile: dict) -> list[str]:
    errors=[]
    for key in ('profile_name','profile_version','model','live'):
        if not profile.get(key): errors.append(f'Missing required profile key: {key}')
    live=profile.get('live',{}) or {}
    if not isinstance(live.get('required_items',[]),list): errors.append('live.required_items must be a list')
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


def mark_validated(path: Path, profile: dict) -> dict:
    errors=validate_profile_structure(profile)
    if errors: raise ValueError('\n'.join(errors))
    profile=deepcopy(profile)
    profile['profile_status']='VALIDATED'
    profile.setdefault('golden_import',{})['validated_at']=datetime.now().isoformat(timespec='seconds')
    path.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
    return profile
