from pathlib import Path
import subprocess, sys

ROOT = Path(__file__).resolve().parents[1]

def test_integration_gate_passes():
    p = subprocess.run([sys.executable, str(ROOT/'tools'/'integration_gate.py')], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert '[INTEGRATION_GATE][PASS]' in p.stdout

def test_manual_review_button_is_explicitly_golden_assisted():
    src=(ROOT/'label_tool'/'app.py').read_text(encoding='utf-8')
    assert 'Review with Golden / Golden對照復判' in src
    assert 'Confirm PASS / 人工確認PASS' in src
