"""Image and evidence boundaries before results may reach a ledger transaction."""

import hashlib
from types import SimpleNamespace

import pytest
from PIL import Image

from ocr_runtime.engine import RapidEngine, _model_file
from ocr_runtime.protocol import OcrRuntimeError


def _image(tmp_path, *, size=(40, 20), orientation=None):
    path = tmp_path / "input.jpg"
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    Image.new("RGB", size).save(path, exif=exif)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _engine(result=None, **limits):
    engine = object.__new__(RapidEngine)
    engine.recipe = {"input_limits": {"bytes": 100000, "pixels": 10000, "side": 1000, **limits},
                     "output_schema": "text-blocks/v1"}
    engine.identity = {"recipe_sha256": "frozen"}
    engine.engine = lambda _: result or SimpleNamespace(img=None, txts=None, scores=None, boxes=None, elapse_list=[])
    return engine


@pytest.mark.parametrize("limits", [{"pixels": 799}, {"side": 39}, {"bytes": 10}])
def test_oversized_image_is_rejected_before_inference(tmp_path, limits):
    path, digest = _image(tmp_path)
    engine = _engine(**limits)
    engine.engine = lambda _: pytest.fail("Unadmitted image reached the inference engine")
    with pytest.raises(OcrRuntimeError, match="ocr_input_limit"):
        engine.recognize(path, digest)


def test_replaced_image_and_non_image_are_rejected(tmp_path):
    path, digest = _image(tmp_path)
    path.write_bytes(b"not an image")
    with pytest.raises(OcrRuntimeError, match="ocr_input_changed"):
        _engine().recognize(path, digest)
    with pytest.raises(OcrRuntimeError, match="ocr_image_invalid"):
        _engine().recognize(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_rotated_empty_image_still_has_an_explicit_coordinate_surface(tmp_path):
    path, digest = _image(tmp_path, orientation=6)
    result = _engine().recognize(path, digest)
    assert (result["width"], result["height"]) == (20, 40)
    assert result["coordinate_space"] == "exif-transposed-pixels"
    assert result["schema"] == "text-blocks/v1" and result["blocks"] == []


@pytest.mark.parametrize("box", [[[0, 0]], [[0, 0], [41, 0], [40, 20], [0, 20]],
                              [[0, 0], [float("nan"), 0], [40, 20], [0, 20]]])
def test_invalid_boxes_cannot_be_published_as_evidence(tmp_path, box):
    path, digest = _image(tmp_path)
    result = SimpleNamespace(img=None, txts=["sample"], scores=[0.9],
                             boxes=SimpleNamespace(tolist=lambda: [box]), elapse_list=[0.1])
    with pytest.raises(OcrRuntimeError, match="ocr_output_invalid"):
        _engine(result).recognize(path, digest)


def test_missing_corrupt_and_escaping_models_are_rejected_without_download(tmp_path):
    entry = {"file": "missing.onnx", "sha256": "untrusted"}
    with pytest.raises(OcrRuntimeError, match="ocr_model_missing"):
        _model_file(tmp_path, entry)
    (tmp_path / "missing.onnx").write_bytes(b"corrupt")
    with pytest.raises(OcrRuntimeError, match="ocr_model_integrity_mismatch"):
        _model_file(tmp_path, entry)
    with pytest.raises(OcrRuntimeError, match="ocr_model_missing"):
        _model_file(tmp_path, {**entry, "file": "../outside.onnx"})


def test_large_jpeg_decodes_within_bound_and_maps_boxes_to_oriented_original(tmp_path):
    path, digest = _image(tmp_path, size=(1600, 1200), orientation=6)
    engine = _engine(bytes=1000000, pixels=2000000, side=2000)
    engine.recipe["decode_limits"] = {"pixels": 150000}
    observed = []

    def recognize(image):
        observed.append(image.size)
        assert image.width * image.height <= 150000
        assert image.getexif().get(274) is None
        width, height = image.size
        return SimpleNamespace(img=None, txts=["corner"], scores=[0.9], elapse_list=[],
            boxes=SimpleNamespace(tolist=lambda: [[[0, 0], [width, 0], [width, height], [0, height]]]))

    engine.engine = recognize
    result = engine.recognize(path, digest)
    assert observed == [(300, 400)]
    assert (result["width"], result["height"]) == (1200, 1600)
    assert result["blocks"][0]["box"] == [[0, 0], [1200, 0], [1200, 1600], [0, 1600]]
    assert result["decoding"] == {"method": "jpeg-dct-draft", "width": 300, "height": 400}


def test_non_reducing_decoder_is_rejected_before_allocating_or_running_inference(tmp_path):
    path = tmp_path / "large.png"
    Image.new("RGB", (1000, 1000)).save(path)
    engine = _engine(pixels=2000000, side=2000)
    engine.recipe["decode_limits"] = {"pixels": 150000}
    engine.engine = lambda _: pytest.fail("Unbounded PNG reached inference")
    with pytest.raises(OcrRuntimeError, match="ocr_input_limit"):
        engine.recognize(path, hashlib.sha256(path.read_bytes()).hexdigest())
