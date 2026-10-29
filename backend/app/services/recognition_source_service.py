"""Project only the exact OCR blocks supporting a candidate's original spans."""
import json

from pydantic import ValidationError

from app.schemas._recognition_source import RecognitionSourceLocation
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
