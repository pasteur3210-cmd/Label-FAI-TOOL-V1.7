import ast
from pathlib import Path
import unittest


class TestV191Python311Compatibility(unittest.TestCase):
    def test_golden_profile_manager_parses_with_python311_grammar(self):
        source = Path('label_tool/core/golden_profile_manager.py').read_text(encoding='utf-8')
        ast.parse(source, filename='golden_profile_manager.py', feature_version=(3, 11))

    def test_no_pep701_only_quote_pattern_in_doc_converter(self):
        source = Path('label_tool/core/golden_profile_manager.py').read_text(encoding='utf-8')
        self.assertIn('source_ps =', source)
        self.assertIn('output_ps =', source)
        self.assertNotIn('replace("\'", "\'\'")}\')', source)


if __name__ == '__main__':
    unittest.main()
