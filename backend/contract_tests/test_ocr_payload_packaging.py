"""Offline publication rejects mismatched models before emitting a usable bundle."""

import hashlib
import json

import pytest

from scripts import prepare_ocr_payload as publication
from scripts.prepare_ocr_payload import acquire_models, prepare_payload


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


def test_selected_region_model_is_required_for_a_complete_bundle(tmp_path):
    recipe_path, models, output = _fixture(tmp_path)
    recipe = json.loads(recipe_path.read_text())
    model = {"file": "region.onnx", "sha256": hashlib.sha256(b"regional").hexdigest()}
    recipe["region_recognition"] = {"model": model, "dictionary": recipe["dictionary"]}
    recipe_path.write_text(json.dumps(recipe))
    with pytest.raises(FileNotFoundError):
        prepare_payload(recipe_path, models, output)
    assert not output.exists()
    (models / model["file"]).write_bytes(b"regional")
    manifest = prepare_payload(recipe_path, models, output)
    assert (output / "models/region.onnx").read_bytes() == b"regional"
    assert model in manifest["models"]


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


def test_official_dictionary_is_canonical_utf8_and_models_keep_pinned_bytes(tmp_path):
    wheel = tmp_path / "wheel"
    wheel.mkdir()
    dictionary_source = b'PostProcess:\n  character_dict: ["A", "B"]\n'
    (wheel / "det.onnx").write_bytes(b"detector")
    (wheel / "inference.yml").write_bytes(dictionary_source)
    model = {"file": "det.onnx", "sha256": hashlib.sha256(b"detector").hexdigest()}
    dictionary = {"file": "keys.txt", "sha256": hashlib.sha256(b"A\nB\n").hexdigest()}
    def source(name, data):
        return {"kind": "wheel", "file": name, "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}
    recipe = {"models": {"Det": model}, "dictionary": dictionary, "distribution": {
        "models": {"Det": source("det.onnx", b"detector")},
        "dictionary": dict(source("inference.yml", dictionary_source), transform="paddle-characters")}}
    target = tmp_path / "acquired"
    target.mkdir()
    acquire_models(recipe, wheel, target)
    assert (target / "keys.txt").read_bytes() == b"A\nB\n"
    assert (target / "det.onnx").read_bytes() == b"detector"
    (wheel / "det.onnx").write_bytes(b"changed model")
    with pytest.raises(ValueError, match="pinned bytes"):
        acquire_models(recipe, wheel, target)


def test_pinned_download_rejects_truncation_and_changed_bytes(tmp_path, monkeypatch):
    class Response:
        data = b"model"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def geturl(self):
            return "https://publisher.example/model"

        def read(self, limit):
            assert limit == 6
            return self.data

    response = Response()
    monkeypatch.setattr(publication.urllib.request, "urlopen", lambda *args, **kwargs: response)
    source = {"kind": "https", "url": response.geturl(), "bytes": 5,
        "sha256": hashlib.sha256(b"model").hexdigest()}
    assert publication._read_source(source, tmp_path) == b"model"
    for data in (b"mode", b"other", b"model!"):
        response.data = data
        with pytest.raises(ValueError, match="pinned bytes"):
            publication._read_source(source, tmp_path)


def test_model_license_is_verified_before_publication(tmp_path):
    recipe, models, output = _fixture(tmp_path)
    license_path = tmp_path / "MODEL_LICENSE.txt"
    license_path.write_bytes(b"publisher license")
    value = json.loads(recipe.read_text())
    value["distribution"] = {"license": {"file": license_path.name,
        "sha256": hashlib.sha256(license_path.read_bytes()).hexdigest()}}
    recipe.write_text(json.dumps(value), encoding="utf-8")
    manifest = prepare_payload(recipe, models, output)
    assert (output / license_path.name).read_bytes() == license_path.read_bytes()
    assert manifest["source"]["license"] == value["distribution"]["license"]
    license_path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="license"):
        prepare_payload(recipe, models, tmp_path / "second")
    assert not (tmp_path / "second").exists()
