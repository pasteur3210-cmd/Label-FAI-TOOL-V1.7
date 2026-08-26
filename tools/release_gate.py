from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = '1.9.5'
REQUIRED = [
    '.github/workflows/build.yml',
    'label_tool/__init__.py',
    'label_tool/app.py',
    'label_tool/core/golden_profile_manager.py',
    'requirements.txt',
    'build.spec',
    'build.bat',
    'run.py',
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
        fail('V1.9.5 clean Dynamic Golden engine-template boundary is missing')
    if 'profile=deepcopy(base_profile)' in gp.replace(' ', ''):
        fail('Dynamic Golden still directly deep-copies a model-specific seed profile')
    if 'apply_editable_items' not in gp or '_dynamic_item_rows' not in gp:
        fail('Visual Profile Editor data model is missing')

    if 'extract_golden_form_items' not in gp or 'golden_completeness' not in gp:
        fail('V1.9.5 numbered Golden completeness parser is missing')
    if 'STANDARD_LIBRARY' not in gp or 'validation_readiness_errors' not in gp:
        fail('V1.9.5 Standard Library / validation readiness gate is missing')
    if '_show_manual_golden_review' not in app or 'Golden Reference / Golden 對照' not in app:
        fail('V1.9.5 Golden-assisted Manual Review UI is missing')

    print(f'[RELEASE_GATE][PASS] version={EXPECTED_VERSION} python311_files={parsed} required_files={len(REQUIRED)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
