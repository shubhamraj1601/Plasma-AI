"""Integration test against the local Pub/Sub emulator; skipped unless PUBSUB_EMULATOR_HOST is set."""

from __future__ import annotations

import copy
import json
import os
import uuid
from collections import Counter
from pathlib import Path

import pytest
import yaml

from conftest import START_TS
from plasma_ai.config import config_from_dict
from plasma_ai.emulator import setup, subscription_name
from plasma_ai.generator.__main__ import main
from plasma_ai.validate import MessageValidator

pytestmark = pytest.mark.skipif(
    not os.environ.get("PUBSUB_EMULATOR_HOST"), reason="PUBSUB_EMULATOR_HOST not set (local Pub/Sub emulator)"
)


def test_generator_publishes_to_emulator(raw_config: dict, tmp_path: Path) -> None:
    from google.cloud import pubsub_v1

    raw = copy.deepcopy(raw_config)
    raw["pubsub"]["project_id"] = f"plasma-ai-test-{uuid.uuid4().hex[:8]}"  # fresh project: no leftover messages
    cfg = config_from_dict(raw)
    config_path = tmp_path / "generator.yaml"
    with config_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(raw, f)

    publisher, subscriber = pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()
    assert len(setup(cfg, publisher, subscriber)) == 6
    assert setup(cfg, publisher, subscriber) == []  # idempotent

    code = main(["--config", str(config_path), "--start-ts", START_TS, "--duration-s", "2", "--seed", "21",
                 "--sink", "pubsub", "--speed", "0"])
    assert code == 0

    validator = MessageValidator()
    received: dict[str, Counter[str]] = {}
    for topic in ("process-ts", "oes-spectra", "dead-letter"):
        path = subscriber.subscription_path(cfg.pubsub.project_id, subscription_name(topic))
        counts: Counter[str] = Counter()
        for _ in range(20):
            response = subscriber.pull(request={"subscription": path, "max_messages": 100}, timeout=2)
            if not response.received_messages:
                break
            for m in response.received_messages:
                data = json.loads(m.message.data.decode("utf-8"))
                validator.validate(data)
                attrs = dict(m.message.attributes)
                assert attrs == {k: data[k] for k in ("schema_version", "message_type", "run_id", "source")}
                counts[attrs["message_type"]] += 1
            subscriber.acknowledge(request={"subscription": path, "ack_ids": [m.ack_id for m in response.received_messages]})
        received[topic] = counts
    assert received["process-ts"] == {"run_start": 1, "process_sample": 20, "run_end": 1, "run_outcome": 1}
    assert received["oes-spectra"] == {"oes_block": 20}
    assert received["dead-letter"] == {}
