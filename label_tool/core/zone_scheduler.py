from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Zone:
    zone_id: str
    title: str
    instruction: str
    items: list[str]
    camera: bool = True
    max_cycles: int = 3
    guide_rect: list[float] = field(default_factory=lambda: [0.12, 0.18, 0.88, 0.82])


class ProgressiveZoneScheduler:
    """Progressive zone scan.

    - Only items in the CURRENT zone are sent to recognition.
    - A zone advances immediately when all its required items are LOCKED.
    - If progress stalls, rotate after max_cycles so one difficult item cannot block the unit.
    - Zone D may be camera=False for pure rule/cross-check evaluation.
    """
    def __init__(self, zone_dicts):
        self.zones = [Zone(
            zone_id=z["id"],
            title=z["title"],
            instruction=z["instruction"],
            items=list(z.get("items", [])),
            camera=bool(z.get("camera", True)),
            max_cycles=int(z.get("max_cycles", 3)),
            guide_rect=list(z.get("guide_rect", [0.12,0.18,0.88,0.82])),
        ) for z in zone_dicts]
        self.index = 0
        self.cycles_in_zone = 0
        self.last_locked_count = 0
        self.stall_cycles = 0

    def reset(self):
        self.index = 0
        self.cycles_in_zone = 0
        self.last_locked_count = 0
        self.stall_cycles = 0

    @property
    def current(self):
        return self.zones[self.index] if self.zones else None

    def zone_unlocked_items(self, locks):
        z = self.current
        if not z:
            return []
        return [x for x in z.items if x in locks.fields and not locks.is_locked(x)]

    def zone_complete(self, locks):
        z = self.current
        if not z:
            return True
        required = [x for x in z.items if x in locks.fields]
        return bool(required) and all(locks.is_locked(x) for x in required)

    def next_zone(self):
        if not self.zones:
            return None
        self.index = (self.index + 1) % len(self.zones)
        self.cycles_in_zone = 0
        self.stall_cycles = 0
        return self.current

    def previous_zone(self):
        if not self.zones:
            return None
        self.index = (self.index - 1) % len(self.zones)
        self.cycles_in_zone = 0
        self.stall_cycles = 0
        return self.current

    def retry_zone(self):
        self.cycles_in_zone = 0
        self.stall_cycles = 0
        return self.current

    def select_next_incomplete(self, locks):
        if not self.zones:
            return None
        for _ in range(len(self.zones)):
            z = self.current
            if not self.zone_complete(locks):
                return z
            self.next_zone()
        return self.current

    def after_cycle(self, locks):
        """Return True if scheduler changed zone."""
        if not self.zones:
            return False

        before = self.index
        self.cycles_in_zone += 1
        locked = locks.locked_count()

        if locked > self.last_locked_count:
            self.stall_cycles = 0
        else:
            self.stall_cycles += 1
        self.last_locked_count = locked

        if self.zone_complete(locks):
            self.next_zone()
            self.select_next_incomplete(locks)
        elif self.cycles_in_zone >= self.current.max_cycles or self.stall_cycles >= self.current.max_cycles:
            self.next_zone()
            self.select_next_incomplete(locks)

        return before != self.index
