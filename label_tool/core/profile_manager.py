from pathlib import Path
import json, sys

def application_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]

def bundled_profile_dir():
    if getattr(sys, '_MEIPASS', None):
        return Path(sys._MEIPASS) / 'label_tool' / 'profiles'
    return Path(__file__).resolve().parents[1] / 'profiles'

def external_profile_dir():
    p=application_dir()/'profiles'; p.mkdir(parents=True,exist_ok=True); return p

def discover_profiles():
    out=[]; seen=set()
    for folder in (external_profile_dir(), bundled_profile_dir()):
        if not folder.exists(): continue
        for p in sorted(folder.glob('*.json')):
            try:
                d=json.loads(p.read_text(encoding='utf-8'))
                name=d.get('profile_name') or p.stem
                k=name.lower()
                if k in seen: continue
                seen.add(k); out.append((name,p,d))
            except Exception:
                pass
    return out
