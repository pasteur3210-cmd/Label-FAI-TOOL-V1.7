import unittest
from pathlib import Path
import ast, json

class V151ThreadTransportTests(unittest.TestCase):
    def setUp(self):
        self.src=Path("label_tool/app.py").read_text(encoding="utf-8")
        self.tree=ast.parse(self.src)

    def _method_source(self,name):
        start=self.src.index(f"    def {name}(")
        nxt=self.src.find("\n    def ",start+5)
        return self.src[start:] if nxt<0 else self.src[start:nxt]

    def test_guided_worker_contains_no_tk_after(self):
        body=self._method_source("_guided_worker")
        self.assertNotIn("self.after(",body)
        self.assertNotIn(".config(",body)
        self.assertIn("WorkerEvent(",body)
        self.assertIn("guided_result",body)

    def test_machine_worker_contains_no_tk_after(self):
        body=self._method_source("_machine_worker")
        self.assertNotIn("self.after(",body)
        self.assertNotIn(".config(",body)
        self.assertIn("machine_result",body)

    def test_preflight_worker_contains_no_tk_after(self):
        body=self._method_source("_ocr_preflight_worker")
        self.assertNotIn("self.after(",body)
        self.assertIn("ocr_preflight_ok",body)

    def test_main_thread_poller_handles_guided_and_machine(self):
        poller=self._method_source("_poll_worker_results")
        dispatch=self._method_source("_dispatch_worker_event")
        self.assertIn("_dispatch_worker_event",poller)
        self.assertIn("_merge_guided_result",dispatch)
        self.assertIn("_merge_machine_result",dispatch)
        self.assertIn("_ocr_preflight_done",dispatch)
        self.assertIn("self.after(",poller)

    def test_end_to_end_trace_strings_present(self):
        for token in ["QUEUE_PUT","QUEUE_GET","RULE_EVAL","SMART_LOCK_RESULT"]:
            self.assertIn(token,self.src)

    def test_profile_declares_queue_transport(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertEqual(d["live"]["worker_result_transport"],"thread_safe_queue")
        self.assertFalse(d["live"]["tk_calls_allowed_from_worker"])

if __name__=="__main__":
    unittest.main()
