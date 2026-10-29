"""Project only the exact OCR blocks supporting a candidate's original spans."""
import json
import math

from pydantic import ValidationError

from app.schemas._recognition_source import RecognitionSourceLocation, RecognitionTextLine, RecognitionTextLines
from app.services.receipt_parse_candidates import evidence_block_spans


def candidate_source_location(fact, candidate: dict) -> RecognitionSourceLocation | None:
    if getattr(fact, "source", "image") != "image" or not fact.evidence_json:
        return None
    evidence = json.loads(fact.evidence_json)
    blocks = evidence.get("blocks", [])
    indices = candidate.get("block_indices", [])
    if not indices or not blocks:
        return None
    if not _candidate_matches_blocks(fact.raw_text, blocks, indices, candidate.get("raw_spans", [])):
        return None
    return _source_location(evidence, indices)


def original_text_lines(fact, image_sha256: str | None) -> RecognitionTextLines | None:
    """Read original OCR lines even when the parser found no field candidate."""
    if fact is None or getattr(fact, "source", "image") != "image" or not fact.evidence_json:
        return None
    evidence = json.loads(fact.evidence_json)
    if evidence.get("input_sha256") != image_sha256:
        return None
    blocks = evidence.get("blocks", [])
    indices = [index for index, _, _ in evidence_block_spans(fact.raw_text, blocks)]
    location = _source_location(evidence, indices) if indices else None
    if location is None:
        return None
    lines = []
    for index, box in zip(indices, location.boxes, strict=True):
        xs, ys = zip(*box, strict=True)
        rectangle = (math.floor(min(xs)), math.floor(min(ys)), math.ceil(max(xs)), math.ceil(max(ys)))
        if rectangle[0] < rectangle[2] and rectangle[1] < rectangle[3]:
            lines.append(RecognitionTextLine(text=blocks[index]["text"].strip(), box=rectangle))
    return RecognitionTextLines(evidence_public_id=fact.public_id, **location.model_dump(exclude={"boxes"}), lines=lines)


def _source_location(evidence: dict, indices: list) -> RecognitionSourceLocation | None:
    blocks = evidence.get("blocks", [])
    try:
        location = RecognitionSourceLocation(image_sha256=evidence.get("input_sha256"),
            width=evidence.get("width"), height=evidence.get("height"),
            coordinate_space=evidence.get("coordinate_space"), boxes=[blocks[index].get("box") for index in indices])
    except ValidationError:
        return None
    if any(not (0 <= x <= location.width and 0 <= y <= location.height)
            for box in location.boxes for x, y in box):
        return None
    return location


def _candidate_matches_blocks(raw_text: str, blocks: list, indices: list, spans: list) -> bool:
    # Reject historical/manual text whose ordering no longer describes the
    # original string. Equal amounts never supply a source link.
    supported = {index for index, start, end in evidence_block_spans(raw_text, blocks)
        if any(start < right and left < end for left, right in spans)}
    return set(indices) == supported and all(type(index) is int and 0 <= index < len(blocks) for index in indices)
