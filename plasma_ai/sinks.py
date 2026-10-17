"""Where generated records go: FileSink, StdoutSink and PubSubSink."""

from __future__ import annotations

import heapq
import itertools
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TextIO

from plasma_ai.messages import Record, parse_ts


class Sink(Protocol):
    """Destination for records, written in event order."""

    def write(self, record: Record) -> None:
        """Send one record."""

    def close(self) -> None:
        """Flush and release resources."""


class FileSink:
    """Writes out/<run_id>/<topic>.jsonl, one Pub/Sub-shaped record per line.

    Records must arrive grouped by run; files of a run are closed when the next
    run starts. Existing files for the same run_id are overwritten.
    """

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = Path(out_dir)
        self.paths: dict[str, list[Path]] = {}
        self._run_id: str | None = None
        self._files: dict[str, TextIO] = {}

    def write(self, record: Record) -> None:
        """Append the record to its run's topic file."""
        if record.run_id != self._run_id:
            self._close_files()
            self._run_id = record.run_id
        f = self._files.get(record.topic)
        if f is None:
            path = self.out_dir / record.run_id / f"{record.topic}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            f = path.open("w", encoding="utf-8", newline="\n")
            self._files[record.topic] = f
            self.paths.setdefault(record.run_id, []).append(path)
        f.write(record.to_json_line() + "\n")

    def close(self) -> None:
        """Close all open files."""
        self._close_files()

    def _close_files(self) -> None:
        for f in self._files.values():
            f.close()
        self._files = {}


class StdoutSink:
    """Prints one JSON record per line to stdout."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout

    def write(self, record: Record) -> None:
        """Print the record as one JSON line."""
        self.stream.write(record.to_json_line() + "\n")

    def close(self) -> None:
        """Flush the stream."""
        self.stream.flush()


class PublishFuture(Protocol):
    """The part of a Pub/Sub publish future the sink uses."""

    def done(self) -> bool:
        """True once the publish finished, successfully or not."""

    def result(self, timeout: float | None = None) -> Any:
        """The server message ID; raises if the publish failed."""


class Publisher(Protocol):
    """The part of google.cloud.pubsub_v1.PublisherClient the sink uses (a fake in tests)."""

    def topic_path(self, project: str, topic: str) -> str:
        """Full topic name, projects/<project>/topics/<topic>."""

    def publish(self, topic: str, data: bytes, **attrs: str) -> PublishFuture:
        """Queue one message for publishing."""


class PublishError(RuntimeError):
    """Raised when Pub/Sub rejects or fails to deliver a message."""


def pubsub_publisher() -> Publisher:
    """Real Pub/Sub client. It talks to the emulator when PUBSUB_EMULATOR_HOST is set."""
    from google.cloud import pubsub_v1  # imported here so file-only runs do not load gRPC

    return pubsub_v1.PublisherClient()


class PubSubSink:
    """Publishes records to their topics in publish_ts order, paced to real time divided by `speed`.

    Records arrive in event_ts order. With a publish delay, a message may be due
    after later events, so records wait in a buffer until no later record can
    have an earlier publish_ts (publish_ts >= event_ts always holds). The
    message body is the JSON message; its attributes are the record's string
    attributes. `speed` 0 publishes as fast as possible.
    """

    _PRUNE_EVERY = 1000

    def __init__(
        self,
        publisher: Publisher,
        project_id: str,
        speed: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        result_timeout_s: float = 60.0,
    ) -> None:
        if speed < 0:
            raise ValueError(f"speed must be >= 0, got {speed}")
        self.publisher = publisher
        self.project_id = project_id
        self.speed = speed
        self.clock = clock
        self.sleep = sleep
        self.result_timeout_s = result_timeout_s
        self.published: Counter[str] = Counter()
        self._buffer: list[tuple[str, int, Record]] = []
        self._order = itertools.count()
        self._start: tuple[datetime, float] | None = None
        self._topic_paths: dict[str, str] = {}
        self._pending: list[tuple[str, PublishFuture]] = []

    def topic_path(self, topic: str) -> str:
        """Full Pub/Sub name of a topic in this sink's project."""
        if topic not in self._topic_paths:
            self._topic_paths[topic] = self.publisher.topic_path(self.project_id, topic)
        return self._topic_paths[topic]

    def write(self, record: Record) -> None:
        """Buffer the record, then publish every buffered record that is due by its event_ts."""
        # Fixed-width UTC timestamps sort correctly as strings. A dead letter may have a null event_ts.
        publish_ts = record.data["publish_ts"]
        heapq.heappush(self._buffer, (publish_ts, next(self._order), record))
        now = record.data["event_ts"] or publish_ts
        while self._buffer and self._buffer[0][0] <= now:
            self._publish(heapq.heappop(self._buffer)[2])

    def close(self) -> None:
        """Publish what is still buffered and wait until Pub/Sub has accepted every message."""
        while self._buffer:
            self._publish(heapq.heappop(self._buffer)[2])
        pending, self._pending = self._pending, []
        for topic, future in pending:
            self._check(topic, future)

    def _publish(self, record: Record) -> None:
        self._pace(parse_ts(record.data["publish_ts"]))
        path = self.topic_path(record.topic)
        future = self.publisher.publish(path, record.data_bytes(), **record.attributes)
        self._pending.append((path, future))
        self.published[record.topic] += 1
        if len(self._pending) >= self._PRUNE_EVERY:
            for topic, done in [(t, f) for t, f in self._pending if f.done()]:
                self._check(topic, done)
            self._pending = [(t, f) for t, f in self._pending if not f.done()]

    def _pace(self, publish_ts: datetime) -> None:
        """Sleep until publish_ts, measured from the first published message and scaled by speed."""
        if self.speed == 0:
            return
        now = self.clock()
        if self._start is None:
            self._start = (publish_ts, now)
            return
        first_ts, first_clock = self._start
        due = first_clock + (publish_ts - first_ts).total_seconds() / self.speed
        if due > now:
            self.sleep(due - now)

    def _check(self, topic: str, future: PublishFuture) -> None:
        try:
            future.result(timeout=self.result_timeout_s)
        except Exception as exc:  # the client raises many types (gRPC, timeout, NotFound, ...)
            raise PublishError(f"publishing to {topic} failed: {exc}") from exc
