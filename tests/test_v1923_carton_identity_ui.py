from pathlib import Path
import unittest

from label_tool.core.golden_profile_manager import (
    _candidate_label_pn, _candidate_label_type, canonical_profile_identity,
)


CARTON_FORM_TEXT = """
Carton Label Request Form
PAK Name: GRG-4297u-TSL-P1
3. Model: GRG-4297u
Finished Information:
1. Blank Label Part Number: 502109-020
2. Carton Label Part Number: 680010-354
"""


class V1923CartonIdentityUI(unittest.TestCase):
    def test_carton_finished_pn_wins_over_blank_stock(self):
        self.assertEqual(_candidate_label_pn(CARTON_FORM_TEXT), '680010-354')

    def test_carton_label_type_is_detected(self):
        self.assertEqual(_candidate_label_type('GRG-4297u carton.doc', CARTON_FORM_TEXT), 'Carton Label')

    def test_model_and_label_type_are_separate(self):
        identity=canonical_profile_identity('GRG-4297u Carton', 'Carton Label', '680010-354')
        self.assertEqual(identity['model'], 'GRG-4297u')
        self.assertEqual(identity['label_type'], 'Carton Label')
        self.assertEqual(identity['label_pn'], '680010-354')
        self.assertEqual(identity['display_name'], 'GRG-4297u Carton Label')

    def test_operator_ui_hierarchy_and_compact_result_area_present(self):
        app=(Path(__file__).resolve().parents[1]/'label_tool/app.py').read_text(encoding='utf-8')
        for token in (
            "font=('Segoe UI',19,'bold')",
            "ACTUAL / 實拍：",
            "EXPECTED / Golden：",
            "font=('Segoe UI',16,'bold')",
            "font=('Segoe UI',14,'bold')",
            'height=2,exportselection=False',
            'height=8)',
        ):
            self.assertIn(token, app)

    def test_release_artifact_name_is_short(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/build.yml').read_text(encoding='utf-8')
        self.assertIn('name: Label_Inspection_Tool_V1.9.23', workflow)
        self.assertNotIn('Performance_Dynamic_Golden_Profile_Windows', workflow)


if __name__ == '__main__':
    unittest.main()
