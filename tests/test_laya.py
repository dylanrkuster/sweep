"""Model-boundary checks use tiny fake artifacts, never downloaded weights."""

import hashlib
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from sweep.decisions import artifacts
from sweep.decisions import laya


@pytest.fixture
def tiny_artifacts(monkeypatch):
    contents = {"model.safetensors": b"fake weights", "LICENSE.laya": b"test license"}
    records = tuple(
        artifacts.Artifact(path, "https://example.test/" + path, hashlib.sha256(data).hexdigest())
        for path, data in contents.items()
    )
    monkeypatch.setattr(artifacts, "ARTIFACTS", records)
    calls = []

    def open_url(url, *, timeout):
        calls.append(url)
        return io.BytesIO(contents[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(artifacts, "urlopen", open_url)
    return contents, calls


def test_explicit_download_keeps_required_artifacts_and_license(tmp_path, tiny_artifacts):
    contents, calls = tiny_artifacts
    manifest = artifacts.download_model(tmp_path)
    assert len(calls) == len(contents)
    assert {path.name for path in tmp_path.iterdir()} == {*contents, artifacts.MANIFEST_NAME}
    assert manifest["model_revision"] == artifacts.MODEL_REVISION
    assert manifest["checkpoint"] == "english-root"
    assert manifest["tokenizer_normalization"] is None
    assert artifacts.verify_model(tmp_path) == manifest
    assert len(calls) == len(contents)  # Verification is local only.


def test_repeated_explicit_download_reuses_verified_files(tmp_path, tiny_artifacts):
    _, calls = tiny_artifacts
    artifacts.download_model(tmp_path)
    first_calls = len(calls)
    artifacts.download_model(tmp_path)
    assert len(calls) == first_calls


def test_bad_download_cannot_replace_existing_artifact(tmp_path, tiny_artifacts, monkeypatch):
    target = tmp_path / "model.safetensors"
    target.write_bytes(b"previous incomplete download")
    monkeypatch.setattr(artifacts, "urlopen", lambda *args, **kwargs: io.BytesIO(b"wrong bytes"))
    with pytest.raises(artifacts.ModelArtifactError, match="Downloaded checksum"):
        artifacts.download_model(tmp_path)
    assert target.read_bytes() == b"previous incomplete download"
    assert list(tmp_path.iterdir()) == [target]


def test_interrupted_download_leaves_no_temporary_artifact(tmp_path, tiny_artifacts, monkeypatch):
    def fail(*args, **kwargs):
        raise TimeoutError("connection interrupted")

    monkeypatch.setattr(artifacts, "urlopen", fail)
    with pytest.raises(TimeoutError):
        artifacts.download_model(tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("damage", ["remove", "change", "manifest"])
def test_verification_rejects_damaged_checkpoint_without_network(tmp_path, tiny_artifacts, damage):
    _, calls = tiny_artifacts
    artifacts.download_model(tmp_path)
    call_count = len(calls)
    if damage == "remove":
        (tmp_path / "model.safetensors").unlink()
    elif damage == "change":
        (tmp_path / "model.safetensors").write_bytes(b"changed")
    else:
        manifest_path = tmp_path / artifacts.MANIFEST_NAME
        manifest = json.loads(manifest_path.read_text())
        manifest["model_revision"] = "main"
        manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(artifacts.ModelArtifactError):
        artifacts.verify_model(tmp_path)
    assert len(calls) == call_count


def test_missing_model_errors_before_loading_dependencies(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Missing artifacts must not invoke model loading or downloads")

    monkeypatch.setattr(artifacts, "urlopen", unexpected)
    monkeypatch.setattr(laya, "_load_backend", unexpected)
    with pytest.raises(artifacts.ModelArtifactError, match="--download-model"):
        laya.LayaRuntime(tmp_path)


def test_pinned_allowlist_excludes_other_checkpoints_and_includes_license():
    paths = {record.path for record in artifacts.ARTIFACTS}
    assert paths == {
        "model.safetensors", "rl_agent_config.json", "encoder/config.json",
        "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json", "README.md", "LICENSE.laya",
    }
    assert all(artifacts.MODEL_REVISION in record.url or artifacts.SDK_REVISION in record.url
               for record in artifacts.ARTIFACTS)
    assert all(len(record.sha256) == 64 for record in artifacts.ARTIFACTS)


@pytest.fixture
def runtime(monkeypatch):
    calls = []
    loads = []

    def predict(ids, markers):
        calls.append((ids, markers))
        return {"choice": "archive", "probabilities": {"archive": 0.8, "delete": 0.2}}

    backend = SimpleNamespace(
        tokenizer=SimpleNamespace(mask_token_id=3), metadata={"software": {"laya": "0.3.5"}},
        predict=predict,
    )

    def load(path, threads):
        loads.append((path, threads))
        return backend

    monkeypatch.setattr(laya, "verify_model", lambda path: {"model_revision": artifacts.MODEL_REVISION})
    monkeypatch.setattr(laya, "_load_backend", load)
    return laya.LayaRuntime(Path("local-model"), max_tokens=2048, threads=2), calls, loads


def prepared(ids=(1, 6, 2, 3, 8, 3, 9, 2, 15, 2), markers=(3, 5), max_tokens=2048):
    return SimpleNamespace(token_ids=ids, marker_positions=markers, max_tokens=max_tokens)


def test_runtime_reuses_loaded_model_and_forwards_exact_prepared_ids(runtime):
    model, calls, loads = runtime
    item = prepared()
    first = model.predict(item)
    second = model.predict(item)
    assert len(loads) == 1
    assert calls == [(item.token_ids, item.marker_positions)] * 2
    assert first == second
    assert model.metadata["dtype"] == "float32"
    assert model.metadata["device"] == "cpu"
    assert model.load_seconds >= 0


@pytest.mark.parametrize("item", [
    prepared(ids=()),
    prepared(ids=(1, 2, 3) * 1000),
    prepared(ids=(1, True, 2, 3, 8, 3, 9, 2)),
    prepared(ids=(1, -2, 2, 3, 8, 3, 9, 2)),
    prepared(markers=(5, 3)),
    prepared(markers=(3, 3)),
    prepared(markers=(3, 50)),
    prepared(markers=(2, 5)),
    prepared(markers=(True, 5)),
    prepared(max_tokens=5),
])
def test_invalid_sequence_never_reaches_inference(runtime, item):
    model, calls, _ = runtime
    with pytest.raises(ValueError):
        model.predict(item)
    assert calls == []


@pytest.mark.parametrize("kwargs", [{"threads": 0}, {"threads": True}, {"max_tokens": 8193}, {"max_tokens": False}])
def test_invalid_runtime_configuration_fails_before_model_loading(tmp_path, kwargs):
    with pytest.raises(ValueError):
        laya.LayaRuntime(tmp_path, **kwargs)


def test_sdk_tensors_preserve_sequence_and_temperature_scoring():
    torch = pytest.importorskip("torch")
    pytest.importorskip("laya")
    captured = []

    def model(*inputs):
        captured.append(inputs)
        return torch.tensor([[1.0, 3.0]]), torch.tensor([[0.0, 1.0]])

    backend = laya._CpuBackend(model, SimpleNamespace(pad_token_id=0), temperature=2.0, metadata={})
    item = prepared()
    output = backend.predict(item.token_ids, item.marker_positions)
    ids, attention, markers, marker_mask, qtype = captured[0]
    assert ids.tolist() == [list(item.token_ids)]
    assert attention.tolist() == [[1] * len(item.token_ids)]
    assert markers.tolist() == [[3, 5]]
    assert marker_mask.tolist() == [[True, True]]
    assert qtype.tolist() == [0]
    assert output["choice"] == "delete"
    assert output["probabilities"] == {"archive": 0.2689, "delete": 0.7311}
    assert output["act_probability"] == 0.2689
    assert output["input_tokens"] == len(item.token_ids)


def test_context_format_matches_pinned_sdk_beyond_default_512_tokens():
    pytest.importorskip("laya")
    from laya.common import build_sequence
    from sweep.decisions.context import build_context
    from sweep.domain import DecisionInput, Message

    class Tokenizer:
        cls_token_id = 1
        sep_token_id = 2
        mask_token_id = 3
        mask_token = "[MASK]"
        all_special_tokens = ("[CLS]", "[SEP]", "[MASK]")

        def __init__(self):
            self.vocabulary = {}

        def encode(self, text, *, add_special_tokens=False):
            return [self.vocabulary.setdefault(word, len(self.vocabulary) + 4)
                    for word in re.findall(r"\w+|[^\w\s]", text)]

        def __call__(self, text, *, add_special_tokens=False):
            return {"input_ids": self.encode(text, add_special_tokens=add_special_tokens)}

    tokenizer = Tokenizer()
    message = Message("m1", "t1", 1, "sender@example.test", ("user@example.test",),
                      "Receipt", "detail " * 700, frozenset({"UNREAD"}), ())
    context = build_context(DecisionInput("Keep receipts.", message), tokenizer)
    assert len(context.token_ids) > 512
    ids, markers = build_sequence(
        tokenizer, context.state,
        {"t": "choice", "ins": context.question["instructions"], "crit": context.question["criteria"]},
        max_len=context.max_tokens, head_max_len=192,
    )
    assert tuple(ids) == context.token_ids
    assert tuple(markers) == context.marker_positions
