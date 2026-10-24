"""A single user-selected text line, bounded in the original image coordinates."""

import math
from contextlib import contextmanager

from ocr_runtime.image_input import inference_image
from ocr_runtime.protocol import OcrRuntimeError


def region_recipe(recipe: dict) -> dict:
    entry = recipe.get("region_recognition")
    if entry is None:
        raise OcrRuntimeError("ocr_runtime_unavailable")
    return {**recipe, "name": entry["name"],
            "models": {"Rec": entry["model"]}, "dictionary": entry["dictionary"],
            "params": {**recipe["params"], **entry["params"],
                       "Global.use_det": False, "Global.use_cls": False}}


def validate_region(region, width: int, height: int) -> tuple[int, int, int, int]:
    if (not isinstance(region, (list, tuple)) or len(region) != 4
            or any(type(value) is not int for value in region)):
        raise OcrRuntimeError("ocr_region_invalid")
    left, top, right, bottom = region
    if not (0 <= left < right <= width and 0 <= top < bottom <= height
            and 4 <= bottom - top <= 512 and 4 <= right - left <= 4096
            and (right - left) * (bottom - top) <= 1048576):
        raise OcrRuntimeError("ocr_region_invalid")
    return left, top, right, bottom


@contextmanager
def region_image(path, region, source_size, limits):
    from PIL import Image

    with inference_image(path, limits) as (surface, decoding):
        if not isinstance(surface, Image.Image):
            raise OcrRuntimeError("ocr_recipe_invalid")
        scale_x, scale_y = surface.width / source_size[0], surface.height / source_size[1]
        left, top, right, bottom = region
        decoded_box = (math.floor(left * scale_x), math.floor(top * scale_y),
                       math.ceil(right * scale_x), math.ceil(bottom * scale_y))
        with surface.crop(decoded_box) as crop:
            yield crop, decoding


def region_blocks(result, region) -> list[dict]:
    texts = list(result.txts) if result.txts is not None else []
    scores = list(result.scores) if result.scores is not None else []
    if len(texts) != len(scores) or len(texts) > 1:
        raise OcrRuntimeError("ocr_output_invalid")
    if not texts:
        return []
    text, score = texts[0], float(scores[0])
    if not isinstance(text, str) or len(text) > 8192 or not math.isfinite(score) or not 0 <= score <= 1:
        raise OcrRuntimeError("ocr_output_invalid")
    left, top, right, bottom = region
    return [{"text": text, "confidence": score,
             "box": [[left, top], [right, top], [right, bottom], [left, bottom]]}]
