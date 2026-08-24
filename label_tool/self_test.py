from __future__ import annotations
import json
from pathlib import Path
import time
import sys
import cv2
import numpy as np
from .core.ocr_runtime import OCRProcessService


def run_ocr_self_test(output_path='ocr_self_test.json'):
    out=Path(output_path)
    out.parent.mkdir(parents=True,exist_ok=True)
    service=OCRProcessService(init_timeout_sec=20,read_timeout_sec=10)
    payload={'test':'EXE_OCR_RUNTIME_SMOKE','passed':False}
    try:
        img=np.full((180,1000,3),255,dtype=np.uint8)
        cv2.putText(img,'GPON VoIP Gateway',(35,115),cv2.FONT_HERSHEY_SIMPLEX,2.0,(0,0,0),4,cv2.LINE_AA)
        info=service.preflight(img,init_timeout_sec=20,read_timeout_sec=10)
        payload.update(info)
        payload['passed']=True
        payload['reason']='RapidOCR process initialized and completed real inference inside packaged runtime.'
        return_code=0
    except Exception as exc:
        payload['error']=repr(exc)
        return_code=2
    finally:
        service.stop()
        payload['completed_at']=time.strftime('%Y-%m-%dT%H:%M:%S')
        out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return return_code


def run_artwork_self_test(output_path='artwork_self_test.json'):
    """Verify packaged runtime can resolve every required Golden Artwork template."""
    from .core.artwork_presence import ArtworkPresenceDetector, artwork_dir_candidates, bundled_artwork_dir
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'test': 'EXE_ARTWORK_RESOURCE_SMOKE',
        'passed': False,
        'selected_root': str(bundled_artwork_dir()),
        'candidates': [str(x) for x in artwork_dir_candidates()],
        'profiles': []
    }
    rc = 0
    try:
        profile_dir_candidates = [
            Path(sys.executable).resolve().parent / 'profiles' if getattr(sys, 'frozen', False) else None,
            Path(getattr(sys, '_MEIPASS', '')) / 'label_tool' / 'profiles' if getattr(sys, '_MEIPASS', None) else None,
            Path(__file__).resolve().parent / 'profiles',
        ]
        profile_dir = next((p for p in profile_dir_candidates if p is not None and p.exists()), None)
        if profile_dir is None:
            raise RuntimeError('Profile directory not found')
        for p in sorted(profile_dir.glob('*.json')):
            profile = json.loads(p.read_text(encoding='utf-8'))
            art = profile.get('artwork_verification') or {}
            if not art.get('enabled'):
                continue
            det = ArtworkPresenceDetector(profile)
            required = [x['item'] for x in det.symbols]
            loaded = sorted(det.templates.keys())
            missing = [x for x in required if x not in det.templates]
            status = det.resource_status()
            algorithm = []
            if det.golden_layout is not None and getattr(det.golden_layout, 'size', 0):
                for cfg in det.symbols:
                    item = cfg['item']
                    templ = det.templates.get(item)
                    center = det.expected_centers.get(item)
                    threshold = float(cfg.get('shape_threshold', cfg.get('presence_threshold', 0.56)))
                    if templ is None or center is None:
                        algorithm.append({'item': item, 'passed': False, 'reason': 'template/center unavailable'})
                        rc = max(rc, 5)
                        continue
                    roi, origin = det._search_roi(det.golden_layout, center, cfg)
                    score, scale, loc, size = det._best_match(roi, templ, cfg.get('detect_scales') or det.DEFAULT_SCALES)
                    roi_center = det._center_norm(loc, size, roi.shape) if size != (0,0) else None
                    actual_center = det._roi_center_to_full(roi_center, origin, roi.shape, det.golden_layout.shape)
                    pos_pass, pos_err = det._position_result(actual_center, center, cfg)
                    passed = bool(score >= threshold and pos_pass)
                    algorithm.append({
                        'item': item, 'passed': passed, 'shape_score': round(float(score),4),
                        'shape_threshold': threshold, 'position_pass': bool(pos_pass),
                        'position_error': round(float(pos_err),4), 'scale': float(scale),
                    })
                    if not passed:
                        rc = max(rc, 5)
            else:
                rc = max(rc, 5)
            payload['profiles'].append({
                'file': p.name,
                'profile_name': profile.get('profile_name',''),
                'required': required,
                'loaded': loaded,
                'missing': missing,
                'resource_status': status,
                'golden_algorithm_check': algorithm,
            })
            if missing:
                rc = max(rc, 3)
        payload['passed'] = rc == 0 and bool(payload['profiles'])
        if not payload['passed'] and rc == 0:
            rc = 4
    except Exception as exc:
        payload['error'] = repr(exc)
        rc = 2
    payload['completed_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return rc


def run_multi_image_self_test(output_path='multi_image_self_test.json'):
    """Packaged-runtime smoke for V1.7.9 guided multi-image fusion."""
    from tempfile import TemporaryDirectory
    from .core.multi_image_inspection import MultiImageInspectionEngine, MultiImageResult, ImageEvidence
    out=Path(output_path); out.parent.mkdir(parents=True,exist_ok=True)
    payload={'test':'EXE_MULTI_IMAGE_SMOKE_V179','passed':False}
    rc=0
    try:
        profile={
            'profile_name':'Smoke','label_type':'Chassis Label',
            'rules':{
                'sn_regex':r'\d{2}[1-9A-C]4297UF-[A-Z0-9]{2}\d{6}',
                'sn_display':'YYM4297UF-FFXXXXXX','pn_regex':r'738125-00\d','pn_display':'738125-00X',
                'made_in_allowed':['China','Taiwan'],'mac_regex':r'[0-9A-F]{12}',
                'gpon_prefix':'434D5444','gpon_regex':r'434D5444[0-9A-F]{8}',
                'ssid_prefix':'Telekom Slovenije_','password_length':8,'wifi_key_length':14
            },
            'live':{'required_items':['Rule: SSID = MAC Last 6','Rule: GPON S/N = Prefix + MAC Last 8']}
        }
        eng=MultiImageInspectionEngine.__new__(MultiImageInspectionEngine); eng.profile=profile; eng.software_version='self-test'
        r=MultiImageResult(overall='PASS',session_id='smoke',session_dir='',image_count=5,initial_image_count=5,identity_status='PASS')
        r.session_fields={'mac_barcode':'1C6499AFB49D','ssid':'Telekom Slovenije_AFB49D','gpon_sn_barcode':'434D544499AFB49D'}
        r.field_sources={
            'mac_barcode':{'source':'identity.jpg','quality':0.9,'value':'1C6499AFB49D'},
            'ssid':{'source':'wifi.jpg','quality':0.9,'value':'Telekom Slovenije_AFB49D'},
            'gpon_sn_barcode':{'source':'identity.jpg','quality':0.9,'value':'434D544499AFB49D'}
        }
        best={}; conflicts={}
        eng._merge_session_rules(r,{},best,conflicts)
        payload['ssid_mac_fusion']=best.get('Rule: SSID = MAC Last 6').result if best.get('Rule: SSID = MAC Last 6') else 'MISSING'
        payload['gpon_mac_fusion']=best.get('Rule: GPON S/N = Prefix + MAC Last 8').result if best.get('Rule: GPON S/N = Prefix + MAC Last 8') else 'MISSING'
        payload['role_identity']=eng.classify_photo_role({'sn_text':'2654297UF-AA000028','mac_text':'1C6499AFB49D'},['1C6499AFB49D'],'',4,5)
        payload['role_compliance']=eng.classify_photo_role({'made_in':'China','has_laser_text':True},[],'CLASS 1 LASER PRODUCT',5,5)
        with TemporaryDirectory() as td:
            r.session_dir=td; r.evidence=best; r.photo_roles={'full.jpg':'FULL','identity.jpg':'IDENTITY','wifi.jpg':'WIFI'}
            report=eng._write_excel(r,{})
            payload['report_created']=Path(report).exists()
        payload['passed']=bool(payload['report_created'] and payload['ssid_mac_fusion']=='PASS' and payload['gpon_mac_fusion']=='PASS' and payload['role_identity']=='IDENTITY' and payload['role_compliance']=='COMPLIANCE')
        if not payload['passed']: rc=3
    except Exception as exc:
        payload['error']=repr(exc); rc=2
    payload['completed_at']=time.strftime('%Y-%m-%dT%H:%M:%S')
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return rc
