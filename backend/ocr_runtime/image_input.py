"""Bounded decoder surfaces; all evidence remains in source-image coordinates."""

from contextlib import ExitStack, contextmanager
from pathlib import Path

from ocr_runtime.protocol import OcrRuntimeError


def _reduce_jpeg(image, pixel_limit: int) -> str:
    width, height = image.size
    if width * height <= pixel_limit:
        return "original"
    if image.format != "JPEG":
        raise OcrRuntimeError("ocr_input_limit")
    factor = next((value for value in (2, 4, 8)
        if ((width + value - 1) // value) * ((height + value - 1) // value) <= pixel_limit), None)
    if factor is None:
        raise OcrRuntimeError("ocr_input_limit")
    # JPEG DCT scaling happens in the decoder, before a full RGB allocation.
    # draft() is advisory, so verify its actual surface before load/transpose.
    image.draft(image.mode, (max(1, width // factor), max(1, height // factor)))
    if image.width * image.height > pixel_limit:
        raise OcrRuntimeError("ocr_input_limit")
    return "jpeg-dct-draft"


@contextmanager
def inference_image(path: Path, limits: dict | None):
    if limits is None:
        yield str(path), {"method": "original"}
        return
    from PIL import Image, ImageOps, UnidentifiedImageError

    with ExitStack() as resources:
        try:
            image = resources.enter_context(Image.open(path))
            method = _reduce_jpeg(image, limits["pixels"])
            ImageOps.exif_transpose(image, in_place=True)
            image.load()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise OcrRuntimeError("ocr_image_invalid") from exc
        yield image, {"method": method, "width": image.width, "height": image.height}


def source_coordinate_blocks(blocks: list[dict], *, source: tuple[int, int], decoded: tuple[int, int]) -> None:
    if source == decoded:
        return
    scale_x, scale_y = source[0] / decoded[0], source[1] / decoded[1]
    for block in blocks:
        block["box"] = [[x * scale_x, y * scale_y] for x, y in block["box"]]
