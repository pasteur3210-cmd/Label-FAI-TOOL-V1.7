from __future__ import annotations

import re


def normalize_serial(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper())


def normalize_mac(value: str) -> str:
    return re.sub(r"[:\-\s]", "", str(value or "").strip().upper())


def check_serial_range(value: str, start: str, end: str) -> tuple[bool | None, str]:
    """Return (ok, detail) for an inclusive production S/N range.

    Preferred path compares a shared-prefix trailing decimal sequence, which is
    the normal factory allocation form.  Fixed-width lexical comparison is a
    conservative fallback for other alphanumeric S/N formats.  ``None`` means
    configuration/data is insufficient and should be sent to Manual Review.
    """
    value = normalize_serial(value)
    start = normalize_serial(start)
    end = normalize_serial(end)
    if not value:
        return None, "S/N not recognized"
    if not start or not end:
        return None, "S/N range not configured"

    sm = re.fullmatch(r"(.*?)(\d+)", start)
    em = re.fullmatch(r"(.*?)(\d+)", end)
    vm = re.fullmatch(r"(.*?)(\d+)", value)
    if sm and em and vm and sm.group(1) == em.group(1):
        prefix = sm.group(1)
        if vm.group(1) != prefix:
            return False, f"S/N prefix mismatch; expected prefix {prefix}"
        if len(sm.group(2)) != len(em.group(2)) or len(vm.group(2)) != len(sm.group(2)):
            return False, "S/N sequence width does not match configured range"
        lo, hi, cur = int(sm.group(2)), int(em.group(2)), int(vm.group(2))
        if lo > hi:
            return None, "S/N Start is greater than S/N End"
        return lo <= cur <= hi, f"numeric sequence {cur} within {lo}..{hi}"

    if len(start) != len(end) or len(value) != len(start):
        return None, "S/N range format/length is inconsistent"
    if start > end:
        return None, "S/N Start is greater than S/N End"
    return start <= value <= end, "fixed-width alphanumeric comparison"


def check_mac_range(value: str, start: str, end: str) -> tuple[bool | None, str]:
    value = normalize_mac(value)
    start = normalize_mac(start)
    end = normalize_mac(end)
    if not value:
        return None, "MAC not recognized"
    if not start or not end:
        return None, "MAC range not configured"
    if not all(re.fullmatch(r"[0-9A-F]{12}", x or "") for x in (value, start, end)):
        return None, "MAC range must be 12 hexadecimal characters"
    cur, lo, hi = int(value, 16), int(start, 16), int(end, 16)
    if lo > hi:
        return None, "MAC Start is greater than MAC End"
    return lo <= cur <= hi, f"0x{cur:012X} within 0x{lo:012X}..0x{hi:012X}"


def check_mac_allocation(value: str, start: str, end: str, step: int) -> tuple[bool | None, str]:
    value = normalize_mac(value)
    start = normalize_mac(start)
    end = normalize_mac(end)
    try:
        step = int(step)
    except (TypeError, ValueError):
        return None, "MAC Qty/Step must be an integer"
    if step <= 0:
        return None, "MAC Qty/Step must be greater than 0"
    base_ok, detail = check_mac_range(value, start, end)
    if base_ok is not True:
        return base_ok, detail
    cur, lo, hi = int(value, 16), int(start, 16), int(end, 16)
    if (cur - lo) % step != 0:
        return False, f"Base MAC is not aligned to allocation step {step} from {start}"
    allocation_last = cur + step - 1
    if allocation_last > hi:
        return False, f"Allocation of {step} MACs exceeds end range at {allocation_last:012X}"
    return True, f"aligned step={step}; allocated {value}..{allocation_last:012X}"
