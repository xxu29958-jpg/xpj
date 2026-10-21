"""Offline publication rejects mismatched models before emitting a usable bundle."""

import hashlib
import json

import pytest

from scripts.prepare_ocr_payload import prepare_payload


def _fixture(tmp_path):
    models = tmp_path / "wheel-models"
    models.mkdir()
    entries = {}
    for role, name in (("Det", "det.onnx"), ("Rec", "rec.onnx"), ("dictionary", "keys.txt")):
        data = name.encode()
        (models / name).write_bytes(data)
        entries[role] = {"file": name, "sha256": hashlib.sha256(data).hexdigest()}
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps({"models": {key: entries[key] for key in ("Det", "Rec")},
                                 "dictionary": entries["dictionary"]}), encoding="utf-8")
    return recipe, models, tmp_path / "output"


def test_offline_models_and_recipe_have_exact_published_identity(tmp_path):
    recipe, models, output = _fixture(tmp_path)
    (models / "unselected.onnx").write_bytes(b"not selected")
    manifest = prepare_payload(recipe, models, output)
    assert sorted(path.name for path in (output / "models").iterdir()) == ["det.onnx", "keys.txt", "rec.onnx"]
    assert (output / "recipe.json").read_bytes() == recipe.read_bytes()
    assert manifest["recipe_sha256"] == hashlib.sha256(recipe.read_bytes()).hexdigest()


@pytest.mark.parametrize("failure", ["corrupt", "missing"])
def test_bad_model_cannot_publish_partial_payload(tmp_path, failure):
    recipe, models, output = _fixture(tmp_path)
    target = models / "rec.onnx"
    if failure == "corrupt":
        target.write_bytes(b"bad")
    else:
        target.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        prepare_payload(recipe, models, output)
    assert not output.exists()
