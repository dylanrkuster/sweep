# Development

**Working now:** Python setup, synthetic email loading, a read-only fake mailbox and tests.

**Next:** more examples, context preparation and Laya inference. Gmail and cloud integration come later.

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

## Code map

| Location | Purpose |
| --- | --- |
| `pyproject.toml`, `uv.lock` | Project settings and pinned dependencies. |
| `src/sweep/domain.py` | Shared email, attachment and decision-input objects. |
| `src/sweep/testing/fixtures.py` | Loads emails and separate expected answers. |
| `src/sweep/testing/mailbox.py` | Retrieves messages and earlier thread context. |
| `src/sweep/testing/__main__.py` | Runs the fixture command. |
| `tests/` | Tests and a small synthetic seed dataset. |

## How the fixture check works

1. Load mailbox facts from `messages.jsonl` and expected answers from `cases.jsonl`.
2. Retrieve each target email and earlier messages in its thread.
3. Build a `DecisionInput` containing preferences and emails. Expected answers stay separate for future scoring.

Message objects cannot be edited in place, preventing tests from changing each other's data. Prior context excludes messages with the same or a later timestamp; earlier messages are sorted by timestamp, then ID.

## Adding examples

JSONL means one JSON object per line. Use synthetic mail in public fixtures; keep future private examples in the ignored `tests/fixtures/private/` directory.

Each case references a message and expects either `archive`, `delete` or an explicit error. Related cases must stay in the same dataset split. The loader checks fields, IDs, references and split boundaries.

See the [evaluator plan](evaluator-plan.md) for record examples and remaining implementation work. The current seed data checks the foundation, not model accuracy.

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
