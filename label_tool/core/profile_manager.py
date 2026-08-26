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

def _display_name(data: dict, path: Path) -> str:
    """Return a unique UI key without changing profile identity metadata.

    Dynamic profiles may share the same model/label type but have different
    Golden label P/Ns. V1.9.5 de-duplicated by profile_name only, which could
    silently select an older Golden. Include label P/N in the UI key so every
    imported Golden remains selectable and unambiguous.
    """
    base=str(data.get('profile_name') or path.stem)
    if data.get('dynamic_profile'):
        pn=str(data.get('label_pn') or '').strip()
        if pn:
            return f"{base} [{pn}]"
    return base

def discover_profiles():
    out=[]; seen=set()
    for folder in (external_profile_dir(), bundled_profile_dir()):
        if not folder.exists(): continue
        for p in sorted(folder.glob('*.json')):
            try:
                d=json.loads(p.read_text(encoding='utf-8'))
                name=_display_name(d,p)
                k=name.lower()
                if k in seen:
                    # Same visible identity should not hide a second file.
                    name=f"{name} <{p.stem}>"; k=name.lower()
                if k in seen: continue
                seen.add(k); out.append((name,p,d))
            except Exception:
                pass
    return out
