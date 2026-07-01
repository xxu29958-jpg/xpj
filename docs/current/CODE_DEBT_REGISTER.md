# Code Debt Register

This register tracks non-product code/documentation debt found during delivery.
It is for scoped cleanup commitments that are too broad to mix into an active
feature slice without raising risk.

## CODE-2026-07-01

- Surface: `backend/scripts/codebase_audit_gate.py` baseline provenance comments.
- Status: registered follow-up; the current tail baseline comment has been kept
  short so the file does not accrue more of the same debt.
- Debt: older baseline comments are extremely long and include mojibake in parts,
  making review, patch anchoring, and audit maintenance harder than necessary.
- Desired cleanup: move historical provenance into a compact changelog table or
  ADR-backed notes, keep the executable gate file focused on active baselines and
  short current deltas, and preserve the strict counter values without changing
  audit semantics.
