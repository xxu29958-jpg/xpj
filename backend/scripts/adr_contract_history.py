"""Immutable history fingerprints for accepted schema-v2 ADRs."""

from __future__ import annotations

import hashlib
import json

HISTORY_FINGERPRINT_VERSION = "adr-history-v2"


def history_fingerprint(
    *,
    adr_id: str,
    title: str,
    decision_date: str,
    summary: str,
    current_scope: str,
    relations: tuple[tuple[str, str, str], ...],
    body: str,
) -> str:
    """Hash semantic front matter and the complete body, including evidence.

    Structural parsing deliberately hides fenced code so example headings cannot
    satisfy the schema.  History preservation has the opposite requirement: a
    wire contract, state machine, command, or receipt inside a fence is still
    accepted history and must not be rewritten in place.
    """

    payload = {
        "algorithm": HISTORY_FINGERPRINT_VERSION,
        "id": adr_id,
        "title": title,
        "date": decision_date,
        "summary": summary,
        "current_scope": current_scope,
        "relations": relations,
        "body": body,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return f"{HISTORY_FINGERPRINT_VERSION}:{digest}"
