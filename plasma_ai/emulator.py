"""Local Pub/Sub emulator helper: create the topics and subscriptions, and pull to check.

    python -m plasma_ai.emulator setup            # topics from config + one <topic>-sub each
    python -m plasma_ai.emulator pull --max 500   # pull, ack and count what arrived

It refuses to run unless PUBSUB_EMULATOR_HOST is set, so it never touches real
GCP. On real GCP the same topics and subscriptions come from infra/setup.ps1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from plasma_ai.config import ConfigError, GeneratorConfig, load_config

EMULATOR_ENV = "PUBSUB_EMULATOR_HOST"


def subscription_name(topic: str) -> str:
    """One subscription per topic, named <topic>-sub (same rule as infra/setup.ps1)."""
    return f"{topic}-sub"


def setup(cfg: GeneratorConfig, publisher: Any, subscriber: Any) -> list[str]:
    """Create every config topic and its subscription; existing ones are kept. Returns what was created."""
    from google.api_core.exceptions import AlreadyExists

    created = []
    project = cfg.pubsub.project_id
    for topic in sorted(set(cfg.topics.values())):
        topic_path = publisher.topic_path(project, topic)
        sub_path = subscriber.subscription_path(project, subscription_name(topic))
        try:
            publisher.create_topic(request={"name": topic_path})
            created.append(topic_path)
        except AlreadyExists:
            pass
        try:
            subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
            created.append(sub_path)
        except AlreadyExists:
            pass
    return created


def pull(cfg: GeneratorConfig, subscriber: Any, max_messages: int) -> dict[str, Counter[str]]:
    """Pull and ack up to `max_messages` per subscription; returns message_type counts per subscription."""
    result: dict[str, Counter[str]] = {}
    project = cfg.pubsub.project_id
    for topic in sorted(set(cfg.topics.values())):
        sub_path = subscriber.subscription_path(project, subscription_name(topic))
        counts: Counter[str] = Counter()
        while sum(counts.values()) < max_messages:
            want = min(1000, max_messages - sum(counts.values()))
            response = subscriber.pull(request={"subscription": sub_path, "max_messages": want}, timeout=3)
            if not response.received_messages:
                break
            for received in response.received_messages:
                counts[received.message.attributes.get("message_type", "<no message_type>")] += 1
            subscriber.acknowledge(
                request={"subscription": sub_path, "ack_ids": [m.ack_id for m in response.received_messages]}
            )
        result[sub_path] = counts
    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    p = argparse.ArgumentParser(prog="python -m plasma_ai.emulator", description=__doc__.splitlines()[0])
    p.add_argument("command", choices=("setup", "pull"))
    p.add_argument("--config", type=Path, default=Path("config/generator.yaml"), help="generator config")
    p.add_argument("--max", type=int, default=1000, help="pull: most messages to pull per subscription")
    args = p.parse_args(argv)
    if not os.environ.get(EMULATOR_ENV):
        print(f"error: {EMULATOR_ENV} is not set; this helper only talks to the local emulator", file=sys.stderr)
        return 2
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from google.cloud import pubsub_v1

    subscriber = pubsub_v1.SubscriberClient()
    if args.command == "setup":
        created = setup(cfg, pubsub_v1.PublisherClient(), subscriber)
        print(f"emulator {os.environ[EMULATOR_ENV]}: created {len(created)} (existing ones kept)")
        for name in created:
            print(f"  {name}")
    else:
        for sub_path, counts in pull(cfg, subscriber, args.max).items():
            print(f"{sub_path}: {sum(counts.values())} message(s) {json.dumps(dict(sorted(counts.items())))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
