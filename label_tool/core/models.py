from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
@dataclass
class QualityResult:
    sharpness: float; brightness: float; contrast: float
    sharpness_pass: bool; brightness_pass: bool; contrast_pass: bool; passed: bool
    reasons: List[str]=field(default_factory=list)
@dataclass
class DecodeItem:
    format: str; text: str; points: Optional[List[Tuple[int,int]]]=None
@dataclass
class FieldResult:
    name: str; actual: str=''; expected: str=''; status: str='INFO'; message: str=''; error_code: str=''
@dataclass
class InspectionResult:
    overall: str='IMAGE_NG'; quality: Optional[QualityResult]=None; fields: List[FieldResult]=field(default_factory=list)
    decoded: List[DecodeItem]=field(default_factory=list); ocr_text: str=''; error_codes: List[str]=field(default_factory=list)
    corrected_image_path: str=''; marked_image_path: str=''; debug_dir: str=''; metadata: Dict[str,str]=field(default_factory=dict)
