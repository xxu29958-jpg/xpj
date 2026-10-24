"""A sloped receipt's lines must not collapse into one amount suggestion."""

from copy import deepcopy

import pytest

from app.errors import AppError
from app.services.ocr_region_service import merge_region_evidence


@pytest.mark.parametrize("boxes,one_line", [
    ([[[0, 0], [100, 20], [100, 30], [0, 10]],
      [[0, 20], [100, 40], [100, 50], [0, 30]]], False),
    ([[[0, 30], [100, 10], [100, 20], [0, 40]],
      [[0, 50], [100, 30], [100, 40], [0, 60]]], False),
    ([[[0, 0], [40, 8], [40, 18], [0, 10]],
      [[100, 20], [140, 28], [140, 38], [100, 30]]], True),
])
def test_sloped_receipt_line_membership_preserves_original_evidence(boxes, one_line):
    request = {"image_sha256": "a" * 64, "box": [0, 0, 160, 65]}
    texts = ("实付", "80.00") if one_line else ("实付 80.00", "优惠 20.00")
    blocks = [{"text": text, "box": box, "confidence": 0.9}
              for text, box in zip(texts, boxes, strict=True)]
    base = {"input_sha256": request["image_sha256"], "width": 200, "height": 100,
            "blocks": blocks + [{"text": "下一笔交易", "confidence": 0.9,
                                 "box": [[0, 80], [100, 80], [100, 95], [0, 95]]}]}
    retry = {**base, "region": request["box"], "identity": {}, "timings_ms": {}, "decoding": {},
             "blocks": [{"text": "实付 80.00", "confidence": 0.9,
                         "box": [[0, 0], [160, 0], [160, 65], [0, 65]]}]}
    original = deepcopy(base)
    if one_line:
        result = merge_region_evidence(base, retry, request)
        assert result["blocks"] == retry["blocks"] + original["blocks"][-1:]
        assert result["regional_retry"]["previous_blocks"] == original["blocks"][:2]
    else:
        with pytest.raises(AppError) as caught:
            merge_region_evidence(base, retry, request)
        assert caught.value.error == "ocr_region_invalid"
    assert base == original
