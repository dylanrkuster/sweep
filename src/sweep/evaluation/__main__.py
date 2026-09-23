"""Evaluate synthetic email decisions locally with the pinned Laya English model."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from sweep.decisions.policy import POLICY_VERSION, check_threshold
from sweep.evaluation.reports import write_reports
from sweep.evaluation.runner import run_cases
from sweep.testing.fixtures import FixtureError, load_cases, load_messages


def _positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _peak_rss_mib() -> float | None:
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    except ImportError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--messages", type=Path, default=Path("tests/fixtures/evaluation/messages.jsonl"))
    parser.add_argument("--cases", type=Path, default=Path("tests/fixtures/evaluation/cases.jsonl"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/laya-english"))
    parser.add_argument("--download-model", action="store_true", help="Explicitly download pinned model files if needed")
    parser.add_argument("--device", choices=["cpu"], default="cpu")
    parser.add_argument("--threads", type=_positive, default=2)
    parser.add_argument("--max-tokens", type=_positive, default=2048)
    parser.add_argument("--delete-threshold", type=float, default=0.8)
    parser.add_argument("--split", choices=["development", "held_out", "all"], default="development")
    parser.add_argument("--repetitions", type=_positive, default=1)
    parser.add_argument("--limit", type=_positive, help="Run only the first N selected cases for a smoke check")
    parser.add_argument("--output", type=Path, help="New output directory; defaults to a timestamp under reports/")
    args = parser.parse_args()
    if not 128 <= args.max_tokens <= 8192:
        parser.error("max-tokens must be from 128 through 8192")
    try:
        check_threshold(args.delete_threshold)
        messages = load_messages(args.messages)
        cases = load_cases(args.cases, messages)
    except (FixtureError, ValueError) as error:
        parser.error(str(error))
    cases = tuple(case for case in cases if args.split == "all" or case.split == args.split)
    if args.limit is not None:
        cases = cases[:args.limit]
    if not cases:
        parser.error("no cases selected")
    output = args.output or Path("reports") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if output.exists():
        parser.error("output directory already exists; choose a new path to preserve previous results")

    try:
        from sweep.decisions.laya import LayaRuntime
        from sweep.decisions.artifacts import download_model
        if args.download_model:
            print("Verifying/downloading pinned Laya English files...", flush=True)
            download_model(args.model_dir)
        print("Loading Laya English on CPU...", flush=True)
        runtime = LayaRuntime(args.model_dir, max_tokens=args.max_tokens, threads=args.threads)
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        parser.error(f"Model setup failed: {error}")

    print(f"Evaluating {len(cases)} {args.split} cases ({args.repetitions} repetitions)...", flush=True)
    results = run_cases(messages, cases, runtime, max_tokens=args.max_tokens,
                        delete_threshold=args.delete_threshold, repetitions=args.repetitions)
    from sweep.decisions.context import CONTEXT_VERSION, QUESTION_VERSION
    versions = {}
    for package in ("sweep", "laya", "torch", "transformers", "tokenizers", "huggingface-hub"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "split": args.split,
        "limit": args.limit,
        "repetitions": args.repetitions,
        "max_tokens": args.max_tokens,
        "delete_threshold": args.delete_threshold,
        "policy_version": POLICY_VERSION,
        "context_version": CONTEXT_VERSION,
        "question_version": QUESTION_VERSION,
        "runtime": runtime.metadata,
        "load_seconds": runtime.load_seconds,
        "peak_rss_mib": _peak_rss_mib(),
        "memory_method": "process high-water RSS, includes model load and Python, bytes on macOS / KiB on Linux",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "threads": args.threads,
        "versions": versions,
        "fixture_hashes": {"messages_sha256": hashlib.sha256(args.messages.read_bytes()).hexdigest(),
                           "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest()},
    }
    report = write_reports(output, results, metadata)
    print(f"Report: {output / 'report.md'}")
    print(json.dumps({key: report['policy'][key] for key in
                      ("unique_cases", "false_deletes", "unexpected_errors", "delete_precision", "delete_recall")}))
    if any((row.error is not None and row.error != row.expected_error)
           or (row.expected_error is not None and not row.matches_expectation) for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
