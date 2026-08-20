import unittest
from label_tool.core.zone_scheduler import ProgressiveZoneScheduler
from label_tool.core.smart_lock import SmartLockEngine

ZONES=[
    {"id":"A","title":"A","instruction":"A","items":["A1","A2"],"max_cycles":2},
    {"id":"B","title":"B","instruction":"B","items":["B1"],"max_cycles":2},
    {"id":"D","title":"D","instruction":"D","items":["D1"],"camera":False,"max_cycles":1},
]

class ZoneSchedulerTests(unittest.TestCase):
    def test_only_current_zone_items(self):
        locks=SmartLockEngine(["A1","A2","B1","D1"])
        z=ProgressiveZoneScheduler(ZONES)
        self.assertEqual(z.zone_unlocked_items(locks),["A1","A2"])

    def test_completed_zone_moves_next(self):
        locks=SmartLockEngine(["A1","A2","B1","D1"])
        z=ProgressiveZoneScheduler(ZONES)
        locks.force_lock("A1","x"); locks.force_lock("A2","x")
        z.after_cycle(locks)
        self.assertEqual(z.current.zone_id,"B")

    def test_stalled_zone_rotates(self):
        locks=SmartLockEngine(["A1","A2","B1","D1"])
        z=ProgressiveZoneScheduler(ZONES)
        z.after_cycle(locks)
        z.after_cycle(locks)
        self.assertEqual(z.current.zone_id,"B")

    def test_zone_d_is_camera_free(self):
        z=ProgressiveZoneScheduler(ZONES)
        z.index=2
        self.assertFalse(z.current.camera)

if __name__=="__main__":
    unittest.main()
