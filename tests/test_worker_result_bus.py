import unittest
import threading
from label_tool.core.worker_bus import WorkerResultBus, WorkerEvent

class WorkerResultBusTests(unittest.TestCase):
    def test_put_drain_round_trip(self):
        bus=WorkerResultBus(maxsize=4)
        self.assertTrue(bus.put(WorkerEvent("guided_result",payload=123,cycle_id=7,item="X")))
        events=bus.drain()
        self.assertEqual(len(events),1)
        self.assertEqual(events[0].kind,"guided_result")
        self.assertEqual(events[0].payload,123)
        self.assertEqual(events[0].cycle_id,7)

    def test_worker_thread_can_put(self):
        bus=WorkerResultBus(maxsize=4)
        def worker():
            bus.put(WorkerEvent("machine_result",payload="OK"))
        t=threading.Thread(target=worker)
        t.start(); t.join(timeout=2)
        self.assertFalse(t.is_alive())
        self.assertEqual(bus.drain()[0].payload,"OK")

    def test_full_queue_drops_without_blocking(self):
        bus=WorkerResultBus(maxsize=1)
        self.assertTrue(bus.put(WorkerEvent("a")))
        self.assertFalse(bus.put(WorkerEvent("b")))
        self.assertEqual(bus.dropped,1)

if __name__=="__main__":
    unittest.main()
