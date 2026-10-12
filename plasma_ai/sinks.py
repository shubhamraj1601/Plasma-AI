"""Where generated records go. FileSink and StdoutSink now; PubSubSink on Day 8."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol, TextIO

from plasma_ai.messages import Record


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
