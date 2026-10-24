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
    ([[[0, 20], [40, 20], [40, 30], [0, 30]],
      [[70, 0], [180, 0], [180, 30], [70, 30]]], True),
    ([[[0, 20], [40, 28], [40, 38], [0, 30]],
      [[70, 14], [180, 36], [180, 66], [70, 44]]], True),
])
def test_sloped_receipt_line_membership_preserves_original_evidence(boxes, one_line):
    request = {"image_sha256": "a" * 64, "box": [0, 0, 190, 70]}
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


@pytest.mark.parametrize("region,selected,error", [
    ([224, 261, 577, 307], 0, None),
    ([280, 304, 510, 353], 1, None),
    ([400, 261, 577, 307], None, "ocr_region_incomplete"),
    ([224, 261, 577, 340], None, "ocr_region_incomplete"),
    ([224, 261, 577, 353], None, "ocr_region_invalid"),
    ([224, 300, 577, 307], None, "ocr_region_incomplete"),
])
def test_touching_detector_borders_preserve_the_other_original_line(region, selected, error):
    # Geometry captured from an installed full-line retry: adjacent detector
    # margins overlap although the two visible text lines are separate.
    blocks = [
        {"text": "商户名称", "confidence": 0.98,
         "box": [[239, 262], [565, 262], [565, 307], [239, 307]]},
        {"text": "登记编号", "confidence": 0.99,
         "box": [[291, 304], [497, 306], [497, 352], [290, 350]]},
    ]
    base = {"input_sha256": "a" * 64, "width": 932, "height": 1695, "blocks": blocks}
    left, top, right, bottom = region
    retry = {**base, "region": region, "identity": {}, "timings_ms": {}, "decoding": {},
             "blocks": [{"text": "重读结果", "confidence": 0.95,
                         "box": [[left, top], [right, top], [right, bottom], [left, bottom]]}]}
    original = deepcopy(base)
    request = {"image_sha256": base["input_sha256"], "box": region}
    if error:
        with pytest.raises(AppError) as caught:
            merge_region_evidence(base, retry, request)
        assert caught.value.error == error
    else:
        result = merge_region_evidence(base, retry, request)
        assert result["blocks"][selected] == retry["blocks"][0]
        assert result["blocks"][1 - selected] == original["blocks"][1 - selected]
        assert result["regional_retry"]["previous_blocks"] == [original["blocks"][selected]]
    assert base == original
