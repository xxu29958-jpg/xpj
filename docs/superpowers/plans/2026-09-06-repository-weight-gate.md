# Repository Codebase Weight Implementation Plan

> Execute inline with `superpowers:executing-plans` and TDD. Main is the only writer; one bounded read-only reviewer before merge. The Owner has delegated design and implementation, without another approval pause.

**Goal:** After closing #370, deliver one useful whole-repository weight/debt report and CI ratchet, then return to the complete product-capability Goal.

**Architecture:** Read immutable Git blobs for an exact base/head pair. Classify each source file once by module, role and primary language; aggregate transparent source-line metrics. Compare actual snapshot debt, not an editable LOC ceiling. Reuse Ruff and Android's maintained Detekt debt/configuration rather than inventing a cross-language quality score.

**Tech stack:** Python 3.11, Git object reads, pinned Ruff/Pygments/Lizard/PyYAML, the native PowerShell parser and XML baseline parsing. No product runtime changes, databases or local heavy tests.

**Spec:** Owner's 2026-09-06 instructions in this task: production/test separation, migrations included and separately visible, module/language detail, source exclusions, LOC as trend only, and no growth in large-file/complexity/suppression debt.

## Contract and counting decisions

- Base: qualified #370 main `5791d176b3b5a739f3af29f9595c0ae4b28d60bd`, identical tree to `ba742454`; candidate and independent merge-main CI/CodeQL/actual Connected all passed. Actual Connected: 109 tests, no failures/skips. Windows lifecycle HOLD remains unchanged.
- Production includes Backend app Python, executable migrations, Android app source/resources and variants, Web templates/static source, Desktop manager, and Windows installer/runtime/delivery scripts. Tests include Backend, packaging, Android JVM/device/benchmark, Desktop and Windows lifecycle tests.
- Engineering-only scripts/build configuration are visible as tooling, not hidden inside product production or omitted from large-file/suppression debt.
- Each source file has exactly one module/role/language. Web templates/static are not counted twice under Backend. Migrations are a distinct module whose production LOC contributes once to production total.
- Primary LOC means physical source lines, including comments and blanks, matching the existing Backend file-size gate. Code/comment-only/blank lines are additionally reported and sum to LOC. Mixed code/comment lines count as code. Embedded code stays under the file's primary language. This is a reproducible size measure, not a count of statements or user capabilities.
- Exclude docs, images/fonts/binaries, lockfiles, generated/vendor/build output, Room schema JSON and analyzer baseline XML from LOC. Analyzer baseline XML is still read as debt metadata. Report exclusions and individual source records without copying source contents or secrets.
- Show current exact SHA, exact base SHA, production/test/product-plus-test totals, tooling, per-module and per-language breakdowns, and signed deltas. Include file/parent-directory details in JSON for drill-down.
- Hard gate: no increase in `>500`, `>800`, `>1000` physical-source-file counts, including tooling; no increase in each recorded complexity debt counter; no newly added suppression signatures. Total LOC has no ceiling or down-only rule.
- Python C901 debt comes from the real pinned Ruff check with `--ignore-noqa`, fixed current threshold 15 and isolated configuration on both snapshots; do not disguise suppressions as zero debt. Android production/JVM-test figures explicitly mean recorded Detekt baseline IDs, not fresh unsuppressed findings. Source suppressions remain a separate dimension. Preserve the six existing Android rule thresholds and enabled gates.
- Owner clarification: this is a usable engineering map for future development, not a total-only report. Configure function-level analysis and actionable hotspots: pinned Lizard for Python/Kotlin/Java/JavaScript/TypeScript (including inline HTML scripts), the native PowerShell AST for script/function decision counts, and Pygments-tokenized Inno routine decision counts. Keep metric names explicit: Lizard is a language-aware estimate, PowerShell is AST-based, and Inno's lexical decision metric is not a control-flow-graph cyclomatic claim. Declarative CSS/XML/configuration have no function cyclomatic metric; their size still counts.
- For these function metrics, ratchet counts and excess above 15, plus physical function spans above 80 lines, by language/module/role. Native Ruff and Detekt rules remain independently required; these maps do not replace them. Show concrete function/file locations, module/language file counts, changed-module deltas and tool versions. No universal quality score or automatically inferred architecture/retirement claim.
- A missing/unreadable required base, malformed source/debt metadata or removed debt authority fails, never becomes an empty successful report. Use the existing exact-base selection authority in CI. Do not run the sources being measured.
- The existing Backend-only smell audit retains its own checks but is labeled accurately. One repository-weight implementation feeds CLI, CI summary and JSON; no second dashboard or maintained numeric snapshot.

## Implementation sequence

### 1. Real report and counterexamples

Files: `backend/scripts/_audit_repository_weight.py`, `repository_weight_sources.py`, `repository_weight_debt.py`, `repository_weight_functions.py`, `repository_weight_powershell.ps1`, `repository_weight_report.py`; `backend/tests/test_repository_weight.py`.

