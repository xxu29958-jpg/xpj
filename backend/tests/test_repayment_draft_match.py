"""ADR-0049 §杠杆③ slice 3b — pure ``suggest_debt_public_id`` matcher unit tests.

The matcher decides which open external/manual Debt a captured repayment most likely pays
down (counterparty_label + amount), or ``None`` when it is not confident. It is pure over a
candidate list, so these exercise the confidence policy in isolation — no DB. The
candidate-query filtering (open / external / manual / tenant-scoped) and the end-to-end
``suggested_debt_public_id`` wiring are pinned in ``test_repayment_drafts.py`` /
``test_repayment_drafts_isolation.py``.
"""

from __future__ import annotations

from app.services.debt_service._repayment_draft_match import (
    RepaymentMatchCandidate,
    suggest_debt_public_id,
)


def _candidate(public_id: str, label: str | None, remaining: int) -> RepaymentMatchCandidate:
    return RepaymentMatchCandidate(
        public_id=public_id, counterparty_label=label, remaining_amount_cents=remaining
    )


def test_unique_feasible_label_match_is_suggested() -> None:
    candidates = [_candidate("huabei", "花呗", 50000), _candidate("baitiao", "京东白条", 30000)]
    assert (
        suggest_debt_public_id(amount_cents=20000, merchant_label="花呗", candidates=candidates)
        == "huabei"
    )


def test_label_containment_either_direction_matches() -> None:
    # The captured merchant keyword is a substring of the user's longer label …
    forward = [_candidate("cmb", "招商银行信用卡", 80000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="信用卡", candidates=forward)
        == "cmb"
    )
    # … and the reverse (a longer captured label containing the short user label) also matches.
    reverse = [_candidate("card", "信用卡", 80000)]
    assert (
        suggest_debt_public_id(
            amount_cents=10000, merchant_label="招商银行信用卡", candidates=reverse
        )
        == "card"
    )


def test_label_match_normalizes_case_and_whitespace() -> None:
    candidates = [_candidate("hb", "huabei", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="HuaBei", candidates=candidates)
        == "hb"
    )
    spaced = [_candidate("hb", "花 呗", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="花呗", candidates=spaced) == "hb"
    )


def test_exact_match_beats_containment_when_disambiguating() -> None:
    # Two feasible candidates both label-match "花呗"; the exact-equality one wins uniquely.
    candidates = [_candidate("contains", "支付宝花呗", 50000), _candidate("exact", "花呗", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="花呗", candidates=candidates)
        == "exact"
    )


def test_ambiguous_equal_strength_label_match_returns_none() -> None:
    # Two candidates equally (exactly) match → not confident which → no suggestion.
    candidates = [_candidate("a", "花呗", 50000), _candidate("b", "花呗", 60000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="花呗", candidates=candidates)
        is None
    )


def test_specific_merchant_with_no_label_match_does_not_fall_through() -> None:
    # A present, specific merchant keyword that matches nothing points elsewhere: do NOT guess
    # the lone unrelated candidate (a 花呗 repayment must not be suggested onto a credit card).
    candidates = [_candidate("card", "招商信用卡", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="花呗", candidates=candidates)
        is None
    )


def test_blank_merchant_with_single_feasible_candidate_is_suggested() -> None:
    # No platform keyword to discriminate, but only one place this repayment can go.
    for merchant in (None, "", "   "):
        candidates = [_candidate("only", "招商信用卡", 50000)]
        assert (
            suggest_debt_public_id(
                amount_cents=10000, merchant_label=merchant, candidates=candidates
            )
            == "only"
        )


def test_blank_merchant_with_multiple_feasible_candidates_returns_none() -> None:
    candidates = [_candidate("a", "招商信用卡", 50000), _candidate("b", "京东白条", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label=None, candidates=candidates)
        is None
    )


def test_infeasible_amount_is_never_suggested() -> None:
    # The only label match cannot absorb the repayment (would 422 over-remaining) → no feasible.
    candidates = [_candidate("huabei", "花呗", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=60000, merchant_label="花呗", candidates=candidates)
        is None
    )


def test_feasibility_filter_precedes_ambiguity() -> None:
    # Two same-label candidates, but only the feasible one survives the remaining≥amount filter,
    # so the label match is unique (not ambiguous) → suggest the feasible one.
    candidates = [_candidate("small", "花呗", 5000), _candidate("big", "花呗", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=20000, merchant_label="花呗", candidates=candidates)
        == "big"
    )


def test_empty_candidates_returns_none() -> None:
    assert suggest_debt_public_id(amount_cents=10000, merchant_label="花呗", candidates=[]) is None


def test_containment_match_can_class_jump_on_multi_keyword_label() -> None:
    # ACCEPTED tradeoff, documented (not a bug): containment matching means a combined-card label
    # carrying TWO platform keywords matches a repayment from EITHER platform. This is bounded by
    # the §8 confirm-is-authoritative override (the user can pick a different Debt via 选其他) and
    # is preferred over a channel→keyword disambiguation table — the fragile keyword-seeding the
    # design deliberately avoids (the source channel is not a match axis). Pinned so a future
    # tightening to "multi-keyword → ambiguous" has a regression anchor.
    candidates = [_candidate("combo", "花呗借呗合并卡", 50000)]
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="花呗", candidates=candidates)
        == "combo"
    )
    assert (
        suggest_debt_public_id(amount_cents=10000, merchant_label="借呗", candidates=candidates)
        == "combo"
    )
