import unittest, json
from pathlib import Path

class LiveProfileTests(unittest.TestCase):
    def test_required_live_items(self):
        d=json.loads(Path('label_tool/profiles/grg4297u_tsl_p1.json').read_text(encoding='utf-8'))
        self.assertEqual(d['profile_version'],'1.7.9.1')
        self.assertGreaterEqual(len(d['live']['required_items']),25)
        self.assertEqual(d['live']['pass_confirmations'],2)
        self.assertEqual(d['live']['fail_confirmations'],3)

if __name__=='__main__': unittest.main()
