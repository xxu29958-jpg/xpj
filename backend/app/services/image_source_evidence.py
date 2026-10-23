"""Preserve allowed metadata before sanitation; metadata never establishes a transaction date."""

import hashlib
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image
from pydantic import ValidationError

from app.errors import AppError
from app.schemas.image_source import ImageSourceContext

IMAGE_CONTEXT_HEADER = "X-Ticketbox-Image-Context"
_TIME_ROLES = {"exif_original": "generated", "exif_digitized": "digitized", "exif_modified": "modified",
    "media_store_taken": "catalog_capture", "media_store_modified": "modified"}


def read_image_context(value: str | None, data: bytes) -> ImageSourceContext | None:
    if value is None:
        return None
    try:
        if len(value) > 8192:
            raise ValueError("Image context exceeds the upload contract")
        context = ImageSourceContext.model_validate_json(value)
        if context.upload_sha256 != hashlib.sha256(data).hexdigest():
            raise ValueError("Image context belongs to different upload bytes")
        return context
    except (ValidationError, ValueError) as error:
        raise AppError("invalid_request", status_code=422) from error


def _exif_time(value, offset, origin: str) -> dict | None:
    if not isinstance(value, str):
        return None
    try:
        local = datetime.strptime(value, "%Y:%m:%d %H:%M:%S").isoformat()
        if offset:
            # An invalid offset must not turn into an invented local or UTC time.
            local = datetime.fromisoformat(local + str(offset)).isoformat()
    except ValueError:
        return None
    return {"origin": origin, "value": local, "precision": "second", "role": _TIME_ROLES[origin]}


def original_image_context(data: bytes) -> dict:
    with Image.open(BytesIO(data)) as image:
        exif = image.getexif()
        nested = exif.get_ifd(0x8769) if 0x8769 in exif else {}
        values = {**dict(exif), **nested}
        times = [_exif_time(values.get(tag), values.get(offset), origin) for tag, offset, origin in (
            (0x9003, 0x9011, "exif_original"), (0x9004, 0x9012, "exif_digitized"),
            (0x0132, 0x9010, "exif_modified"))]
        return {"sha256": hashlib.sha256(data).hexdigest(), "width": image.width, "height": image.height,
            "orientation": values.get(0x0112) if isinstance(values.get(0x0112), int) and values[0x0112] in range(1, 9) else None,
            "times": [item for item in times if item is not None]}


def image_source_evidence(original: dict, stored: bytes, client: ImageSourceContext | None) -> dict:
    claimed = client.model_dump(mode="json") if client is not None else None
    if claimed is not None:
        claimed["times"] = [{**item, "role": _TIME_ROLES[item["origin"]]} for item in claimed["times"]]
    with Image.open(BytesIO(stored)) as image:
        return {"schema": "image-source/v1", "scope": "whole_image",
            "time_authority": "metadata_claim_only", "automatic_transaction_anchor": False,
            "received_at": datetime.now(UTC).isoformat(),
            "uploaded": original,
            "stored": {"sha256": hashlib.sha256(stored).hexdigest(), "width": image.width, "height": image.height},
            "server_transform": "privacy_sanitize" if original["sha256"] != hashlib.sha256(stored).hexdigest() else "unchanged",
            "client": claimed}
