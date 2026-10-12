"""Stream impairments: publish delay, sensor drift and dropouts.

Day 8 fills these in. In v1 every hook is a no-op, but the generator already
calls them at the right places, so Day 8 only changes this module.
"""

from __future__ import annotations


class Impairments:
    """No-op impairment hooks (v1)."""

    def publish_delay_us(self, message_type: str) -> int:
        """Delay between event_ts and publish_ts, in microseconds. v1: 0."""
        return 0

    def drift(self, signal: str, value: float, elapsed_s: float) -> float:
        """Measured value after sensor drift at `elapsed_s` into the run. v1: unchanged."""
        return value

    def drop(self, message_type: str) -> bool:
        """True if this message is lost. Its seq_no is still used, leaving a gap. v1: never."""
        return False
