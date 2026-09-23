# Development

**Working now:** a local Laya evaluator, synthetic mailbox, exact token budgeting, decision policy, reports and tests.

**Next:** improve decision quality. The first prompt archives too much; Gmail and cloud integration remain unimplemented.

## Run locally

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run these from the Git repository containing `pyproject.toml`:

```sh
uv sync --locked
uv run --locked python -m sweep.testing --messages tests/fixtures/messages.jsonl --cases tests/fixtures/cases.jsonl
uv run --locked pytest
```

- `sync` sets up Python 3.11 and the dependencies recorded in `uv.lock`.
- The fixture command validates sample data and assembles decision inputs. It makes no predictions or mailbox changes.
- `pytest` checks the code. After setup, both commands work offline.

The environment is separate from other Python projects. Sweep uses an editable install, so source changes take effect without reinstalling.

## Run Laya

```sh
uv sync --locked --extra model
uv run --locked --extra model python -m sweep.evaluation --download-model
```

The first run downloads the pinned English model (about 860 MB). Later runs can omit `--download-model`; inference uses local files only. Defaults: CPU, two threads, 2,048 tokens, development cases and an experimental 0.8 delete threshold.

Results go to a new timestamped folder under `reports/`: `report.md`, `results.json` and `cases.csv`. Use `--split held_out` to evaluate the separate test cases after choosing the prompt and policy. Keep those cases out of tuning.

See [baseline results](baseline.md) and the [evaluator reference](evaluator-plan.md).

## Code map

[Browse the current code map](code-map.md) to see files, major functions and their connections. Update it whenever those responsibilities or connections change. The [architecture guide](architecture.md) describes the planned Gmail and cloud system.

## How evaluation works

1. Load mailbox facts from `messages.jsonl` and expected answers from `cases.jsonl`.
2. Retrieve each target email and earlier messages in its thread.
3. Build the context, run Laya once, and apply the delete threshold.
4. Compare the result with the separate answer key. Reports contain scores and counts, not email bodies.

Message objects cannot be edited in place, preventing tests from changing each other's data. Prior context excludes messages with the same or a later timestamp; earlier messages are sorted by timestamp, then ID.

## Adding examples

JSONL means one JSON object per line. Use synthetic mail in public fixtures; keep future private examples in the ignored `tests/fixtures/private/` directory.

Each case references a message and expects either `archive`, `delete` or an explicit error. Related cases must stay in the same dataset split. The loader checks fields, IDs, references and split boundaries.

The original seed data checks the foundation. The larger evaluation corpus measures this particular prompt/model combination; it does not establish real-mail accuracy.

## Troubleshooting: Python cannot find `sweep`

First run `uv sync --locked` from the repository.

On macOS, Python can also ignore the `sweep.pth` file that points to our source if it carries the operating system's hidden flag. [Python startup behavior](https://github.com/python/cpython/blob/3.11/Lib/site.py)

Check for `hidden`:

```sh
ls -lO .venv/lib/python3.11/site-packages/sweep.pth
```

If present, clear it on the known setup files:

```sh
chflags nohidden .venv/lib/python3.11/site-packages/sweep.pth \
  .venv/lib/python3.11/site-packages/_virtualenv.pth
```

On the initial development machine, these flags kept returning for an unknown reason. The working repair uses a visible `venv/` directory, with `.venv` pointing to it. Normal commands stay the same; both paths are ignored by Git. If rebuilding this setup, see [uv's environment location setting](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path).
