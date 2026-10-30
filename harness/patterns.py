"""Logical strength curves; physical output mapping belongs to the driver."""
import json
from pathlib import Path

PATTERNS = json.loads((Path(__file__).resolve().parents[1] / "contracts/patterns.json").read_text(encoding="utf-8"))


def segments(pattern, strength):
    result = []
    for item in PATTERNS[str(pattern)]["segments"]:
        ms, level = item
        result.append((ms, (strength * level + 50) // 100))
    return result


def duration(pattern, repeat=1):
    return sum(ms for ms, _ in PATTERNS[str(pattern)]["segments"]) * repeat + 200 * (repeat - 1)


def strength_at(pattern, strength, repeat, elapsed_ms):
    unit = segments(pattern, strength)
    for repetition in range(repeat):
        for ms, level in unit:
            if elapsed_ms < ms:
                return level
            elapsed_ms -= ms
        if repetition + 1 < repeat:
            if elapsed_ms < 200:
                return 0
            elapsed_ms -= 200
    return 0
