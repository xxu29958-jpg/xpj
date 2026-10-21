"""Acquire pinned build inputs and publish a verified, offline OCR bundle."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _filename(entry: dict) -> str:
    name = entry["file"]
    if not name or name in {".", ".."} or any(value in name for value in ("/", "\\", ":")):
        raise ValueError("OCR artifact must have a plain filename")
    return name


def _read_source(source: dict, wheel_models: Path) -> bytes:
    if source["kind"] == "wheel":
        data = (wheel_models / _filename(source)).read_bytes()
    elif source["kind"] == "https":
        url = urllib.parse.urlsplit(source["url"])
        if url.scheme != "https" or url.username or url.password or url.fragment:
            raise ValueError("OCR source must be credential-free HTTPS")
        with urllib.request.urlopen(source["url"], timeout=30) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                raise ValueError("OCR source redirected outside HTTPS")
            data = response.read(source["bytes"] + 1)
    else:
        raise ValueError("Unsupported frozen OCR source")
    if len(data) != source["bytes"] or hashlib.sha256(data).hexdigest() != source["sha256"]:
        raise ValueError("OCR source does not match its pinned bytes")
    return data


def acquire_models(recipe: dict, wheel_models: Path, destination: Path) -> None:
    import yaml

    sources = recipe["distribution"]
    entries = [(entry, sources["models"][role]) for role, entry in recipe["models"].items()]
    entries.append((recipe["dictionary"], sources["dictionary"]))
    for entry, source in entries:
        name = _filename(entry)
        data = _read_source(source, wheel_models)
        if source.get("transform") == "paddle-characters":
            characters = yaml.safe_load(data)["PostProcess"]["character_dict"]
            if not isinstance(characters, list) or not characters or any(
                not isinstance(char, str) or not char or "\n" in char or "\r" in char for char in characters
            ):
                raise ValueError("Official OCR dictionary is not a character sequence")
            data = ("\n".join(characters) + "\n").encode("utf-8")
        elif source.get("transform") is not None:
            raise ValueError("Unsupported frozen OCR transformation")
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Acquired OCR model does not match the runtime recipe")
        (destination / name).write_bytes(data)


def prepare_payload(recipe_path: Path, model_root: Path, output: Path) -> dict:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    entries = [*recipe["models"].values(), recipe["dictionary"]]
    for entry in entries:
        source = model_root / _filename(entry)
        if source.parent.resolve() != model_root.resolve() or _sha256(source) != entry["sha256"]:
            raise ValueError("Offline OCR model does not match the frozen recipe")
    license_entry = recipe.get("distribution", {}).get("license")
    license_path = recipe_path.parent / _filename(license_entry) if license_entry else None
    if license_path is not None and _sha256(license_path) != license_entry["sha256"]:
        raise ValueError("OCR model license does not match its frozen identity")
    destination = output / "models"
    destination.mkdir(parents=True)
    for entry in entries:
        target = destination / entry["file"]
        shutil.copyfile(model_root / entry["file"], target)
        if _sha256(target) != entry["sha256"]:
            raise ValueError("Offline OCR model changed during publication")
    shutil.copyfile(recipe_path, output / "recipe.json")
    if license_path is not None:
        shutil.copyfile(license_path, output / license_path.name)
    manifest = {"schema": 1, "recipe_sha256": _sha256(output / "recipe.json"),
                "models": entries, "source": recipe.get("distribution", "verified local model inputs")}
    (output / "MODEL_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-root", type=Path, help="Already acquired model bytes; still hash-verified")
    args = parser.parse_args()
    if args.model_root is not None:
        prepare_payload(args.recipe, args.model_root, args.output)
        return
    spec = importlib.util.find_spec("rapidocr")
    if spec is None or spec.origin is None:
        raise RuntimeError("The locked OCR wheel is missing")
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="ticketbox-ocr-build-inputs-") as directory:
        acquired = Path(directory)
        acquire_models(recipe, Path(spec.origin).parent / "models", acquired)
        prepare_payload(args.recipe, acquired, args.output)


if __name__ == "__main__":
    main()
