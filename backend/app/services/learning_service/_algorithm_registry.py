"""v1.2 follow-up — small registry for algorithm types.

ADR-0037 originally called out that ``decision_type`` and ``algorithm_version`` were
scattered as string constants across each suggestion service
(``"category_suggestion"`` in ``pending_suggestion_service``,
``ALGORITHM_VERSION = "category-history-v1"`` in
``_category_suggestion``, the same string repeated in tests, ...).
This module collapses them into one place.

Why this matters:

* No more silent typos. ``"catgory_suggestion"`` won't quietly write a
  row alongside the real ``"category_suggestion"`` rows.
* Listing live algorithm types is a function call, not a grep. Owner
  Console / future migration tools can enumerate them.
* When a service rolls a new algorithm version (``v1`` → ``v2``), the
  bump happens in *one* place; consumers (suggestion writer, model
  versioning UI, audit) all pick it up.

The registry is intentionally **flat** — frozen dataclasses + a dict.
No metaclass, no plugin discovery, no auto-registration. Adding a new
algorithm = add a new module-level constant + reference it from the
service module. The :func:`get` lookup raises on unknown types so the
caller fails fast instead of silently writing a row with a typo'd
``decision_type``.

Each entry carries enough metadata for the rest of the v1.2 layer to
work off the registry without hardcoding:

* ``display_label`` — what Owner Console shows the user instead of the
  internal snake_case identifier.
* ``default_retention_days`` — what a fresh ``algorithm_decisions``
  row gets if the writer doesn't override. Mirrors retention defaults
  from the v1.2 cleanup story.
* ``marker_keys`` — which fields of an algorithm's decision payload
  form the canonical "what was suggested" marker. Two different
  decisions whose marker_keys produce equal sub-dicts represent the
  same advice; the marker is what we hash to query "has the user
  rejected this advice before?" in O(index) instead of LIKE-scanning
  JSON text.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeAlias

from app.services._json_types import JsonObject, JsonValue
from app.services.duplicate_evidence import ALGORITHM_VERSION as DUPLICATE_VERSION

__all__ = [
    "ALGORITHM_TYPES",
    "AlgorithmType",
    "BUDGET_SUGGESTION",
    "CATEGORY_SUGGESTION",
    "DUPLICATE_CANDIDATE",
    "build_feedback_marker",
    "canonical_marker_hash",
    "get",
]

AlgorithmPayload: TypeAlias = Mapping[str, JsonValue]
AlgorithmMarker: TypeAlias = JsonObject


@dataclass(frozen=True)
class AlgorithmType:
    """One algorithm-type registration.

    ``marker_keys`` is the small set of payload fields that uniquely
    identify "what advice was given" for feedback de-duplication. For
    ``category_suggestion`` that's just ``("category",)`` — two
    different rationale strings for the same category are the same
    suggestion. For ``duplicate_candidate`` it's
    ``("amount_cents", "merchant")`` — same money to same merchant is
    the same proposed dup, regardless of the time-bucket reason.

    Retention defaults distinguish three lifecycle states:

    * ``default_retention_days`` — the fresh ``active`` row's
      retention; applies until the row hits a terminal status.
    * ``accepted_retention_days`` — once the user accepts the
      suggestion, the row stays around this long (typically *longer*
      than the default — accept is a positive signal worth keeping
      for the next algorithm version to learn from).
    * ``dismissed_retention_days`` — once the user dismisses (or the
      subject's lifecycle ends), the row stays around this long
      (typically shorter — we don't need long history of "user said
      no" once the next algorithm pass has settled).
    """

    decision_type: str
    current_version: str
    display_label: str
    description: str
    subject_kinds: tuple[str, ...]
    default_retention_days: int = 180
    accepted_retention_days: int = 365
    dismissed_retention_days: int = 90
    marker_keys: tuple[str, ...] = field(default_factory=tuple)

    def retention_for_status(self, status: str) -> int:
        """Return the retention window appropriate for ``status``.

        ``active`` and any other / unknown status falls back to the
        type's ``default_retention_days``.
        """

        if status == "accepted":
            return self.accepted_retention_days
        if status == "dismissed":
            return self.dismissed_retention_days
        return self.default_retention_days

    def build_marker(self, payload: AlgorithmPayload) -> AlgorithmMarker | None:
        """Reduce a decision payload to its canonical marker.

        Returns ``None`` when the type has no ``marker_keys`` (e.g.
        budget suggestions don't currently take per-suggestion
        feedback). Otherwise returns a dict with exactly those keys —
        callers JSON-encode it and hash via
        :func:`canonical_marker_hash`.
        """

        if not self.marker_keys:
            return None
        return {key: payload.get(key) for key in self.marker_keys}


CATEGORY_SUGGESTION = AlgorithmType(
    decision_type="category_suggestion",
    current_version="category-history-v2",
    display_label="分类建议",
    description="参考同一商家近 180 天已入账记录；最高分类至少有 3 笔支持且没有平票时才建议。90 天内两次有效的不采用反馈会暂停该分类建议。",
    subject_kinds=("expense",),
    default_retention_days=180,
    marker_keys=("category",),
)


DUPLICATE_CANDIDATE = AlgorithmType(
    decision_type="duplicate_candidate",
    current_version=DUPLICATE_VERSION,
    display_label="疑似重复",
    description="对照原件、交易标识、原币金额、商家和交易时间。冲突的记录不作重复候选；选择保留两笔只记住这一对，不影响同商家同金额的其他交易。",
    subject_kinds=("expense",),
    default_retention_days=180,
    marker_keys=("amount_cents", "merchant"),
)


BUDGET_SUGGESTION = AlgorithmType(
    decision_type="budget_suggestion",
    current_version="budget-quantile-v1",
    display_label="预算建议",
    description="在洞察中对照过去 6 个完整月份的分类支出，显示通常水平和较高水平。随账目重新计算，不会自动修改预算。",
    subject_kinds=("expense", "month"),
    default_retention_days=365,
    marker_keys=(),
)


RECOGNITION_TIME_CHOICE = AlgorithmType(
    decision_type="recognition_time_choice",
    current_version="time-case-memory-v1",
    display_label="原件时间选择",
    description="记住你在同类原件中明确选过的位置，仅调整可核对候选的顺序；记账时间改动不自动当作识别标签。",
    subject_kinds=("expense",),
    default_retention_days=0,
    marker_keys=("field", "evidence_public_id"),
)


REPAYMENT_CHOICE = AlgorithmType(
    decision_type="repayment_choice",
    current_version="repayment-case-memory-v1",
    display_label="还款选择记忆",
    description="只参考本人明确选过的对应欠款；来源、欠款或还款事实失效后不再参考，余额仍按真实还款计算。",
    subject_kinds=("repayment_draft",),
    default_retention_days=0,
    marker_keys=("target_debt_public_id",),
)


ALGORITHM_TYPES: dict[str, AlgorithmType] = {
    CATEGORY_SUGGESTION.decision_type: CATEGORY_SUGGESTION,
    DUPLICATE_CANDIDATE.decision_type: DUPLICATE_CANDIDATE,
    BUDGET_SUGGESTION.decision_type: BUDGET_SUGGESTION,
    RECOGNITION_TIME_CHOICE.decision_type: RECOGNITION_TIME_CHOICE,
    REPAYMENT_CHOICE.decision_type: REPAYMENT_CHOICE,
}


def get(decision_type: str) -> AlgorithmType:
    """Return the registry entry for ``decision_type``.

    Raises ``KeyError`` when the type is unregistered — typo'd
    decision_type at write time fails fast instead of silently
    writing a row no consumer knows how to interpret.
    """

    try:
        return ALGORITHM_TYPES[decision_type]
    except KeyError as exc:
        raise KeyError(
            f"unknown algorithm decision_type {decision_type!r}; "
            f"add it to learning_service._algorithm_registry"
        ) from exc


def build_feedback_marker(
    decision_type: str, payload: AlgorithmPayload
) -> AlgorithmMarker | None:
    """Convenience: ``get(decision_type).build_marker(payload)`` without
    the per-call ``get`` boilerplate. Returns ``None`` for types that
    don't define a marker (no feedback-de-dup loop)."""

    return get(decision_type).build_marker(payload)


def canonical_marker_hash(marker: AlgorithmMarker | None) -> str | None:
    """SHA-256 hex of the canonical JSON encoding of ``marker``.

    Canonical means ``sort_keys=True`` and ``ensure_ascii=False``, so
    two callers that pass logically-equal markers always hash equal.
    ``None`` in → ``None`` out — callers store NULL on the row, the
    index becomes a sparse one for hash-having rows.
    """

    if marker is None:
        return None
    encoded = json.dumps(marker, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
