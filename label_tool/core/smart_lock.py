from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Iterable
import time


@dataclass
class ItemLock:
    state: str = "SCANNING"
    candidate: str = ""
    confirmations: int = 0
    candidate_last_seen: float = 0.0
    locked_value: str = ""
    fail_candidate: str = ""
    fail_confirmations: int = 0
    last_message: str = ""
    lock_source: str = ""
    lock_time: str = ""
    ignored_after_lock: int = 0


@dataclass
class SmartLockEngine:
    required_items: list[str]
    pass_confirmations: int = 2
    fail_confirmations: int = 3
    candidate_ttl_sec: float = 12.0
    fields: dict[str, ItemLock] = field(default_factory=dict)

    def __post_init__(self):
        self.reset(self.required_items)

    def reset(self, required_items: Iterable[str] | None = None):
        if required_items is not None:
            self.required_items = list(required_items)
        self.fields = {name: ItemLock() for name in self.required_items}

    def manual_unlock(self, name: str) -> bool:
        if name not in self.fields:
            return False
        self.fields[name] = ItemLock()
        return True

    def retry_items(self, names) -> int:
        """Reset only unfinished candidates for a manual Retry Zone action.

        Existing LOCK results are terminal and intentionally preserved.
        """
        count=0
        for name in names or []:
            if name in self.fields and not self.is_locked(name):
                self.fields[name]=ItemLock()
                count+=1
        return count

    def is_locked(self, name: str) -> bool:
        return name in self.fields and self.fields[name].state == "LOCK"

    def locked_value(self, name: str) -> str:
        return self.fields[name].locked_value if name in self.fields else ""

    def unlocked_items(self) -> list[str]:
        return [name for name in self.required_items if not self.is_locked(name)]

    def _candidate_expired(self, item: ItemLock, now: float) -> bool:
        return bool(item.candidate and item.candidate_last_seen and
                    (now - item.candidate_last_seen) > self.candidate_ttl_sec)

    def offer(self, name: str, value: str, result_status: str,
              message: str = "", source: str = "Camera") -> str:
        if name not in self.fields:
            return "NOT_REQUIRED"

        item = self.fields[name]

        # LOCK is terminal.
        if item.state == "LOCK":
            item.ignored_after_lock += 1
            return "LOCK"

        item.last_message = message or ""
        value = (value or "").strip()
        now = time.time()

        # Expire an old half-confirmed candidate only after TTL.
        if self._candidate_expired(item, now):
            item.candidate = ""
            item.confirmations = 0
            item.candidate_last_seen = 0.0
            if item.state == "VERIFY":
                item.state = "SCANNING"

        if result_status == "PASS" and value:
            item.fail_candidate = ""
            item.fail_confirmations = 0

            if value == item.candidate:
                item.confirmations += 1
            else:
                # Only a NEW VALID PASS value replaces the previous candidate.
                item.candidate = value
                item.confirmations = 1
            item.candidate_last_seen = now
            item.state = "VERIFY"

            if item.confirmations >= self.pass_confirmations:
                item.state = "LOCK"
                item.locked_value = value
                item.lock_source = source
                item.lock_time = datetime.now().isoformat(timespec="seconds")
            return item.state

        # V1.2.0 IMPORTANT:
        # unreadable / blur / missing result DOES NOT erase PASS 1/2.
        if result_status in ("WARN", "SKIP", "INFO") or not value:
            if item.candidate and item.confirmations > 0:
                item.state = "VERIFY"
            else:
                item.state = "SCANNING"
            return item.state

        # Invalid OCR data / rule fail:
        # keep an existing valid PASS candidate; independently count stable fail.
        if result_status == "FAIL":
            if value == item.fail_candidate:
                item.fail_confirmations += 1
            else:
                item.fail_candidate = value
                item.fail_confirmations = 1

            if item.fail_confirmations >= self.fail_confirmations:
                item.state = "CONFIRMED_FAIL"
            elif item.candidate and item.confirmations > 0:
                item.state = "VERIFY"
            else:
                item.state = "VERIFY_FAIL"
            return item.state

        return item.state

    def force_lock(self, name: str, value: str, source: str = "HID Scanner") -> str:
        if name not in self.fields:
            return "NOT_REQUIRED"
        item = self.fields[name]
        if item.state == "LOCK":
            item.ignored_after_lock += 1
            return "LOCK"
        value = (value or "").strip()
        if not value:
            return item.state
        item.state = "LOCK"
        item.candidate = value
        item.confirmations = self.pass_confirmations
        item.candidate_last_seen = time.time()
        item.locked_value = value
        item.lock_source = source
        item.lock_time = datetime.now().isoformat(timespec="seconds")
        item.fail_candidate = ""
        item.fail_confirmations = 0
        return "LOCK"

    def status_text(self, name: str) -> str:
        item = self.fields[name]
        if item.state == "VERIFY":
            return f"PASS {item.confirmations}/{self.pass_confirmations}"
        if item.state == "VERIFY_FAIL":
            return f"FAIL? {item.fail_confirmations}/{self.fail_confirmations}"
        if item.state == "LOCK":
            return "LOCK"
        return item.state

    def locked_count(self) -> int:
        return sum(1 for n in self.required_items if self.is_locked(n))

    def all_locked(self) -> bool:
        return bool(self.required_items) and self.locked_count() == len(self.required_items)

    def confirmed_fail_items(self) -> list[str]:
        return [n for n, v in self.fields.items() if v.state == "CONFIRMED_FAIL"]

    def snapshot(self):
        return {k: asdict(v) for k, v in self.fields.items()}


class IdentityGuard:
    def __init__(self, confirmations: int = 3):
        self.confirmations = confirmations
        self.current = ""
        self.candidate = ""
        self.count = 0

    def reset(self, current: str = ""):
        self.current = current or ""
        self.candidate = ""
        self.count = 0

    def set_current(self, value: str):
        if value:
            self.current = value
            self.candidate = ""
            self.count = 0

    def offer(self, value: str) -> bool:
        value = (value or "").strip().upper()
        if not value or not self.current or value == self.current.upper():
            self.candidate = ""
            self.count = 0
            return False
        if value == self.candidate:
            self.count += 1
        else:
            self.candidate = value
            self.count = 1
        return self.count >= self.confirmations
