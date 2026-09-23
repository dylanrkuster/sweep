# Quickstart

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the repository root:

```sh
uv sync --locked
uv run --locked python -m sweep.testing --messages tests/fixtures/messages.jsonl --cases tests/fixtures/cases.jsonl
uv run --locked pytest
```

The fixture command checks synthetic emails and their separate answer key. It does not run Laya or change Gmail.

To run the local Laya evaluator:

```sh
uv sync --locked --extra model
uv run --locked --extra model python -m sweep.evaluation --download-model
```

The first run downloads about 860 MB of model files. Later, omit `--download-model`. Reports are saved under `reports/`; `--split held_out` runs the separate test cases. The current baseline archives every valid case, so decision quality needs work before connecting Gmail.
