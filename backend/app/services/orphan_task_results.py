"""Public observations of local orphan maintenance never contain storage paths."""

INSPECT_ORPHANS = "orphan_inspection"
DISPOSE_ORPHANS = "orphan_disposal"
ORPHAN_TASK_TYPES = frozenset({INSPECT_ORPHANS, DISPOSE_ORPHANS})


def public_task_result(task_type: str, result: dict) -> dict:
    if task_type not in ORPHAN_TASK_TYPES:
        return result
    return {key: value for key, value in result.items() if key not in {"_candidates", "_outcomes"}}
