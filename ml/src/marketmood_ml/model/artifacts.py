"""Save and load a released model without pickle, with SHA-256 checksums.

A model folder (ml/models/<version>/) holds:
    model.json     scaler, HMM parameters, label map, feature medians, training range
    surrogate.txt  LightGBM text model used for the explanations
    metrics.json   evaluation results (informational; not needed to run the model)

Loading a pickle can run arbitrary code, so only JSON and LightGBM's text format are used.
The expected checksums come from model_registry (the trust anchor), never from the folder
itself: a changed or missing file is refused with MM-MODEL-001 (SOA F06, TC-ML-08).
Files are written with LF line endings; .gitattributes keeps them LF on Windows too, so
the checksums are the same on every laptop.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from marketmood_ml.common import MM_MODEL_001, MM_MODEL_004, PipelineError
from marketmood_ml.model.hmm import HmmParams, Scaler

MODEL_FILES = ("model.json", "surrogate.txt")
FORMAT_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[4]  # ml/src/marketmood_ml/model -> repository root
MODELS_DIR = REPO_ROOT / "ml" / "models"


@dataclass
class TrainedModel:
    version: str
    config: dict
    features: list
    log_transform: bool
    scaler: Scaler
    hmm: HmmParams
    label_map: dict  # {state index: label}
    medians: list  # raw training median per feature, for the signal direction
    train: dict  # {"start", "end", "rows"}
    seed: int
    log_likelihood: float
    surrogate_text: str
    metrics: dict = field(default_factory=dict)

    def surrogate(self):
        from marketmood_ml.model.explain import load_surrogate

        return load_surrogate(self.surrogate_text)

    def to_json(self):
        doc = {
            "format": FORMAT_VERSION,
            "version": self.version,
            "config": self.config,
            "features": list(self.features),
            "log_transform": self.log_transform,
            "scaler": {"mean": self.scaler.mean.tolist(), "scale": self.scaler.scale.tolist()},
            "hmm": {
                "startprob": self.hmm.startprob.tolist(),
                "transmat": self.hmm.transmat.tolist(),
                "means": self.hmm.means.tolist(),
                "covars": self.hmm.covars.tolist(),
            },
            "label_map": {str(k): v for k, v in sorted(self.label_map.items())},
            "medians": [float(m) for m in self.medians],
            "train": self.train,
            "seed": int(self.seed),
            "log_likelihood": float(self.log_likelihood),
        }
        return _compact_json(doc)

    @classmethod
    def from_files(cls, model_json, surrogate_text, metrics=None):
        doc = json.loads(model_json)
        if doc.get("format") != FORMAT_VERSION:
            raise PipelineError(MM_MODEL_001, f"unsupported model format {doc.get('format')!r}")
        h = doc["hmm"]
        return cls(
            version=doc["version"],
            config=doc["config"],
            features=doc["features"],
            log_transform=doc["log_transform"],
            scaler=Scaler(np.array(doc["scaler"]["mean"]), np.array(doc["scaler"]["scale"])),
            hmm=HmmParams(
                startprob=np.array(h["startprob"]),
                transmat=np.array(h["transmat"]),
                means=np.array(h["means"]),
                covars=np.array(h["covars"]),
            ),
            label_map={int(k): v for k, v in doc["label_map"].items()},
            medians=doc["medians"],
            train=doc["train"],
            seed=doc["seed"],
            log_likelihood=doc["log_likelihood"],
            surrogate_text=surrogate_text,
            metrics=metrics or {},
        )


def artifact_path(folder):
    """Path stored in model_registry: relative to the repository when possible."""
    folder = Path(folder).resolve()
    try:
        return folder.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return folder.as_posix()


def resolve_artifact(path):
    """Inverse of artifact_path(): registry path -> folder on this machine."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_model(model, directory):
    """Write the model folder; return {file name: sha256} for model_registry.

    A released version never changes: if the folder already holds different model files
    (new code or data under the same version name), nothing is written (MM-MODEL-004).
    Rewriting identical files is allowed, so re-running training is harmless.
    """
    out = Path(directory)
    texts = {"model.json": model.to_json(), "surrogate.txt": normalise_text(model.surrogate_text)}
    for name, text in texts.items():
        path = out / name
        if path.is_file() and path.read_bytes() != text.encode("utf-8"):
            raise PipelineError(
                MM_MODEL_004,
                f"{path} already exists with different content; released versions are never "
                "overwritten (train under a new name with mm-train --version)",
            )
    out.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        _write_text(out / name, text)
    _write_text(out / "metrics.json", _compact_json(model.metrics))
    return {name: sha256_file(out / name) for name in MODEL_FILES}


def load_model(directory, expected_checksums):
    """Load a model folder after verifying every file against the registry's checksums."""
    folder = Path(directory)
    if set(expected_checksums) != set(MODEL_FILES):
        raise PipelineError(
            MM_MODEL_001, f"registry lists files {sorted(expected_checksums)}, expected {list(MODEL_FILES)}"
        )
    for name in MODEL_FILES:
        path = folder / name
        if not path.is_file():
            raise PipelineError(MM_MODEL_001, f"model file missing: {path}")
        actual = sha256_file(path)
        if actual != expected_checksums[name]:
            raise PipelineError(
                MM_MODEL_001,
                f"checksum mismatch for {path} (expected {expected_checksums[name][:12]}..., "
                f"got {actual[:12]}...); refusing to run",
            )
    metrics_path = folder / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.is_file() else {}
    return TrainedModel.from_files(
        (folder / "model.json").read_text(encoding="utf-8"),
        (folder / "surrogate.txt").read_text(encoding="utf-8"),
        metrics,
    )


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def normalise_text(text):
    """LF endings, no trailing spaces, one final newline (what the pre-commit hooks enforce)."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


def _compact_json(doc):
    """Indented JSON with short numeric lists kept on one line (readable diffs, small files)."""
    text = json.dumps(doc, indent=2, sort_keys=False, allow_nan=False)
    number = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
    pattern = re.compile(r"\[\s*(" + number + r"(?:,\s*" + number + r")*)\s*\]")
    text = pattern.sub(lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]", text)
    return text + "\n"
