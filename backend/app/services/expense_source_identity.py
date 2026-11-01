"""Reconcile transcription identities within one immutable source, one card at a time."""

import unicodedata


def _card_text(source, spans):
    return "".join(character for start, end in spans
        for character in unicodedata.normalize("NFKC", source[start:end]) if character.isalnum())


def match_source_events(raw_text, events, previous):
    """Punctuation/spacing/absolute offsets do not create another financial event.

    Each previous card may match only once. Equal-price or even identical-text
    siblings retain their distinct identities; unmatched cards are published.
    No amount-only or fuzzy-text suppression is permitted.
    """
    available = sorted(previous, key=lambda row: (row.event_index, row.id))
    matched = {}
    for event in events:
        signature = _card_text(raw_text, event["raw_spans"])
        exact = next((row for row in available if row.event_key == event["id"]), None)
        row = exact or next((row for row in available if signature == _card_text(
            row.evidence["source_text"], row.evidence["raw_spans"])), None)
        if row is not None:
            available.remove(row)
            matched[event["id"]] = row
    return matched
