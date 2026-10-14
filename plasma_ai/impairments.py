"""Stream disturbances: publish delay, sensor drift, dropouts and missing messages.

Each disturbance has its own switch in config (`disturbances:`). A disabled
disturbance draws nothing from the RNG, so output with everything off is
byte-identical to the v1 generator.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from plasma_ai.config import DisturbancesConfig


class Impairments:
    """Applies the configured disturbances; with no config every hook is a no-op."""

    def __init__(self, cfg: DisturbancesConfig | None = None, rng: np.random.Generator | None = None) -> None:
        if cfg is not None and rng is None:
            raise ValueError("an RNG is required when disturbances are configured")
        self.cfg = cfg
        self.rng = rng
        self.stats: Counter[str] = Counter()

    def publish_delay_us(self, message_type: str) -> int:
        """Delay between event_ts and publish_ts, in microseconds (0 when off)."""
        if self.cfg is None or not self.cfg.publish_delay.enabled:
            return 0
        delay = self.cfg.publish_delay
        extra_ms = float(self.rng.exponential(delay.mean_extra_ms)) if delay.mean_extra_ms > 0 else 0.0
        return round((delay.min_ms + extra_ms) * 1000)

    def drift(self, signal: str, value: float, elapsed_s: float) -> float:
        """Measured value after linear relative drift at `elapsed_s` into the run (unchanged when off)."""
        if self.cfg is None or not self.cfg.drift.enabled:
            return value
        rate = self.cfg.drift.rel_per_hour.get(signal, 0.0)
        return value * (1 + rate * elapsed_s / 3600)

    def dropout(self, signal: str) -> bool:
        """True if this reading is lost and must be sent as null (never when off)."""
        if self.cfg is None or not self.cfg.dropout.enabled:
            return False
        prob = self.cfg.dropout.null_prob.get(signal, 0.0)
        if prob <= 0:
            return False
        lost = bool(self.rng.random() < prob)
        if lost:
            self.stats[f"null.{signal}"] += 1
        return lost

    def drop(self, message_type: str) -> bool:
        """True if this message is lost. Its seq_no is still used, leaving a gap (never when off)."""
        if self.cfg is None or not self.cfg.missing_messages.enabled:
            return False
        prob = self.cfg.missing_messages.prob.get(message_type, 0.0)
        if prob <= 0:
            return False
        lost = bool(self.rng.random() < prob)
        if lost:
            self.stats[f"missing.{message_type}"] += 1
        return lost
