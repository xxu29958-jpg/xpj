"""Closed evidence for a bounded cleanup of frozen attachment references."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _explicit_instant(value):
    if not isinstance(value, (str, datetime)) or (
        isinstance(value, str) and not re.search(r"(Z|[+-][0-9]{2}:[0-9]{2})$", value)
    ):
        raise ValueError("cleanup evidence requires an explicit aware timestamp")
    return value


UtcInstant = Annotated[
    AwareDatetime, BeforeValidator(_explicit_instant), AfterValidator(lambda value: value.astimezone(UTC)),
]


class CleanupFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    reference: str = Field(strict=True, min_length=1, max_length=500)
    outcome: Literal["pending", "deleted", "cancelled"] = "pending"
    completed_at: UtcInstant | None = None
    error_code: Literal["unlink_failed", "invalid_reference"] | None = None

    @model_validator(mode="after")
    def completion_matches_outcome(self):
        if (self.outcome == "pending") != (self.completed_at is None):
            raise ValueError("only completed cleanup items have a completion timestamp")
        if self.outcome != "pending" and self.error_code is not None:
            raise ValueError("only pending cleanup items have a retry error")
        return self


class CleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    request_id: UUID
    reason: Literal["after_confirm", "confirmed_retention", "rejected_retention"]
    requested_at: UtcInstant
    image: CleanupFile | None = None
    thumbnail: CleanupFile | None = None

    @model_validator(mode="after")
    def has_frozen_reference(self):
        if self.image is None and self.thumbnail is None:
            raise ValueError("cleanup requests require at least one frozen reference")
        return self


# PostgreSQL checks the canonical serialized shape even for writers bypassing ORM
# validation. The timestamp check is lexical; the typed boundary parses instants.
_UTC_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|\+00:00)$"
_UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _file_shape_sql(field):
    item = f"(attachment_cleanup_request -> '{field}')"
    return f"""CASE WHEN {item} = 'null'::jsonb THEN TRUE
        WHEN jsonb_typeof({item}) = 'object' THEN
            {item} ?& ARRAY['reference', 'outcome', 'completed_at', 'error_code']
            AND {item} - ARRAY['reference', 'outcome', 'completed_at', 'error_code'] = '{{}}'::jsonb
            AND jsonb_typeof({item} -> 'reference') = 'string'
            AND char_length({item} ->> 'reference') BETWEEN 1 AND 500
            AND {item} ->> 'outcome' IN ('pending', 'deleted', 'cancelled')
            AND CASE WHEN {item} ->> 'outcome' = 'pending' THEN
                {item} -> 'completed_at' = 'null'::jsonb
                AND ({item} -> 'error_code' = 'null'::jsonb
                     OR {item} ->> 'error_code' IN ('unlink_failed', 'invalid_reference'))
            ELSE jsonb_typeof({item} -> 'completed_at') = 'string'
                AND {item} ->> 'completed_at' ~ '{_UTC_PATTERN}'
                AND {item} -> 'error_code' = 'null'::jsonb END
        ELSE FALSE END"""


ATTACHMENT_CLEANUP_REQUEST_CHECK_SQL = f"""attachment_cleanup_request IS NULL OR COALESCE(
    CASE WHEN jsonb_typeof(attachment_cleanup_request) = 'object' THEN
        attachment_cleanup_request ?& ARRAY['request_id', 'reason', 'requested_at', 'image', 'thumbnail']
        AND attachment_cleanup_request - ARRAY['request_id', 'reason', 'requested_at', 'image', 'thumbnail'] = '{{}}'::jsonb
        AND jsonb_typeof(attachment_cleanup_request -> 'request_id') = 'string'
        AND attachment_cleanup_request ->> 'request_id' ~ '{_UUID_PATTERN}'
        AND attachment_cleanup_request ->> 'reason' IN ('after_confirm', 'confirmed_retention', 'rejected_retention')
        AND jsonb_typeof(attachment_cleanup_request -> 'requested_at') = 'string'
        AND attachment_cleanup_request ->> 'requested_at' ~ '{_UTC_PATTERN}'
        AND (attachment_cleanup_request -> 'image' <> 'null'::jsonb
             OR attachment_cleanup_request -> 'thumbnail' <> 'null'::jsonb)
        AND ({_file_shape_sql('image')}) AND ({_file_shape_sql('thumbnail')})
    ELSE FALSE END, FALSE)"""
