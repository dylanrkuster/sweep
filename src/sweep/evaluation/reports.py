"""Write compact reports without saving email bodies or model input text."""

import csv
import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from sweep.evaluation.metrics import summarize, timing_summary
from sweep.evaluation.runner import CaseResult


def _ratio_text(metric: dict) -> str:
    value = metric["value"]
    return "N/A (0 denominator)" if value is None else (
        f"{value:.1%} ({metric['numerator']}/{metric['denominator']})"
    )


def _seconds(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f} s"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def write_reports(output: Path, results: Iterable[CaseResult], metadata: dict) -> dict:
    rows = tuple(results)
    policy = summarize(rows)
    raw = summarize(rows, raw=True)
    timing = timing_summary(rows)
    report = {
        "schema_version": 1,
        "metadata": metadata,
        "policy": policy,
        "raw_model": raw,
        "timing": timing,
        "by_split": {split: {"policy": summarize(r for r in rows if r.split == split),
                              "raw_model": summarize((r for r in rows if r.split == split), raw=True)}
                     for split in sorted({r.split for r in rows})},
        "cases": [{**asdict(row), "matches_expectation": row.matches_expectation} for row in rows],
    }
    # Never silently replace an earlier baseline.
    output.mkdir(parents=True, exist_ok=False)
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    csv_fields = ["case_id", "family_id", "split", "repetition", "expected_action",
                  "expected_error", "raw_choice", "action", "error", "delete_probability",
                  "input_tokens", "context_seconds", "inference_seconds", "matches_expectation"]
    with (output / "cases.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            values = {key: getattr(row, key) for key in csv_fields if hasattr(row, key)}
            values["delete_probability"] = row.probabilities["delete"] if row.probabilities else None
            values["input_tokens"] = row.token_counts["total"] if row.token_counts else None
            writer.writerow(values)
    lines = [
        "# Sweep evaluation", "",
        f"{policy['unique_cases']} unique cases, {policy['attempts']} attempts, "
        f"{policy['families']} families. Split: {metadata['split']}.", "",
        "Synthetic engineering examples; these results do not establish real-mail accuracy or safety.",
        f"Delete threshold: **{metadata['delete_threshold']}** (experimental, not calibrated). "
        f"Context limit: **{metadata['max_tokens']}** tokens.", "",
        "| Measure | Policy | Raw model |", "| --- | --- | --- |",
        f"| Action accuracy (errors count as misses) | {_ratio_text(policy['action_accuracy'])} | {_ratio_text(raw['action_accuracy'])} |",
        f"| Delete precision | {_ratio_text(policy['delete_precision'])} | {_ratio_text(raw['delete_precision'])} |",
        f"| Delete recall | {_ratio_text(policy['delete_recall'])} | {_ratio_text(raw['delete_recall'])} |",
        f"| Incorrect deletes | {policy['false_deletes']} | {raw['false_deletes']} |", "",
        f"Expected validation errors matched: {policy['expected_errors_matched']}/{policy['expected_error_cases']}. "
        f"Unexpected errors: {policy['unexpected_errors']}.", "",
        "| Expected action | Predicted archive | Predicted delete | Error |", "| --- | ---: | ---: | ---: |",
    ]
    for action, counts in policy["confusion_matrix"].items():
        lines.append(f"| {action} | {counts['archive']} | {counts['delete']} | {counts['error']} |")
    lines += ["", "## Runtime", "",
              f"Model load: {_seconds(metadata['load_seconds'])}. "
              f"First inference: {_seconds(timing['first_inference_seconds'])}.",
              f"Warm median: {_seconds(timing['warm_median_seconds'])}; "
              f"warm p95: {_seconds(timing['warm_p95_seconds'])} "
              f"({timing['warm_inference_count']} calls).",
              f"Peak process memory: {metadata['peak_rss_mib']:.0f} MiB." if metadata['peak_rss_mib'] is not None else "Peak process memory: unavailable.",
              "Timings are local wall-clock measurements. They exclude download time and do not predict Modal or Gmail latency.",
              "", "## Individual results", "",
              "| Case | Split | Run | Expected | Raw | Policy | Error | Tokens |",
              "| --- | --- | ---: | --- | --- | --- | --- | ---: |"]
    for row in rows:
        lines.append("| " + " | ".join(map(_cell, (
            row.case_id, row.split, row.repetition,
            row.expected_action or row.expected_error, row.raw_choice or "—",
            row.action or "—", row.error or "—",
            row.token_counts["total"] if row.token_counts else "—",
        ))) + " |")
    lines += ["", "Full scores, versions, file hashes and per-case timings are in `results.json`; `cases.csv` is for comparison."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
