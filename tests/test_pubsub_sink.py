"""PubSubSink with a fake client: topics, attributes, body, pacing, ordering and errors."""

from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from conftest import CONFIG_PATH, START_TS
from plasma_ai.config import config_from_dict
from plasma_ai.generator import __main__ as cli
from plasma_ai.generator.run import RunSpec, generate_run
from plasma_ai.impairments import Impairments
from plasma_ai.messages import Record
from plasma_ai.sinks import PublishError, PubSubSink

PROJECT = "test-project"


@dataclass
class FakeFuture:
    error: Exception | None = None

    def done(self) -> bool:
        return True

    def result(self, timeout: float | None = None) -> str:
        if self.error is not None:
            raise self.error
        return "message-id"


@dataclass
class FakePublisher:
    """Records publish calls like google.cloud.pubsub_v1.PublisherClient would receive them."""

    calls: list[tuple[str, bytes, dict[str, str]]] = field(default_factory=list)
    fail_on: str | None = None

    def topic_path(self, project: str, topic: str) -> str:
        return f"projects/{project}/topics/{topic}"

    def publish(self, topic: str, data: bytes, **attrs: str) -> FakeFuture:
        self.calls.append((topic, data, attrs))
        return FakeFuture(RuntimeError("404 topic not found") if topic == self.fail_on else None)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _records(raw_config: dict, publish_delay: bool = False, duration_s: float = 2.0) -> list[Record]:
    raw = copy.deepcopy(raw_config)
    raw["disturbances"]["publish_delay"]["enabled"] = publish_delay
    cfg = config_from_dict(raw)
    rng = np.random.default_rng(12)
    spec = RunSpec(
        run_id="SYN-20261012-050000-001",
        start=datetime(2026, 10, 12, 5, tzinfo=timezone.utc),
        duration_s=duration_s,
        setpoints=cfg.reference_run,
        oes_mode="lines",
        noise=True,
        seed=12,
    )
    return list(generate_run(cfg, spec, rng, Impairments(cfg.disturbances, rng)))


def _publish_all(records: list[Record], speed: float = 0, clock: FakeClock | None = None) -> FakePublisher:
    publisher = FakePublisher()
    clock = clock or FakeClock()
    sink = PubSubSink(publisher, PROJECT, speed, clock=clock, sleep=clock.sleep)
    for record in records:
        sink.write(record)
    sink.close()
    return publisher


def test_topics_attributes_and_body(raw_config: dict) -> None:
    records = _records(raw_config)
    publisher = _publish_all(records)
    assert len(publisher.calls) == len(records)
    for record, (topic, data, attrs) in zip(records, publisher.calls):
        assert topic == f"projects/{PROJECT}/topics/{record.topic}"
        assert attrs == record.attributes
        assert set(attrs) == {"schema_version", "message_type", "run_id", "source"}
        assert all(isinstance(v, str) for v in attrs.values())
        assert json.loads(data.decode("utf-8")) == record.data
    topics = Counter(t.rsplit("/", 1)[1] for t, _, _ in publisher.calls)
    assert topics == {"process-ts": 23, "oes-spectra": 20}


def test_dead_letter_with_null_event_ts_goes_to_dead_letter_topic() -> None:
    data = {"message_type": "dead_letter", "event_ts": None, "publish_ts": "2026-10-12T05:00:00.000000Z"}
    record = Record(topic="dead-letter", attributes={"message_type": "dead_letter"}, data=data)
    publisher = FakePublisher()
    sink = PubSubSink(publisher, PROJECT, 0)
    sink.write(record)
    assert publisher.calls[0][0] == f"projects/{PROJECT}/topics/dead-letter"


@pytest.mark.parametrize("speed", [1.0, 10.0])
def test_paced_to_real_time_divided_by_speed(raw_config: dict, speed: float) -> None:
    clock = FakeClock()
    _publish_all(_records(raw_config, duration_s=2.0), speed=speed, clock=clock)
    # 2 s of samples, then run_end at 2 s and run_outcome 1 s later: 3 s of stream time in total.
    assert clock.now - 100.0 == pytest.approx(3.0 / speed)
    assert max(clock.sleeps) == pytest.approx(1.0 / speed)  # the wait for run_outcome


def test_speed_zero_never_sleeps(raw_config: dict) -> None:
    clock = FakeClock()
    _publish_all(_records(raw_config), speed=0, clock=clock)
    assert clock.sleeps == []


def test_delayed_messages_published_in_publish_ts_order(raw_config: dict) -> None:
    records = _records(raw_config, publish_delay=True, duration_s=5.0)
    publisher = _publish_all(records)
    published = [json.loads(data) for _, data, _ in publisher.calls]
    assert len(published) == len(records)
    publish_ts = [m["publish_ts"] for m in published]
    assert publish_ts == sorted(publish_ts)
    event_ts = [m["event_ts"] for m in published]
    assert event_ts != sorted(event_ts)  # jitter reorders arrival relative to measurement time


def test_failed_publish_raises_publish_error(raw_config: dict) -> None:
    publisher = FakePublisher(fail_on=f"projects/{PROJECT}/topics/oes-spectra")
    sink = PubSubSink(publisher, PROJECT, 0)
    for record in _records(raw_config):
        sink.write(record)
    with pytest.raises(PublishError, match="oes-spectra"):
        sink.close()


def test_negative_speed_rejected() -> None:
    with pytest.raises(ValueError, match="speed"):
        PubSubSink(FakePublisher(), PROJECT, -1)


def test_cli_publishes_to_config_topics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    publisher = FakePublisher()
    monkeypatch.setattr(cli, "pubsub_publisher", lambda: publisher)
    code = cli.main([
        "--config", str(CONFIG_PATH), "--start-ts", START_TS, "--out", str(tmp_path),
        "--duration-s", "1", "--seed", "3", "--sink", "pubsub", "--speed", "0",
    ])
    assert code == 0
    assert Counter(t for t, _, _ in publisher.calls) == {
        "projects/plasma-ai-local/topics/process-ts": 13,
        "projects/plasma-ai-local/topics/oes-spectra": 10,
    }
    assert not any(tmp_path.iterdir())  # the pubsub sink writes no files


def test_cli_rejects_full_oes_mode_for_pubsub(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(cli, "pubsub_publisher", FakePublisher)
    code = cli.main(["--config", str(CONFIG_PATH), "--duration-s", "1", "--sink", "pubsub", "--oes-mode", "full"])
    assert code == 2
    assert "lines" in capsys.readouterr().err


def test_cli_reports_publish_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(cli, "pubsub_publisher", lambda: FakePublisher(fail_on="projects/plasma-ai-local/topics/process-ts"))
    code = cli.main(["--config", str(CONFIG_PATH), "--duration-s", "1", "--sink", "pubsub", "--speed", "0"])
    assert code == 3
    assert "process-ts" in capsys.readouterr().err
