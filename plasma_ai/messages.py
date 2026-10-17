"""Build schema v0 messages (envelope + flat payload) as Pub/Sub-shaped records."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from plasma_ai.config import GeneratorConfig
from plasma_ai.impairments import Impairments

_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def format_ts(ts: datetime) -> str:
    """Format a datetime as UTC ISO-8601 with microseconds and a trailing Z."""
    return ts.astimezone(timezone.utc).strftime(_TS_FORMAT)


def parse_ts(text: str) -> datetime:
    """Parse an ISO-8601 timestamp; a value without a timezone is taken as UTC."""
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def new_message_id(rng: np.random.Generator) -> str:
    """UUID v4 drawn from the seeded RNG, so seeded runs are reproducible."""
    return str(uuid.UUID(bytes=rng.bytes(16), version=4))


@dataclass(frozen=True)
class Record:
    """One Pub/Sub-shaped message: string attributes plus the JSON data."""

    topic: str
    attributes: dict[str, str]
    data: dict[str, Any]

    @property
    def message_type(self) -> str:
        """The message_type of the wrapped message."""
        return self.data["message_type"]

    @property
    def run_id(self) -> str:
        """The run_id of the wrapped message."""
        return self.data["run_id"]

    def data_bytes(self) -> bytes:
        """The message alone (no attributes) as compact UTF-8 JSON: the Pub/Sub message body."""
        return json.dumps(self.data, allow_nan=False, separators=(",", ":")).encode("utf-8")

    def to_json_line(self) -> str:
        """Serialise as one JSON line; raises ValueError on NaN or Infinity."""
        return json.dumps(
            {"attributes": self.attributes, "data": self.data},
            allow_nan=False,
            separators=(",", ":"),
        )


class MessageFactory:
    """Builds the messages of one run, keeping seq_no per message type."""

    def __init__(
        self,
        cfg: GeneratorConfig,
        run_id: str,
        rng: np.random.Generator,
        impairments: Impairments,
    ) -> None:
        self.cfg = cfg
        self.run_id = run_id
        self.rng = rng
        self.impairments = impairments
        self._seq: defaultdict[str, int] = defaultdict(int)

    def build(self, message_type: str, event_ts: datetime, payload: dict[str, Any]) -> Record:
        """Wrap a payload in the envelope and Pub/Sub attributes."""
        seq_no = self._seq[message_type]
        self._seq[message_type] += 1
        publish_ts = event_ts + timedelta(microseconds=self.impairments.publish_delay_us(message_type))
        data: dict[str, Any] = {
            "schema_version": self.cfg.schema_version,
            "message_type": message_type,
            "message_id": new_message_id(self.rng),
            "source": self.cfg.source,
            "reactor_id": self.cfg.reactor_id,
            "run_id": self.run_id,
            "seq_no": seq_no,
            "event_ts": format_ts(event_ts),
            "publish_ts": format_ts(publish_ts),
            **payload,
        }
        attributes = {
            "schema_version": self.cfg.schema_version,
            "message_type": message_type,
            "run_id": self.run_id,
            "source": self.cfg.source,
        }
        return Record(topic=self.cfg.topics[message_type], attributes=attributes, data=data)
