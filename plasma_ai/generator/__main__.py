"""CLI: python -m plasma_ai.generator --runs 1 --duration-s 60 --seed 42 --out out [--sink pubsub]"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from plasma_ai.config import OES_MODES, ConfigError, load_config
from plasma_ai.generator.run import RunSpec, generate_run, make_run_id, sample_setpoints
from plasma_ai.impairments import Impairments
from plasma_ai.messages import parse_ts
from plasma_ai.sinks import FileSink, PublishError, PubSubSink, Sink, StdoutSink, pubsub_publisher
from plasma_ai.validate import MessageValidationError, MessageValidator


def _positive_float(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
    return value


def _non_negative_float(text: str) -> float:
    value = float(text)
    if not value >= 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {text}")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {text}")
    return value


def _timestamp(text: str) -> datetime:
    try:
        return parse_ts(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO-8601 timestamp: {text}") from exc


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface of the synthetic generator."""
    p = argparse.ArgumentParser(
        prog="python -m plasma_ai.generator",
        description="Generate synthetic microwave plasma reactor runs as schema v0 messages (JSON Lines).",
    )
    p.add_argument("--config", type=Path, default=Path("config/generator.yaml"), help="config file")
    p.add_argument("--runs", type=_positive_int, default=1, help="number of runs (default 1)")
    p.add_argument("--duration-s", type=_positive_float, default=60.0, help="seconds of data per run (default 60)")
    p.add_argument("--seed", type=int, default=None, help="RNG seed; same seed + same --start-ts gives identical output")
    p.add_argument("--start-ts", type=_timestamp, default=None, help="ISO-8601 start of the first run (default: now, UTC)")
    p.add_argument("--reference-run", action="store_true", help="use the slide 3 setpoints instead of sampling")
    p.add_argument(
        "--no-noise",
        action="store_true",
        help="turn off measurement and outcome noise and every disturbance (delay, drift, dropouts, missing messages)",
    )
    p.add_argument("--oes-mode", choices=OES_MODES, default=None, help="override oes.mode from config")
    p.add_argument(
        "--sink",
        choices=("file", "pubsub"),
        default="file",
        help="file: JSONL under --out (default); pubsub: publish to the config topics (lines OES mode only)",
    )
    p.add_argument(
        "--speed",
        type=_non_negative_float,
        default=None,
        help="pubsub pacing: 1 = real time, 10 = ten times faster, 0 = as fast as possible (default: pubsub.speed)",
    )
    p.add_argument("--out", type=Path, default=Path("out"), help="output folder for the file sink (default out)")
    p.add_argument("--stdout", action="store_true", help="also print messages to stdout; the summary then goes to stderr")
    p.add_argument(
        "--validate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="validate every message before writing (default on)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the generator; returns the process exit code."""
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rng = np.random.default_rng(args.seed)
    oes_mode = args.oes_mode or cfg.oes.mode
    if args.sink == "pubsub" and oes_mode != "lines":
        print("error: --sink pubsub supports OES mode 'lines' only (full mode is for local tests)", file=sys.stderr)
        return 2
    start = args.start_ts or datetime.now(timezone.utc)
    validator = MessageValidator() if args.validate else None
    impairments = Impairments() if args.no_noise else Impairments(cfg.disturbances, rng)
    file_sink: FileSink | None = None
    pubsub_sink: PubSubSink | None = None
    if args.sink == "file":
        file_sink = FileSink(args.out)
        sinks: list[Sink] = [file_sink]
    else:
        speed = cfg.pubsub.speed if args.speed is None else args.speed
        pubsub_sink = PubSubSink(pubsub_publisher(), cfg.pubsub.project_id, speed)
        sinks = [pubsub_sink]
    if args.stdout:
        sinks.append(StdoutSink())
    summary_stream = sys.stderr if args.stdout else sys.stdout

    try:
        try:
            for number in range(1, args.runs + 1):
                spec = RunSpec(
                    run_id=make_run_id(cfg.run.id_prefix, start, number),
                    start=start,
                    duration_s=args.duration_s,
                    setpoints=cfg.reference_run if args.reference_run else sample_setpoints(cfg.sweep, rng),
                    oes_mode=oes_mode,
                    noise=not args.no_noise,
                    seed=args.seed,
                )
                counts: Counter[str] = Counter()
                stats_before = Counter(impairments.stats)
                outcome: dict = {}
                for record in generate_run(cfg, spec, rng, impairments):
                    if validator is not None:
                        validator.validate_record(record)
                    for sink in sinks:
                        sink.write(record)
                    counts[record.message_type] += 1
                    if record.message_type == "run_outcome":
                        outcome = record.data
                if file_sink is not None:
                    where = ", ".join(str(p) for p in file_sink.paths.get(spec.run_id, []))
                else:
                    where = ", ".join(pubsub_sink.topic_path(t) for t in sorted({cfg.topics[m] for m in counts}))
                disturbed = impairments.stats - stats_before
                print(_summary(spec.run_id, counts, where, disturbed, outcome), file=summary_stream)
                start = start + timedelta(seconds=args.duration_s + cfg.run.gap_s)
        finally:
            for sink in sinks:
                sink.close()
    except MessageValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    return 0


def _summary(run_id: str, counts: Counter[str], where: str, disturbed: Counter[str], outcome: dict) -> str:
    count_text = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    if disturbed:
        count_text += " | disturbances: " + " ".join(f"{k}={v}" for k, v in sorted(disturbed.items()))
    outcome_text = (
        f"yield={outcome['graphite_yield_percent']:.2f}% id_ig={outcome['raman_id_ig']:.3f} "
        f"xrd_fwhm={outcome['xrd_002_fwhm_deg']:.3f}deg h2_purity={outcome['h2_purity_percent']:.2f}%"
        if outcome
        else "no run_outcome"
    )
    return f"{run_id} | {count_text} | {where} | {outcome_text}"


if __name__ == "__main__":
    sys.exit(main())
