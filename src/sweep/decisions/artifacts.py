"""Explicit downloads and integrity checks for one pinned English checkpoint."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen


MODEL_ID = "convaiinnovations/laya"
MODEL_REVISION = "1c5edc17a7acd8701df6fc341c0d179f1c62c982"
SDK_VERSION = "0.3.5"
SDK_REVISION = "573e5b62696ba441230cd6be71d593331b5d23af"
MANIFEST_NAME = "sweep-model-manifest.json"
_MODEL_BASE = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/"


@dataclass(frozen=True)
class Artifact:
    path: str
    url: str
    sha256: str


# Pinned upstream bytes. README preserves the model's Apache-2.0 declaration;
# the SDK repository supplies the complete license text absent from the model repo.
ARTIFACTS = tuple(
    Artifact(path, _MODEL_BASE + path, checksum)
    for path, checksum in (
        ("model.safetensors", "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"),
        ("rl_agent_config.json", "ae287b56bbcf5f8c4f4541ae9dfd00c914c4c48b940b8398c3058af37ba92bbd"),
        ("encoder/config.json", "bf3ab80598fdccf414855a2ce80f22859e4492d06ca8a62ddd1cfb63972f8979"),
        ("tokenizer/tokenizer.json", "6c8aaa9a542084f2457eab775d4eeb51f92a70c0fd9de28d5edb0ddec3c08d30"),
        ("tokenizer/tokenizer_config.json", "50044de60daaa73df97d262e15a40d4faf0160e7d742df64b377877a1320dd12"),
        ("README.md", "33911629d87484754bb755d2118a38626264a9b63bc33ee30131d7564f5560ee"),
    )
) + (
    Artifact(
        "LICENSE.laya",
        f"https://raw.githubusercontent.com/NandhaKishorM/laya/{SDK_REVISION}/LICENSE",
        "a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9",
    ),
)


class ModelArtifactError(RuntimeError):
    """The local checkpoint is incomplete, changed or from another revision."""


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "checkpoint": "english-root",
        "sdk_version": SDK_VERSION,
        "sdk_revision": SDK_REVISION,
        "license": "Apache-2.0",
        "tokenizer_normalization": None,
        "files": {
            artifact.path: {"sha256": artifact.sha256, "source": artifact.url}
            for artifact in ARTIFACTS
        },
    }


def download_model(model_dir: Path) -> dict:
    """Download only required files, checking hashes before installing each one.

    This is the only network operation in the model adapter. Existing verified
    files are reused, so an interrupted download can be rerun explicitly.
    """
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for artifact in ARTIFACTS:
        target = model_dir / artifact.path
        if target.is_file() and _sha256(target) == artifact.sha256:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = Path(output.name)
                digest = hashlib.sha256()
                with urlopen(artifact.url, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
            if digest.hexdigest() != artifact.sha256:
                raise ModelArtifactError(f"Downloaded checksum does not match: {artifact.path}")
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    manifest = _manifest()
    (model_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_model(model_dir: Path) -> dict:
    """Verify pinned source bytes locally, without fetching missing files."""
    model_dir = Path(model_dir)
    try:
        manifest = json.loads((model_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ModelArtifactError(
            "No valid Sweep model manifest; run the explicit --download-model command first."
        ) from error
    if manifest != _manifest():
        raise ModelArtifactError("Model manifest differs from the pinned English checkpoint.")
    for artifact in ARTIFACTS:
        path = model_dir / artifact.path
        if not path.is_file():
            raise ModelArtifactError(f"Required local model file is missing: {artifact.path}")
        if _sha256(path) != artifact.sha256:
            raise ModelArtifactError(f"Local model checksum does not match: {artifact.path}")
    return manifest
