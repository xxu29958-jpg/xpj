# Room schema snapshots

Room KSP exports the canonical schema for each `@Database(version = N)` to
`N.json` at compile time. These files are committed to git so PR reviewers
can see the schema diff next to the entity / migration changes.

## Hand-written snapshots

Most `N.json` files are emitted unchanged by KSP. `9.json` was added by
hand for ADR-0038 PR-2f (offline outbox `pending_mutations` table)
because no Gradle daemon could start on the dev machine at the time;
KSP overwrites it with the canonical hash + structure on the first
successful run in CI.

The committed JSON must:
- match the entity declarations exactly (column types / nullability /
  `defaultValue` / index column list), or the next KSP run produces a
  different output and CI surfaces an "uncommitted schema regen"
  diff;
- carry a strict-parseable shape — Room's `kotlinx.serialization` JSON
  decoder rejects unknown keys, so no comment fields inside the JSON.
  Document context in this README instead.

If a follow-up review notices the placeholder identityHash still in
git after the table has shipped, run `./gradlew :app:kspGrayDebugKotlin`
once and commit the regenerated `9.json`.
