# Room schema snapshots

Room KSP exports the canonical schema for each `@Database(version = N)` to
`N.json` at compile time. These files are committed to git so PR reviewers
can see the schema diff next to the entity / migration changes.

## Hand-written snapshots

Most `N.json` files are emitted unchanged by KSP. `9.json` is a
hand-written starting point (`pending_mutations` table for ADR-0038
PR-2f offline outbox) committed before a successful local Gradle run
was available; the `identityHash` field is a placeholder
(`"0000000000000000000000000000000000000000"`) and gets overwritten
to the canonical content-derived hash the first time KSP runs in CI
or on a developer machine that can start Gradle.

A schema JSON with a placeholder identityHash is safe at runtime as
long as KSP runs at least once before instrumented tests open the
database — KSP's output becomes the source of truth and overwrites
the placeholder. The committed file's only job until then is to show
the column / index diff to a code reviewer.

If a follow-up review notices the placeholder still in git after the
table has shipped, run `./gradlew :app:kspGrayDebugKotlin` once and
commit the regenerated `9.json`.
