"""Publish only recipe-verified offline models from the locked RapidOCR wheel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_payload(recipe_path: Path, model_root: Path, output: Path) -> dict:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    entries = [*recipe["models"].values(), recipe["dictionary"]]
    for entry in entries:
        source = model_root / entry["file"]
        if source.parent.resolve() != model_root.resolve() or _sha256(source) != entry["sha256"]:
            raise ValueError("Offline OCR model does not match the frozen recipe")
    destination = output / "models"
    destination.mkdir(parents=True)
    for entry in entries:
        target = destination / entry["file"]
        shutil.copyfile(model_root / entry["file"], target)
        if _sha256(target) != entry["sha256"]:
            raise ValueError("Offline OCR model changed during publication")
    shutil.copyfile(recipe_path, output / "recipe.json")
    manifest = {"schema": 1, "recipe_sha256": _sha256(output / "recipe.json"),
                "models": entries, "source": "hash-locked rapidocr wheel"}
    (output / "MODEL_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        raise RuntimeError("The locked OCR wheel is missing")
    prepare_payload(args.recipe, Path(spec.origin).parent / "models", args.output)


if __name__ == "__main__":
    main()
