import unittest
from label_tool.core.production_zone_ocr import ProductionZone, ProductionZoneScheduler
from label_tool.core.smart_lock import SmartLockEngine


class V174ManualZoneNavigationTests(unittest.TestCase):
    def setUp(self):
        self.zones=[
            ProductionZone('A','A','A',[0,0,1,1],['a']),
            ProductionZone('B','B','B',[0,0,1,1],['b']),
            ProductionZone('C','C','C',[0,0,1,1],['c']),
        ]
        self.s=ProductionZoneScheduler(self.zones)
        self.l=SmartLockEngine(['a','b','c'], pass_confirmations=1)
        self.l.force_lock('a','ok')
        self.l.force_lock('b','ok')

    def test_auto_selects_incomplete_c(self):
        self.assertEqual(self.s.current_for_display(self.l).id,'C')

    def test_previous_holds_completed_b(self):
        self.s.current_for_display(self.l)  # move auto pointer to C
        self.assertEqual(self.s.previous().id,'B')
        self.assertTrue(self.s.manual_hold)
        for _ in range(5):
            self.assertEqual(self.s.current_for_display(self.l).id,'B')

    def test_next_is_literal_not_next_incomplete(self):
        self.s.current_for_display(self.l)  # C
        self.s.previous()                  # B
        self.assertEqual(self.s.next(self.l).id,'C')

    def test_resume_auto_returns_to_incomplete(self):
        self.s.current_for_display(self.l)
        self.s.previous()  # hold B
        self.s.resume_auto()
        self.assertEqual(self.s.current_for_display(self.l).id,'C')

    def test_retry_resets_unfinished_but_preserves_locks(self):
        self.s.current_for_display(self.l)
        # C is incomplete; create a half-confirmed candidate.
        self.l.pass_confirmations=2
        self.l.offer('c','candidate','PASS')
        self.assertEqual(self.l.fields['c'].confirmations,1)
        self.s.retry()
        reset=self.l.retry_items(self.s.effective_items(self.s.current,self.l))
        self.assertEqual(reset,1)
        self.assertEqual(self.l.fields['c'].confirmations,0)
        self.assertTrue(self.l.is_locked('a'))
        self.assertTrue(self.l.is_locked('b'))


if __name__ == '__main__':
    unittest.main()
