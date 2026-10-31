"""UUIDv7 identifiers (PLAN Section 16: time-ordered primary keys).

Python 3.12 has no uuid.uuid7. Within one process the ids are strictly increasing:
the 12-bit rand_a field counts up inside a millisecond and the timestamp moves on
when it would overflow.
"""

import secrets
import threading
import time
from uuid import UUID

_lock = threading.Lock()
_last = (0, 0)  # (milliseconds, rand_a)


def uuid7() -> UUID:
    global _last
    with _lock:
        now = time.time_ns() // 1_000_000
        last_ms, last_counter = _last
        if now > last_ms:
            milliseconds, counter = now, secrets.randbits(11)
        elif last_counter < 0xFFF:
            milliseconds, counter = last_ms, last_counter + 1
        else:
            milliseconds, counter = last_ms + 1, secrets.randbits(11)
        _last = (milliseconds, counter)
    bits = (milliseconds << 80) | (7 << 76) | (counter << 64)
    bits |= (2 << 62) | secrets.randbits(62)
    return UUID(int=bits)
