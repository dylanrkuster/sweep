"""CPU inference over the exact sequence prepared by Sweep's context builder.

Laya's model and scoring functions are reused; its high-level prompt builder is
bypassed because it silently truncates inputs. Model libraries load only when a
runtime is constructed, keeping fixture commands and ordinary tests lightweight.
"""

from importlib.metadata import version
import json
from pathlib import Path
import time
from typing import Any, Protocol

from sweep.decisions.artifacts import SDK_VERSION, verify_model


class PreparedInput(Protocol):
    token_ids: tuple[int, ...]
    marker_positions: tuple[int, int]
    max_tokens: int


class LayaRuntime:
    """Load one verified checkpoint once and evaluate one email at a time."""

    def __init__(self, model_dir: Path, max_tokens: int = 2048, threads: int = 2):
        if type(max_tokens) is not int or not 128 <= max_tokens <= 8192:
            raise ValueError("max_tokens must be an integer from 128 through 8192")
        if type(threads) is not int or threads < 1:
            raise ValueError("threads must be a positive integer")
        started = time.perf_counter()
        manifest = verify_model(model_dir)
        self._backend = _load_backend(Path(model_dir), threads)
        self.tokenizer = self._backend.tokenizer
        self.max_tokens = max_tokens
        self.load_seconds = time.perf_counter() - started
        self.metadata = {
            **manifest,
            "device": "cpu",
            "dtype": "float32",
            "threads": threads,
            "max_tokens": max_tokens,
            "load_seconds": self.load_seconds,
            "sequence_execution": "prepared-token-ids-v1",
            **self._backend.metadata,
        }

    def predict(self, prepared: PreparedInput) -> dict[str, Any]:
        ids = tuple(prepared.token_ids)
        markers = tuple(prepared.marker_positions)
        if not ids or len(ids) > min(self.max_tokens, prepared.max_tokens):
            raise ValueError("Prepared sequence is empty or exceeds the configured token budget")
        if any(type(token) is not int or token < 0 for token in ids):
            raise ValueError("Prepared token IDs must be nonnegative integers")
        if (
            len(markers) != 2
            or any(type(marker) is not int or not 0 <= marker < len(ids) for marker in markers)
            or markers[0] >= markers[1]
            or any(ids[marker] != self.tokenizer.mask_token_id for marker in markers)
        ):
            raise ValueError("Prepared sequence must have ordered archive/delete mask markers")
        return self._backend.predict(ids, markers)


def _load_backend(model_dir: Path, threads: int):
    try:
        installed = version("laya")
    except ImportError as error:
        raise RuntimeError("Install model dependencies with uv sync --locked --extra model") from error
    if installed != SDK_VERSION:
        raise RuntimeError(f"Expected laya=={SDK_VERSION}; found {installed}")

    import torch
    from laya.agent import _verify_compatibility
    from laya.common import DecisionModel, clamp_temperature
    from safetensors.torch import load_file
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    torch.set_num_threads(threads)
    cfg = json.loads((model_dir / "rl_agent_config.json").read_text(encoding="utf-8"))
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir / "tokenizer", local_files_only=True, trust_remote_code=False
    )
    encoder_config = AutoConfig.from_pretrained(
        model_dir / "encoder", local_files_only=True, trust_remote_code=False
    )
    encoder_config.reference_compile = False
    encoder = AutoModel.from_config(
        encoder_config, attn_implementation="sdpa", trust_remote_code=False
    )
    model = DecisionModel(encoder, cfg["head_layers"], len(cfg.get("act_costs", {})) + 1)
    weights = load_file(str(model_dir / "model.safetensors"), device="cpu")
    _verify_compatibility(model, cfg, weights, str(model_dir))
    model.load_state_dict(weights, strict=True)
    del weights
    model.to(device="cpu", dtype=torch.float32).eval()
    raw_temperature = cfg.get("temperature_by_options", {}).get(
        "choice:2", cfg.get("temperature", [1.0])[0]
    )
    temperature = clamp_temperature(raw_temperature)
    return _CpuBackend(
        model,
        tokenizer,
        temperature,
        {
            "software": {
                package: version(package)
                for package in ("laya", "torch", "transformers", "safetensors", "numpy")
            },
            "temperature_raw": raw_temperature,
            "temperature_applied": temperature,
            "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        },
    )


class _CpuBackend:
    def __init__(self, model, tokenizer, temperature: float, metadata: dict):
        self.model = model
        self.tokenizer = tokenizer
        self.temperature = temperature
        self.metadata = metadata

    def predict(self, ids: tuple[int, ...], markers: tuple[int, int]) -> dict[str, Any]:
        import numpy as np
        import torch
        from laya.common import collate_items, confidence_from_probs

        batch = collate_items(
            [[{"ids": list(ids), "markers": list(markers), "qtype": 0}]],
            self.tokenizer.pad_token_id,
        )
        # One unpadded question: these are the exact prepared IDs, not a second
        # rendering of the email that could silently change or clip its evidence.
        if batch["input_ids"][0].tolist() != list(ids):
            raise RuntimeError("Laya collation changed the prepared token sequence")
        with torch.inference_mode():
            logits, act = self.model(
                batch["input_ids"],
                batch["attention_mask"],
                batch["marker_pos"],
                batch["marker_mask"],
                batch["qtype"],
            )
        scores = logits.float().cpu().numpy()[0, :2] / self.temperature
        probabilities = np.exp(scores - scores.max())
        probabilities /= probabilities.sum()
        act_probability = torch.softmax(act.float(), -1).cpu().numpy()[0, 0]
        names = ("archive", "delete")
        return {
            "choice": names[int(probabilities.argmax())],
            "probabilities": {
                name: round(float(score), 4) for name, score in zip(names, probabilities)
            },
            "confidence": round(confidence_from_probs(probabilities, 2), 4),
            "act_probability": round(float(act_probability), 4),
            "input_tokens": int(batch["attention_mask"].sum()),
        }
