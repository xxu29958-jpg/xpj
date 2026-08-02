"""Pure tag-text normalization shared by schemas and persistence services."""

from __future__ import annotations

import re

TAG_SEPARATOR_RE = re.compile(r"[,，;；\n]+")
TAG_SPACE_RE = re.compile(r"\s+")
MAX_TAG_STORAGE_LENGTH = 64


def clean_tag_name(value: str | None) -> str:
    if value is None:
        return ""
    return TAG_SPACE_RE.sub(" ", value.strip()).strip()


def tag_key(value: str | None) -> str:
    return clean_tag_name(value).casefold()


def parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for raw in TAG_SEPARATOR_RE.split(value):
        name = clean_tag_name(raw)
        key = tag_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        tags.append(name)
    return tags


def validate_tags_fit_storage(value: str | None) -> str | None:
    """Reject a tag whose normalized name or lookup key exceeds VARCHAR(64)."""

    for name in parse_tags(value):
        if (
            len(name) > MAX_TAG_STORAGE_LENGTH
            or len(tag_key(name)) > MAX_TAG_STORAGE_LENGTH
        ):
            raise ValueError("单个标签标准化后最多 64 个字符")
    return value
