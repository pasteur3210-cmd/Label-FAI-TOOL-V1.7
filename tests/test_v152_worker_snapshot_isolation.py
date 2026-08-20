import unittest
from pathlib import Path
import json,re

class V152WorkerSnapshotIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src=Path("label_tool/app.py").read_text(encoding="utf-8")

    def method(self,name):
        s=self.src.index(f"    def {name}(")
        e=self.src.find("\n    def ",s+5)
        return self.src[s:] if e<0 else self.src[s:e]

    def test_guided_worker_has_no_expected_tk_read(self):
        body=self.method("_guided_worker")
        self.assertNotIn("self._expected(",body)
        self.assertIn("expected_snapshot",body)

    def test_schedule_builds_snapshot_before_thread(self):
        body=self.method("_schedule_live")
        build=body.index("_build_worker_snapshot(target)")
        launch=body.index("threading.Thread(target=self._guided_worker", build)
        self.assertLess(build,launch)

    def test_worker_snapshot_builder_is_main_thread_boundary(self):
        body=self.method("_build_worker_snapshot")
        self.assertIn("dict(self._expected())",body)
        self.assertIn("dict(self._locked_known_fields())",body)
        self.assertIn('"item": str(target.item)',body)

    def test_background_workers_forbid_tk_patterns(self):
        prohibited=[
            "self.after(","self._expected(",".winfo_","messagebox.",
            ".config(",".configure(","self.update(","self.update_idletasks("
        ]
        for name in ["_guided_worker","_machine_worker","_ocr_preflight_worker"]:
            body=self.method(name)
            for token in prohibited:
                self.assertNotIn(token,body,msg=f"{name}: forbidden {token}")
            self.assertIsNone(
                re.search(r"self\.[A-Za-z_][A-Za-z0-9_]*\.get\(",body),
                msg=f"{name}: forbidden self.<attr>.get()"
            )

    def test_trace_chain_present(self):
        for token in ["WORKER_SNAPSHOT","OCR_CALL_END","QUEUE_PUT","QUEUE_GET","RULE_EVAL","SMART_LOCK_RESULT"]:
            self.assertIn(token,self.src)

    def test_profile_declares_isolation(self):
        d=json.loads(Path("label_tool/profiles/grg4297u_tsl_p1.json").read_text(encoding="utf-8"))
        self.assertTrue(d["live"]["worker_snapshot_isolation"])
        self.assertFalse(d["live"]["tk_calls_allowed_from_worker"])

if __name__=="__main__":
    unittest.main()
