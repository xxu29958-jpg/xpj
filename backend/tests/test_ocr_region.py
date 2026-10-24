"""Region retry preserves source coordinates and never repairs digits by guessing."""

import hashlib
from types import SimpleNamespace

import pytest
from PIL import Image

from ocr_runtime.engine import RapidEngine
from ocr_runtime.protocol import OcrRuntimeError
from ocr_runtime.region import region_blocks, region_image, validate_region


@pytest.mark.parametrize("region", [
    [-1, 0, 100, 20], [0, 0, 101, 20], [0, 0, 100, 81],
    [0, 0, 0, 20], [True, 0, 100, 20], [0.5, 0, 100, 20], [0, 0, 100],
])
def test_invalid_region_cannot_escape_source(region):
    with pytest.raises(OcrRuntimeError, match="ocr_region_invalid"):
        validate_region(region, 100, 80)


def test_region_resource_budget_is_independent_of_full_image_limit():
    with pytest.raises(OcrRuntimeError, match="ocr_region_invalid"):
        validate_region([0, 0, 4096, 512], 8000, 8000)
    assert validate_region([50, 60, 150, 85], 1080, 1920) == (50, 60, 150, 85)


def test_crop_uses_exif_transposed_pixels(tmp_path):
    path = tmp_path / "rotated.png"
    image = Image.new("RGB", (80, 120), "white")
    image.paste((255, 0, 0), (0, 0, 20, 20))
    exif = Image.Exif()
    exif[274] = 6
    image.save(path, exif=exif)
    with region_image(path, [100, 0, 120, 20], (120, 80), {"pixels": 6000000}) as (crop, _):
        assert crop.size == (20, 20) and crop.getpixel((10, 10)) == (255, 0, 0)


def test_retry_has_source_region_identity_and_does_not_rewrite_punctuation(tmp_path):
    path = tmp_path / "line.png"
    Image.new("RGB", (100, 80), "white").save(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    engine = object.__new__(RapidEngine)
    engine.recipe = {"input_limits": {"bytes": 10000, "pixels": 10000, "side": 100},
                     "decode_limits": {"pixels": 10000}, "output_schema": "text-blocks/v1"}
    engine.identity = {"recipe_name": "qualified-region"}
    calls = []

    def recognize(crop, **options):
        calls.append((crop.size, options))
        return SimpleNamespace(txts=["216:75"], scores=[0.93])

    engine.engine = recognize
    result = engine.recognize_region(path, digest, [10, 20, 90, 45])
    assert calls == [((80, 25), {"use_det": False, "use_cls": False, "use_rec": True})]
    assert result["blocks"][0]["text"] == "216:75"
    assert result["blocks"][0]["box"] == [[10, 20], [90, 20], [90, 45], [10, 45]]
    assert result["input_sha256"] == digest and result["region"] == [10, 20, 90, 45]
    path.write_bytes(b"changed")
    with pytest.raises(OcrRuntimeError, match="ocr_input_changed"):
        engine.recognize_region(path, digest, [10, 20, 90, 45])
    assert len(calls) == 1


def test_unreadable_or_invalid_output_does_not_invent_a_candidate():
    assert region_blocks(SimpleNamespace(txts=None, scores=None), [0, 0, 80, 25]) == []
    with pytest.raises(OcrRuntimeError, match="ocr_output_invalid"):
        region_blocks(SimpleNamespace(txts=["1", "2"], scores=[0.9, 0.9]), [0, 0, 80, 25])
