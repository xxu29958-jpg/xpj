"""Amount-only replay comparisons; publisher oracle actions are not user effort."""

from collections import Counter


def summarize(rows: list[dict]) -> dict:
    labeled = [row for row in rows if row["label_state"] != "unlabeled"]
    present = [row for row in rows if row["label_state"] == "present"]
    absent = [row for row in rows if row["label_state"] == "absent"]
    recalled = [row for row in present if row.get("correct_candidate_count", 0) > 0]
    exposed = [row for row in labeled if row.get("memory_suggested")]
    return {"attempted": len(rows), "independent_groups": len({row["group_id"] for row in rows}),
        "outcomes": dict(Counter(row["outcome"] for row in rows)),
        "labeled": len(labeled), "unlabeled": len(rows) - len(labeled),
        "expected_present": len(present), "expected_absent": len(absent),
        "raw_correct": sum(row.get("raw_correct") is True for row in labeled),
        "first_candidate_correct": sum(row.get("candidate_correct") is True for row in labeled),
        "correct_candidate_recalled": len(recalled),
        "correct_candidate_missing": len(present) - len(recalled),
        "correct_candidate_below_first": sum(row.get("candidate_correct") is False for row in recalled),
        "abstained_or_failed": sum(row.get("first_candidate") is None for row in present),
        "wrong_nonempty": sum(row.get("first_candidate") is not None and row.get("candidate_correct") is False for row in present),
        "false_fill": sum(row.get("first_candidate") is not None for row in absent),
        "memory_exposed_labeled": len(exposed),
        "needs_correction_after_memory": sum(row.get("candidate_correct") is False for row in exposed),
        "feedback_events": sum(row.get("feedback", {}).get("events", 0) for row in rows),
        "qualified_feedback": sum(row.get("feedback", {}).get("qualified", 0) for row in rows),
        "withdrawn_feedback": sum(row.get("feedback", {}).get("withdrawn", 0) for row in rows)}


def compare(baseline: list[dict], changed: list[dict]) -> dict:
    if [row["sample"] for row in baseline] != [row["sample"] for row in changed]:
        raise ValueError("comparison arrivals differ")
    pairs = [(left, right) for left, right in zip(baseline, changed, strict=True) if left["label_state"] != "unlabeled"]
    return {"labeled_pairs": len(pairs),
        "repaired": sum(left.get("candidate_correct") is not True and right.get("candidate_correct") is True for left, right in pairs),
        "harmed": sum(left.get("candidate_correct") is True and right.get("candidate_correct") is not True for left, right in pairs),
        "changed_first_candidate": sum(left.get("first_candidate") != right.get("first_candidate") for left, right in pairs)}


def comparison_report(arms: dict[str, dict]) -> dict:
    result = {}
    for split in ("development", "holdout"):
        rows = {mode: [row for row in arm["rows"] if row["split"] == split] for mode, arm in arms.items()}
        result[split] = {"arms": {mode: summarize(values) for mode, values in rows.items()},
            "amount_context_slices": {context: {mode: summarize([row for row in values if row.get("material_context") == context])
                for mode, values in rows.items()} for context in (
                    "seen_development_context", "new_amount_context", "no_comparable_amount_context")},
            "feedback_vs_baseline": compare(rows["baseline"], rows["feedback"]),
            "withdrawn_vs_baseline": compare(rows["baseline"], rows["withdrawn"])}
    return result
