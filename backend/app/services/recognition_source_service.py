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
    # This check also rejects historical/manual text whose block ordering no
    # longer describes the original string. Equal amounts never supply a link.
    supported = {index for index, start, end in evidence_block_spans(fact.raw_text, blocks)
        if any(start < right and left < end for left, right in candidate.get("raw_spans", []))}
    if set(indices) != supported or any(type(index) is not int or index < 0 or index >= len(blocks) for index in indices):
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
