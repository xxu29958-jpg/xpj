"""Repeat one source line while retaining the rest of the immutable OCR evidence."""

import json
from copy import deepcopy

from app.errors import AppError
from app.services.learning_service import read_ocr_facts
from app.services.ocr_service import OcrExtraction, OcrResult
from app.services.ocr_service._providers import _original_snapshot
from app.services.ocr_worker_client import recognize_region_snapshot
from ocr_runtime.protocol import OcrRuntimeError
from ocr_runtime.region import validate_region


def region_base(db, expense, request) -> tuple[str, dict]:
    fact = read_ocr_facts(db, tenant_id=expense.tenant_id, expenses=[expense]).get(expense.id)
    evidence = json.loads(fact.evidence_json) if fact and fact.evidence_json else {}
    if (not evidence.get("blocks") or evidence.get("input_sha256") != request["image_sha256"]
            or expense.image_hash != request["image_sha256"]
            or evidence.get("coordinate_space") != "exif-transposed-pixels"):
        raise AppError("ocr_region_source_unavailable", status_code=409)
    try:
        validate_region(request["box"], evidence["width"], evidence["height"])
    except (KeyError, OcrRuntimeError) as exc:
        raise AppError("ocr_region_invalid", status_code=422) from exc
    if request.get("base_evidence_public_id", fact.public_id) != fact.public_id:
        raise AppError("state_conflict", status_code=409)
    return fact.public_id, evidence


def prepare_region(db, expense, request) -> dict | None:
    if request is None:
        return None
    public_id, _evidence = region_base(db, expense, request)
    return {**request, "base_evidence_public_id": public_id}


def _validate_neighbor_borders(borders, removed, top, bottom) -> None:
    # Adjacent detector boxes can share a narrow top/bottom margin. Retain that
    # neighbour byte-for-byte only when another complete block anchors the crop.
    # Horizontal cuts and a crop wholly inside a block still require adjustment.
    if borders and (not removed or any(
        (lo <= top and bottom <= hi) or min(hi, bottom) - max(lo, top) > (hi - lo) * 0.1
        for lo, hi in borders
    )):
        raise AppError("ocr_region_incomplete", status_code=422)


def _partition_blocks(blocks, region) -> tuple[list, list, int]:
    left, top, right, bottom = region
    retained, removed, borders = [], [], []
    insertion, following = None, None
    for block in blocks:
        xs, ys = zip(*block["box"], strict=True)
        overlap = min(xs) < right and max(xs) > left and min(ys) < bottom and max(ys) > top
        if left <= min(xs) <= max(xs) <= right and top <= min(ys) <= max(ys) <= bottom:
            insertion = len(retained) if insertion is None else insertion
            removed.append(block)
        else:
            if overlap:
                borders.append((min(ys), max(ys)))
            if following is None and min(ys) >= bottom:
                following = len(retained)
            retained.append(block)
    _validate_neighbor_borders(borders, removed, top, bottom)
    position = insertion if insertion is not None else following if following is not None else len(retained)
    return retained, removed, position


def _validate_single_line(blocks) -> None:
    # Compare bands perpendicular to the text direction: sloped neighbouring
    # lines can overlap on the image Y axis without belonging to the same line.
    directions = [(box[1][0] - box[0][0] + box[2][0] - box[3][0],
                   box[1][1] - box[0][1] + box[2][1] - box[3][1])
                  for box in (block["box"] for block in blocks)]
    dx, dy = max(directions, key=lambda direction: direction[0] ** 2 + direction[1] ** 2, default=(1, 0))
    if dx == dy == 0:
        raise AppError("ocr_region_invalid", status_code=422)
    spans = [[-dy * x + dx * y for x, y in block["box"]] for block in blocks]
    # Overlapping detector margins do not make two complete lines one line.
    cores = [(min(span) + (max(span) - min(span)) / 4,
              max(span) - (max(span) - min(span)) / 4) for span in spans]
    if cores and max(lo for lo, _hi in cores) >= min(hi for _lo, hi in cores):
        raise AppError("ocr_region_invalid", status_code=422)


def merge_region_evidence(base, retry, request) -> dict:
    if (retry["input_sha256"] != request["image_sha256"] or retry.get("region") != request["box"]
            or (retry["width"], retry["height"]) != (base["width"], base["height"])):
        raise AppError("ocr_input_changed", status_code=409)
    if not retry["blocks"] or not retry["blocks"][0]["text"].strip():
        raise AppError("ocr_region_no_text", status_code=422)
    retained, removed, position = _partition_blocks(base["blocks"], request["box"])
    _validate_single_line(removed)
    result = deepcopy(base)
    result.pop("field_parse", None)
    result["blocks"] = deepcopy(retained)
    result["blocks"][position:position] = deepcopy(retry["blocks"])
    result["regional_retry"] = {**request, "previous_blocks": deepcopy(removed),
        "identity": retry["identity"], "timings_ms": retry["timings_ms"], "decoding": retry["decoding"]}
    return result


def extract_region(expense, request, base) -> OcrExtraction:
    from app.services.expense_service._ocr import _active_provider_name

    if _active_provider_name() != "rapidocr":
        raise AppError("ocr_runtime_unavailable", status_code=503)
    try:
        with _original_snapshot(expense) as original:
            retry = recognize_region_snapshot(original.path, request["image_sha256"], request["box"])
    except OcrRuntimeError as exc:
        raise AppError(exc.code, status_code=503) from exc
    evidence = merge_region_evidence(base, retry, request)
    text = "\n".join(block["text"].strip() for block in evidence["blocks"] if block["text"].strip())
    scores = [block["confidence"] for block in evidence["blocks"]]
    return OcrExtraction(provider_name="rapidocr", ocr_model=retry["identity"]["recipe_name"],
        result=OcrResult(raw_text=text, confidence=sum(scores) / len(scores), evidence=evidence))
