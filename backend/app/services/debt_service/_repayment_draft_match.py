"""ADR-0049 §杠杆③ slice 3b — ephemeral suggested-Debt match for a captured repayment.

A pending :class:`RepaymentDraft` (an NLS-captured "还款成功") is UNLINKED: slice 3a
leaves the user to pick the target Debt at confirm time. Slice 3b adds a server-computed
*suggestion* — which open external/manual Debt this repayment most likely pays down — so
the inbox can pre-select it.

The suggestion is RECOMPUTED on every list (§8: a suggestion is not a fact). It is NEVER
stored on the draft: a Debt suggested when the notification was captured can be cleared /
voided / created by the time the user reviews, so a stored snapshot would go stale — the
very failure mode the §6 projection-honesty work fights. The user's confirm is still the
authoritative act; the suggestion only pre-selects.

Match axes (counterparty_label + amount):

* Candidate set = the same open external/manual Debt the inbox picker offers — mirrors
  ``guard_direct_fact_writable`` (external + manual) and the Android ``isRepayableDebt``
  (open). A member / bill_split / voided / cleared Debt is never suggested, so a suggested
  ``public_id`` is always something the user could also pick manually.
* Feasibility = ``amount_cents <= remaining_amount_cents``. ``record_repayment`` rejects an
  over-remaining repayment (``debt_overpay_rejected`` 422), so an infeasible Debt is never
  suggested — a pre-selected suggestion never 422s on a one-tap confirm.
* Label match = the captured ``merchant_label`` — a short platform keyword the parser
  anchors (花呗 / 借呗 / 白条 / 美团月付 / 信用卡) — is, after a casefold + whitespace
  strip, equal to or a substring of the user's ``counterparty_label`` ("招商信用卡" /
  "京东白条"), in either containment direction.

We suggest only when confident:

1. among the feasible candidates, if exactly one label-matches at the strictly-best
   strength (exact equality beats containment), suggest it;
2. else, only when the captured ``merchant_label`` is blank (the parser anchored no
   platform — label cannot discriminate) AND there is exactly one feasible candidate at
   all, suggest that lone candidate (the only place this repayment can go);
3. else — an ambiguous label match, OR a specific merchant label that matches nothing
   (a hint that points elsewhere must not force a guess onto an unrelated Debt), OR
   several feasible candidates with no label discriminator, OR nothing feasible — make no
   suggestion: the user picks manually (slice-3a behavior).

The ``source`` channel (alipay / jd / ...) is deliberately NOT a match axis: a Debt
carries no structured channel, only a free-text label, and hardcoding a channel→keyword
table is the fragile keyword-seeding ADR work defers — the merchant label the parser
anchors already carries the platform.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ledger_scope import ledger_scoped_select
from app.models import Debt
from app.services.debt_service._fold import compute_remaining

# Label match strength: a strictly-better strength wins; a tie at the best strength is
# ambiguous → no suggestion.
_NO_MATCH = 0
_CONTAINS = 1
_EXACT = 2


@dataclass(frozen=True)
class RepaymentMatchCandidate:
    """A repayable Debt reduced to the fields the matcher needs (folded ``remaining``)."""

    public_id: str
    counterparty_label: str | None
    remaining_amount_cents: int


def list_repayment_match_candidates(
    db: Session, *, tenant_id: str
) -> list[RepaymentMatchCandidate]:
    """Open external/manual Debt in the tenant, folded for ``remaining`` (the picker set).

    SQL prefilters by ``counterparty_type='external'`` / ``source_type='manual'`` and
    excludes the stored ``voided`` latch; the fold then yields ``remaining`` and only
    ``remaining > 0`` rows (= folded ``open``) become candidates. Mirrors the inbox
    picker's ``isRepayableDebt`` so a suggested ``public_id`` is always a Debt the user
    could also pick manually. ``compute_remaining`` is one query per candidate; the
    external/manual Debt set is small (a user's credit cards / loans), so the inbox list
    stays cheap.
    """
    statement = (
        ledger_scoped_select(Debt, tenant_id)
        .where(Debt.counterparty_type == "external")
        .where(Debt.source_type == "manual")
        .where(Debt.status != "voided")
        .order_by(Debt.created_at.asc(), Debt.id.asc())
    )
    candidates: list[RepaymentMatchCandidate] = []
    for debt in db.scalars(statement):
        remaining = compute_remaining(db, debt)
        if remaining <= 0:
            continue  # cleared (folded) — not a repayable target
        candidates.append(
            RepaymentMatchCandidate(
                public_id=debt.public_id,
                counterparty_label=debt.counterparty_label,
                remaining_amount_cents=remaining,
            )
        )
    return candidates


def _normalize_label(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(value.split()).casefold()


def _label_match_strength(merchant: str, label: str) -> int:
    """0 = no match, 1 = containment (either way), 2 = exact, on normalized labels."""
    normalized_merchant = _normalize_label(merchant)
    normalized_label = _normalize_label(label)
    if not normalized_merchant or not normalized_label:
        return _NO_MATCH
    if normalized_merchant == normalized_label:
        return _EXACT
    if normalized_merchant in normalized_label or normalized_label in normalized_merchant:
        return _CONTAINS
    return _NO_MATCH


def suggest_debt_public_id(
    *,
    amount_cents: int,
    merchant_label: str | None,
    candidates: list[RepaymentMatchCandidate],
) -> str | None:
    """Pick the most likely Debt for a captured repayment, or ``None`` when not confident.

    See the module docstring for the confidence policy. Pure over the candidate list, so
    the matcher is exercised in isolation (``test_repayment_draft_match``) without a DB.
    """
    feasible = [c for c in candidates if amount_cents <= c.remaining_amount_cents]
    if not feasible:
        return None

    has_merchant = bool(merchant_label and merchant_label.strip())
    if has_merchant:
        scored = [
            (c, _label_match_strength(merchant_label or "", c.counterparty_label or ""))
            for c in feasible
        ]
        matched = [(c, strength) for c, strength in scored if strength > _NO_MATCH]
        if matched:
            best = max(strength for _, strength in matched)
            top = [c for c, strength in matched if strength == best]
            if len(top) == 1:
                return top[0].public_id
            return None  # ambiguous label match — let the user pick
        # A specific merchant label that matches nothing points elsewhere: do NOT fall
        # through to the lone-candidate guess.
        return None

    # No merchant label to discriminate: suggest only when there is a single feasible target.
    if len(feasible) == 1:
        return feasible[0].public_id
    return None
