from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_DIR_NAMES = {
    '.pytest_cache', '__pycache__', '.ruff_cache', '.mypy_cache',
    'htmlcov', 'build', 'dist'
}
FORBIDDEN_FILE_SUFFIXES = {'.pyc', '.pyo'}
FORBIDDEN_FILES = {'.coverage'}


def main() -> int:
    removed: list[str] = []

    # Remove deepest directories first so parent scans remain safe.
    dirs = [p for p in ROOT.rglob('*') if p.is_dir() and p.name in FORBIDDEN_DIR_NAMES]
    for p in sorted(dirs, key=lambda x: len(x.parts), reverse=True):
        if p.exists():
            removed.append(str(p.relative_to(ROOT)))
            shutil.rmtree(p, ignore_errors=False)

    # Remove generated files that can survive outside standard cache dirs.
    for p in list(ROOT.rglob('*')):
        if not p.is_file():
            continue
        if p.name in FORBIDDEN_FILES or p.suffix.lower() in FORBIDDEN_FILE_SUFFIXES:
            removed.append(str(p.relative_to(ROOT)))
            p.unlink(missing_ok=True)

    print(f'[WORKSPACE_CLEANUP][PASS] removed={len(removed)}')
    for rel in removed[:50]:
        print(f'  removed: {rel}')
    if len(removed) > 50:
        print(f'  ... and {len(removed)-50} more')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
