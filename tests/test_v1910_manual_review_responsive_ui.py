from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'label_tool' / 'app.py'


def _src():
    return APP.read_text(encoding='utf-8')


def test_manual_review_popup_is_screen_responsive_not_fixed_790_height():
    s=_src()
    assert "win.geometry('1320x790')" not in s
    assert 'SystemParametersInfoW(0x0030' in s
    assert 'target_h=min(920, max(560, work_h-40))' in s
    assert "win.geometry(f'{target_w}x{target_h}+{x}+{y}')" in s


def test_manual_review_actions_are_above_comparison_body():
    s=_src()
    fn=s[s.index('    def _show_manual_golden_review'):s.index('    def manual_review_selected')]
    assert fn.index("actions=ttk.Frame(win") < fn.index("body=ttk.Frame(win")
    assert "pass_btn=ttk.Button(actions,text='Confirm PASS / 人工確認PASS'" in fn


def test_confirm_pass_is_visible_and_not_disabled_for_nonpass_items():
    s=_src()
    fn=s[s.index('    def _show_manual_golden_review'):s.index('    def manual_review_selected')]
    assert "Confirm PASS / 人工確認PASS" in fn
    assert "pass_btn.config(state='disabled')" not in fn
    # Do not regress to hiding the PASS button entirely for REVIEW_ONLY.
    assert "if mode=='OVERRIDE_ALLOWED':\n            ttk.Button" not in fn
