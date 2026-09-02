from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = '1.9.20'
REQUIRED = [
    '.github/workflows/build.yml',
    'label_tool/__init__.py',
    'label_tool/app.py',
    'label_tool/core/golden_profile_manager.py',
    'label_tool/core/production_range.py',
    'requirements.txt',
    'build.spec',
    'build.bat',
    'run.py',
    'tools/integration_gate.py',
]
FORBIDDEN_DIR_NAMES = {'.pytest_cache', '__pycache__', '.ruff_cache', '.mypy_cache', 'htmlcov', 'build', 'dist'}
FORBIDDEN_FILE_SUFFIXES = {'.pyc', '.pyo'}
FORBIDDEN_FILES = {'.coverage'}


def fail(msg: str) -> None:
    print(f'[RELEASE_GATE][FAIL] {msg}')
    raise SystemExit(1)


def main() -> int:
    for rel in REQUIRED:
        if not (ROOT / rel).exists():
            fail(f'Missing required release file: {rel}')

    version_text=(ROOT/'label_tool/__init__.py').read_text(encoding='utf-8')
    m=re.search(r'__version__\s*=\s*["\']([^"\']+)',version_text)
    if not m or m.group(1) != EXPECTED_VERSION:
        fail(f'Application version must be {EXPECTED_VERSION}; found {m.group(1) if m else "missing"}')

    workflow=(ROOT/'.github/workflows/build.yml').read_text(encoding='utf-8')
    if f'V{EXPECTED_VERSION}' not in workflow:
        fail(f'GitHub workflow does not contain V{EXPECTED_VERSION}')

    bad=[]
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if any(part in FORBIDDEN_DIR_NAMES for part in rel.parts):
            bad.append(str(rel)); continue
        if p.is_file() and (p.name in FORBIDDEN_FILES or p.suffix.lower() in FORBIDDEN_FILE_SUFFIXES):
            bad.append(str(rel))
    if bad:
        fail('Forbidden generated/cache artifacts present: ' + ', '.join(sorted(set(bad))[:30]))

    parsed=0
    for folder in ('label_tool','tests','tools'):
        for p in (ROOT/folder).rglob('*.py'):
            try:
                ast.parse(p.read_text(encoding='utf-8'),filename=str(p),feature_version=(3,11))
                parsed += 1
            except Exception as exc:
                fail(f'Python 3.11 grammar failure in {p.relative_to(ROOT)}: {exc}')

    gp=(ROOT/'label_tool/core/golden_profile_manager.py').read_text(encoding='utf-8')
    app=(ROOT/'label_tool/app.py').read_text(encoding='utf-8')
    if 'suggested=f"{base.get(' in app:
        fail('Legacy seed-model Dynamic Profile name logic is still present')
    if "source_ps =" not in gp or "output_ps =" not in gp:
        fail('Python 3.11-safe legacy DOC conversion guard is missing')
    if 'dynamic_identity_errors' not in gp or 'profile_identity' not in gp:
        fail('Dynamic Golden identity consistency gate is missing')
    if '_clean_engine_template(base_profile)' not in gp:
        fail('V1.9.20 clean Dynamic Golden engine-template boundary is missing')
    if 'profile=deepcopy(base_profile)' in gp.replace(' ', ''):
        fail('Dynamic Golden still directly deep-copies a model-specific seed profile')
    if 'apply_editable_items' not in gp or '_dynamic_item_rows' not in gp:
        fail('Visual Profile Editor data model is missing')

    if 'extract_golden_form_items' not in gp or 'golden_completeness' not in gp:
        fail('V1.9.20 numbered Golden completeness parser is missing')
    if 'STANDARD_LIBRARY' not in gp or 'validation_readiness_errors' not in gp:
        fail('V1.9.20 Standard Library / validation readiness gate is missing')
    if '_show_manual_golden_review' not in app or 'Golden Reference / Golden 對照' not in app:
        fail('V1.9.20 Golden-assisted Manual Review UI is missing')
    if 'Review with Golden / Golden對照復判' not in app:
        fail('V1.9.20 Manual Review button does not visibly expose Golden comparison')
    if '_golden_review_artwork_marker' not in app or 'showing full Golden' not in app or 'artwork_review_roi' not in app:
        fail('V1.9.20 strict Artwork Golden-reference safety/marker rule is missing')
    if 'Full Golden / 完整Golden' not in app or 'Focus Item / 項目放大' not in app:
        fail('V1.9.20 Manual Review full-Golden/default + optional-focus controls are missing')
    if "render_golden(None,'Final Label / Full Golden reference',golden_crop)" not in app:
        fail('V1.9.20 Manual Review does not default to the complete Golden image with current-item highlight')
    if 'REVIEW: {item}' not in app or 'golden_focus_allowed=bool(golden_crop)' not in app:
        fail('V1.9.20 Golden current-item highlight / safe Focus policy is missing')
    if 'Golden Item Specification / Golden 項目說明' not in app or '_golden_item_specification' not in app:
        fail('V1.9.20 item-specific Golden specification panel is missing')
    if 'select_final_label_image' not in gp or 'candidate_layout_policy' not in gp:
        fail('V1.9.20 final-label image selection guard is missing')
    if 'FINAL Label image' not in app or 'support screenshot' not in app:
        fail('V1.9.20 manual review is not isolated from support screenshots')
    if 'golden_item_bindings' not in gp or '_build_golden_item_bindings' not in gp:
        fail('V1.9.20 deterministic inspection-item -> Request-Form binding is missing')
    if 'Numbered Request Form exists => allow only deterministic' not in app:
        fail('V1.9.20 numbered Golden reference still permits fuzzy cross-item lookup')
    if 'urn:schemas-microsoft-com:vml' not in gp or 'imagedata' not in gp:
        fail('V1.9.20 legacy DOC/VML Final Label structural detection is missing')
    if 'final_label_image' not in gp or "gi.get('final_label_image'" not in app:
        fail('V1.9.20 exact persisted Final Label reference is missing')
    if 'normalize_dynamic_profile_for_runtime' not in gp or 'AUTO_RUNTIME_PROFILE_MIGRATION_V1916' not in app:
        fail('V1.9.20 stale external Dynamic Profile migration is missing')
    if 'validation_readiness_summary' not in gp or 'MANUAL review' not in app:
        fail('V1.9.20 Validate does not accept MANUAL as a first-class handling path')


    pm=(ROOT/'label_tool/core/profile_manager.py').read_text(encoding='utf-8')
    parser=(ROOT/'label_tool/core/parser.py').read_text(encoding='utf-8')
    if '_display_name' not in pm or 'label_pn' not in pm:
        fail('V1.9.20 unique Dynamic Profile UI key guard is missing')
    if '_parse_ocr_fields_dynamic' not in parser or 'profile=self.profile' not in (ROOT/'label_tool/core/multi_image_inspection.py').read_text(encoding='utf-8'):
        fail('V1.9.20 profile-aware Dynamic Image parser is missing')
    if 'qr_payload_fields' not in gp or 'ssid_mac_suffix_length' not in gp:
        fail('V1.9.20 Golden runtime rule extraction is missing')
    if 'password_length' not in gp or 'Password\\s*:' not in gp:
        fail('V1.9.20 Golden Password length rule extraction is missing')

    mi=(ROOT/'label_tool/core/multi_image_inspection.py').read_text(encoding='utf-8')
    if 'manual_attention_mode' not in mi or 'manual_reviews' not in mi:
        fail('V1.9.20 all-non-PASS operator-attention/traceability model is missing')
    if 'return bool(str(item or "").strip())' not in mi:
        fail('V1.9.20 every non-PASS item must have a traceable manual PASS path')
    if 'mode=self.multi_image_engine.manual_attention_mode(item)' not in app or 'Confirm PASS / 人工確認PASS' not in app:
        fail('V1.9.20 Manual Review does not expose traceable Confirm PASS for non-PASS items')
    if 'IMAGE_SESSION_INVALIDATED' not in app:
        fail('V1.9.20 profile/Golden change does not invalidate previous Image result')
    if '__incoming_' not in gp or 'backup=root.parent' not in gp:
        fail('V1.9.20 transactional Golden asset replacement guard is missing')
    if '_apply_chassis_scope_filter' not in gp or 'CHASSIS_SHIPPED_LABEL_ONLY' not in gp:
        fail('V1.9.20 CMP-001 shipped Chassis scope filter is missing')
    if '_extract_notch_direction' not in gp or 'Geometry: Label Notch Direction' not in gp:
        fail('V1.9.20 CMP-008 Request-Form notch direction rule is missing')
    if 'detect_label_notch_direction' not in mi or 'GEO-NOTCH-VERIFY' not in mi:
        fail('V1.9.20 CMP-008 runtime notch detector/manual fallback is missing')
    production=(ROOT/'label_tool/core/production_range.py').read_text(encoding='utf-8')
    if 'check_serial_range' not in production or 'check_mac_range' not in production or 'check_mac_allocation' not in production:
        fail('V1.9.20 production S/N/MAC range/allocation engine is missing')
    if 'Check S/N Range' not in app or 'Check MAC Range' not in app or 'Check MAC Allocation Step' not in app:
        fail('V1.9.20 production range GUI controls are missing')
    rules=(ROOT/'label_tool/core/rules.py').read_text(encoding='utf-8')
    for token in ('Work Order: S/N Range','Work Order: MAC Range','Work Order: MAC Allocation Step'):
        if token not in rules:
            fail(f'V1.9.20 production rule missing: {token}')
    if 'DERIVED_RULE_FAIL' not in app:
        fail('V1.9.20 CAM production-range FAIL path is missing')

    print(f'[RELEASE_GATE][PASS] version={EXPECTED_VERSION} python311_files={parsed} required_files={len(REQUIRED)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
