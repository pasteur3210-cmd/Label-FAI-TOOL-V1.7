import unittest
from label_tool.core.smart_lock import SmartLockEngine, IdentityGuard

class SmartLockTests(unittest.TestCase):
    def test_two_same_pass_locks(self):
        s=SmartLockEngine(['A'],2,3)
        self.assertEqual(s.offer('A','VALUE','PASS'),'VERIFY')
        self.assertEqual(s.offer('A','VALUE','PASS'),'LOCK')
        self.assertTrue(s.all_locked())

    def test_different_pass_resets_counter(self):
        s=SmartLockEngine(['A'],2,3)
        s.offer('A','A','PASS')
        s.offer('A','B','PASS')
        self.assertEqual(s.fields['A'].confirmations,1)
        self.assertFalse(s.is_locked('A'))

    def test_warn_does_not_fail(self):
        s=SmartLockEngine(['A'],2,3)
        self.assertEqual(s.offer('A','','WARN'),'SCANNING')
        self.assertFalse(s.confirmed_fail_items())

    def test_three_same_fail_confirms(self):
        s=SmartLockEngine(['A'],2,3)
        s.offer('A','BAD','FAIL')
        s.offer('A','BAD','FAIL')
        self.assertEqual(s.offer('A','BAD','FAIL'),'CONFIRMED_FAIL')

    def test_locked_value_not_overwritten_by_fail(self):
        s=SmartLockEngine(['A'],2,3)
        s.offer('A','GOOD','PASS')
        s.offer('A','GOOD','PASS')
        s.offer('A','BAD','FAIL')
        self.assertEqual(s.locked_value('A'),'GOOD')
        self.assertEqual(s.status_text('A'),'LOCK')

    def test_locked_value_not_overwritten_by_warn(self):
        s=SmartLockEngine(['A'],2,3)
        s.offer('A','GOOD','PASS')
        s.offer('A','GOOD','PASS')
        s.offer('A','','WARN')
        self.assertTrue(s.is_locked('A'))
        self.assertEqual(s.locked_value('A'),'GOOD')

    def test_locked_value_not_overwritten_by_new_pass(self):
        s=SmartLockEngine(['A'],2,3)
        s.offer('A','GOOD','PASS')
        s.offer('A','GOOD','PASS')
        s.offer('A','OTHER','PASS')
        s.offer('A','OTHER','PASS')
        self.assertTrue(s.is_locked('A'))
        self.assertEqual(s.locked_value('A'),'GOOD')

    def test_manual_unlock_only_explicitly_clears(self):
        s=SmartLockEngine(['A'],2,3)
        s.force_lock('A','GOOD')
        self.assertTrue(s.is_locked('A'))
        self.assertTrue(s.manual_unlock('A'))
        self.assertFalse(s.is_locked('A'))

    def test_force_lock_never_overwrites_existing_lock(self):
        s=SmartLockEngine(['A'],2,3)
        s.force_lock('A','GOOD','HID')
        s.force_lock('A','OTHER','HID')
        self.assertEqual(s.locked_value('A'),'GOOD')

    def test_unlocked_items_excludes_lock(self):
        s=SmartLockEngine(['A','B'],2,3)
        s.force_lock('A','X')
        self.assertEqual(s.unlocked_items(),['B'])

    def test_identity_guard_requires_stable_new_sn(self):
        g=IdentityGuard(3)
        g.set_current('SN001')
        self.assertFalse(g.offer('SN002'))
        self.assertFalse(g.offer('SN002'))
        self.assertTrue(g.offer('SN002'))

    def test_warn_preserves_pass_candidate(self):
        s=SmartLockEngine(['A'],2,3,12)
        self.assertEqual(s.offer('A','GOOD','PASS'),'VERIFY')
        self.assertEqual(s.offer('A','','WARN'),'VERIFY')
        self.assertEqual(s.fields['A'].confirmations,1)
        self.assertEqual(s.offer('A','GOOD','PASS'),'LOCK')

    def test_different_valid_pass_restarts_candidate(self):
        s=SmartLockEngine(['A'],2,3,12)
        s.offer('A','GOOD1','PASS')
        s.offer('A','','WARN')
        s.offer('A','GOOD2','PASS')
        self.assertEqual(s.fields['A'].candidate,'GOOD2')
        self.assertEqual(s.fields['A'].confirmations,1)

if __name__=='__main__':
    unittest.main()
