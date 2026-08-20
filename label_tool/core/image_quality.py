import cv2
from .models import QualityResult

def evaluate_image_quality(image,cfg):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    sharp=float(cv2.Laplacian(gray,cv2.CV_64F).var()); bright=float(gray.mean()); contrast=float(gray.std())
    q=cfg.get('image_quality',{}); mins=float(q.get('min_sharpness',55)); minb=float(q.get('min_brightness',45)); maxb=float(q.get('max_brightness',235)); minc=float(q.get('min_contrast',22))
    sp=sharp>=mins; bp=minb<=bright<=maxb; cp=contrast>=minc; reasons=[]
    if not sp: reasons.append(f'Sharpness {sharp:.1f} < {mins:.1f}')
    if bright<minb: reasons.append(f'Brightness {bright:.1f} < {minb:.1f}')
    if bright>maxb: reasons.append(f'Brightness {bright:.1f} > {maxb:.1f}')
    if not cp: reasons.append(f'Contrast {contrast:.1f} < {minc:.1f}')
    return QualityResult(sharp,bright,contrast,sp,bp,cp,sp and bp and cp,reasons)
