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

- Surface: Android Compose root screens, especially `StatsScreen`.
- Status: active cleanup in the Android IA/UIUX slice.
- Debt: visual-control logic had started to accumulate inside root screen files,
  making the page behave like a god object and tripping detekt
  `TooManyFunctions` / `LongParameterList` while also weakening product-level IA.
- Desired cleanup: keep root screens responsible for page flow only; move dense
  top controls, chart renderers, item rows, and settings sections into focused
  components with resource-backed copy and testable inputs.

- Surface: Android detekt Gray Debug analysis.
- Status: registered follow-up.
- Debt: detekt still reports "34 compiler errors found during analysis" even
  when Kotlin compilation succeeds, reducing confidence in type-resolution
  findings and making visual-slice validation noisier.
- Desired cleanup: investigate the detekt classpath/type-resolution setup so
  successful builds do not emit stale compiler-analysis warnings.

- Surface: Android `LedgerRepository` invitation validation and repository error
  messages.
- Status: registered follow-up after the Join Family secondary-page slice.
- Debt: the UI/VM slice now resolves known ledger roles through resources, but
  `LedgerRepository.acceptInvitation` still throws several Chinese validation
  strings directly. Those can surface through `Throwable.toUiText(...)` as raw
  messages, which violates the resource-backed copy rule if left as the normal
  product path.
- Desired cleanup: migrate invitation validation failures to structured error
  codes or `UiText`-friendly repository errors in a focused repository/error
  contract slice, then update ViewModel tests for preview, accept, and invalid
  input failures.