- [x] Write a real CLI fixture test using two temporary Git commits across all required modules/languages. Assert literal totals, migrations membership, exclusions and independence from dirty/untracked workspace files.
- [x] Observe RED before implementation. Add focused regression cases for large-file growth despite LOC reduction, ordinary healthy growth, actual C901 hidden by a pragma, Android baseline growth, suppression versus quoted examples, and missing exact base.
- [x] Implement immutable inventory, lexical accounting, the maintained debt sources and deterministic comparison/output. No generic plugin framework, invented writer detector or auto-baseline rewrite.
- [x] Run only these small script fixtures locally; all product/heavy qualification remains cloud-only.

### 2. Existing CI integration and slice closure

Files: existing release-audit aggregation/CI contract points, development dependencies, current product atlas and this plan.

- [x] Integrate one always-on read-only gate with the existing exact-base environment and Backend contracts result. Publish a human summary and JSON even for a genuine debt regression; do not weaken current gates or trigger another product runtime locally.
- [ ] Check the exact repository report and its base comparison, targeted lint/contract tests, then exact-head cloud CI/CodeQL/Connected as selected by existing scope.
- [ ] One bounded read-only review, adjudicate only current blockers, normal protected squash merge and independent merge-main qualification.
- [ ] Record actual report/limits and return to capability completion and consumer-grade product work. This gate is an interlude in the full RC Goal, not its replacement or completion.

## Observed development evidence

- Initial real CLI fixtures: 7 RED because the new entry did not exist, then 7 passed. This is not a claim that each later regression was independently mutation-tested.
- CI integration: actual RED for missing JSON/summary production and acceptance of a missing required audit lane; then 16 focused cases passed.
- Policy/fixture isolation: actual RED for a newly added Android rule exemption and synthetic report pollution of the real CI summary; the Inno line-composition/malformed-metadata regression already passed.
- Owner engineering-map addition: 6 real source-consumer cases were RED because JS/TS/Kotlin/inline-JS/PowerShell/Inno function debt was unmeasured; module file counts and zero-LOC source-change navigation separately failed before implementation.
- Current scoped working code: 25 cases passed in 25.97 seconds; targeted Ruff passed; `git diff --check` passed. These are small temporary Git/script fixtures, not product qualification. No local Gradle, emulator, PostgreSQL, browser or installer run occurred.
- Full-repository metrics, exact-candidate cloud qualification and bounded review remain pending; do not print invented repository totals or transfer old green results to this code.

First cloud candidate `456f9f03`: CI `33999112054` failed in Backend contracts. The added lane-absence test grew an existing 497-line file to 508, making Backend large-file debt 12→13; move that new test into this slice's own fixture file, preserving the 12 baseline. Whole-source PowerShell analysis failed because the JSON array wrapper could bind a batch as one item: a two-script CLI fixture reproduced a list-valued path instead of independent records. Use direct `ConvertFrom-Json -InputObject` assignment; no measured script was executed. A read-only 68-file AST syntax probe had zero parse errors and did not run product code. CodeQL `33999111937` and Connected `33999111924` passed for this failed candidate, not for a future one.

One immutable-snapshot review (2979 files; before/after SHA256 `071946F4DD5778CDA1F9078D78FA31622C212FF9F616AAB96D7CEDC68EB5F466`) found two P2 candidates, both admitted FIX: the actually executed `.cjs` test consumer and active `.ini/.properties/.conf/.jsonc` inputs were excluded; the deployed-entry Worker source was wrongly classified as tooling. Their real consumers were independently inspected, and a temporary-Git regression failed before the classification repair. No deployment/Windows authority was changed. After these repairs, 27 fixtures passed in 27.84 seconds.

The new analyzer's own narrow Lizard check then found two over-complex functions (19/20 CCN). File ownership is now an explicit ordered prefix table with separate role classification; Inno declaration discovery and routine measurement have separate responsibilities. Targeted Lizard and Ruff pass without a threshold increase; the five directly affected CLI/required-lane regressions passed in 5.48 seconds. Cloud full-repository report and final-head review/qualification remain pending. Future developers find this map from AGENTS and the existing code-quality guide; no new dashboard or permanent numeric copy is added.

Owner handoff instruction: only after this gate is completely closed, create a new task with the complete continuing product Goal, using `gpt-6-astra` and reasoning effort `max` (not `ultra`, not `gpt-5.6-sol`). Carry full authority/invariants, exact closure evidence, capability/consumer-art obligations, cloud-only heavy verification and all Windows HOLD boundaries. Starting the new Goal must not mislabel the complete product RC as already finished.

Analyzer references: [Lizard upstream](https://github.com/terryyin/lizard) documents its estimation boundary and source-string API; [Microsoft PowerShell AST](https://learn.microsoft.com/en-us/dotnet/api/system.management.automation.language.functiondefinitionast) supplies parser ownership/function boundaries. Versions are reported with each result. Inno uses independent lexical instrumentation, not a fabricated mature Pascal cyclomatic analyzer.
