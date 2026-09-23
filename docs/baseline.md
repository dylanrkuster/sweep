# First Laya baseline

Measured September 22, 2026 on an ARM Mac with 24 GiB RAM and eight logical CPUs. Inference used two CPU threads, float32, Laya 0.3.5, Transformers 5.17.0 and PyTorch 2.14.0. Question: `disposition-v1`; context: `complete-evidence-v1`; delete threshold: 0.8.

## Decision quality

| Measure | Development | Held-out |
| --- | ---: | ---: |
| Valid action cases | 20 | 12 |
| Raw model correct | 11/20 | 8/12 |
| Raw model incorrect deletes | 2 | 0 |
| Raw model expected deletes found | 1/8 | 2/6 |
| Policy deletes | 0 | 0 |
| Expected validation errors matched | 6/6 | 2/2 |

**This prompt/model combination is not ready for automatic inbox changes.** The conservative policy archives every valid case. Zero incorrect policy deletions therefore reflects zero deletions, not useful classification. The small synthetic dataset is an engineering check, not a production accuracy estimate.

No prompt or threshold was changed between development and held-out runs. Future tuning needs development examples and fresh held-out evaluation.

## Local performance

The ordinary cases used roughly 180–275 tokens: warm median inference was about **0.21 seconds**, with p95 about **0.27 seconds**. Loading and verifying the model took **26–32 seconds**. Peak process memory was about **3.6 GiB**. A complete development run succeeded with network connections blocked after downloading the model.

A separate scaling experiment repeated synthetic reference text to fill each budget. Each size had one warmup and three timed calls:

| Actual input tokens | Median inference |
| ---: | ---: |
| 507 | 0.49 s |
| 1,017 | 1.12 s |
| 2,037 | 3.08 s |
| 4,092 | 10.10 s |

Peak memory reached about **4.5 GiB** during the 4,092-token experiment. These timings exclude Gmail requests and model download. They measure this machine and repeated synthetic text, not typical inbox throughput or Modal performance.

Local disk usage was roughly **0.8 GiB for model files**, **0.7 GiB for the Python environment**, and **0.8 GiB for installation caches**. A packaged desktop application has not been built or measured.

## Reproduce

Follow [Run Laya](development.md#run-laya), then use `--split held_out` for the second split. Keep the pinned dependencies and default question, context and threshold. Full local results are saved under `reports/development-baseline/` and `reports/held-out-baseline/`; those generated files are ignored by Git. The scaling experiment is recorded locally in `reports/context-scaling.json` with its method and input pattern.
