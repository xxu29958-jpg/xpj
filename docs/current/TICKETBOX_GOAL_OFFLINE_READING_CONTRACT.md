# Previously read goals remain useful offline

## User outcome and boundaries

After reading a Goal list online, the user can open one of those goals offline,
including a detail never opened before, and reopen it after the local database
and ViewModel are recreated. Show the original data time and offline source.
Preserve recorded currencies, nullable progress, debt evaluations and versions;
the client does not recalculate financial facts or declare a new achievement.

ReportsRepository remains the Goal query owner. Its cache stores complete server
query results, separate from original creation/edit submissions and their
receipts. One small Room snapshot table serves Goal lists and details. The thin
read result shares value, fetchedAt and fromCache with statistics; no new workflow
state machine, command queue or alternative financial owner is introduced.

An accepted edit remains usable when a later read fails: keep its existing
receipt, visibly identify the original accepted result, and allow another edit
from that real OCC when access has not been refused. Do not attach a query time
or write that receipt into the query cache. A same-or-newer verified query can
replace it; an old Done subscription cannot refill a view cleared by refusal.

This is one high-frequency read journey. Budget and debt read persistence remain
separate gaps. Permissions, local governance and current tool health do not gain
offline authority, and not every product page is promised offline operation.

## Impact closure before construction

| Boundary | Actual entry, consumer, old exit and direct proof |
|---|---|
| Goal query | ReportsActions goals/goal/debtGoals, including original month/type/archive/timezone scope; ReportsRepository owns complete DTO validation and exact-binding requests. List acceptance atomically stores its result, including empty lists, and each complete Goal for detail reopening |
| User consumers | Spending Goal list/detail, debt Goal list/detail and the actual StatsReportsViewModel → StatsUiState → overview goal-count entry. Creation/edit/archive/debt-link/target-date continuations refresh through those owners; unused display components are not assumed to be connected |
| Cache identity | Full logical binding and original query dimensions; recorded money is never rebound to a later default. Preserve current request ordering and prevent old responses from publishing after binding change or access refusal |
| Refusal and recovery | Only verified transport unavailability can use an old snapshot. HTTP 401/403 invalidates the binding's affected query snapshots and clears refused read displays. HTTP 404, compatibility and decoding failures remain failures. Drafts, Outbox rows and original receipts survive |
| Existing statistics | The current any-failure fallback can turn HTTP 403 into cached success. Correct this direct counterexample through the same narrow read-failure distinction and migrate actual Stats display consumers. Preserve statistics query dimensions and calculations |
| Room and cleanup | Existing AppDatabase migration and session/cache clearing paths include Goal snapshots. Migration and cache clearing retain every original Outbox byte; no alternate database or destructive migration |
| Direct producers | Existing ReportsActions implementations and fakes migrate with the return contract. Targeted repository, migration and real Room/Route producers verify list-to-detail reopening, empty lists, original currency/unknown progress, refusal, binding isolation and original intent preservation |

## Implementation and qualification

Retire the network-only Goal dead end, generic offline success claims, the old
StatsRead name when replaced by the shared thin result, and cached-success exits
after explicit access refusal. A stored query remains a dated projection; it
cannot overwrite or stand in for the latest accepted command receipt.

Write the direct continuation/refusal counterexamples before implementation.
Use existing database and navigation fixtures. Keep review bounded to these
postconditions and changed consumers; local checks stay short, while Android
compilation, Room/Route execution and exact final qualification run in the cloud.
Record the after-construction closure here without adding CI histories to the
atlas. This slice does not complete the full Goal or Internal Beta RC, and does
not reopen any Windows lifecycle HOLD.

## Impact closure after construction

- ReportsRepository returns the shared ReadSnapshot through the same Graph and
  API adapters. A complete list and its details share one atomic Room write;
  explicit empty lists replace old membership. Month/type/archive/timezone and
  full binding stay part of the key. StatsRead and unused forwarding methods
  are physically retired; financial values remain server projections.
- Spending list/detail, debt Goal list/detail and the real Stats overview show
  the query's source and time. A complete debt list supplies its selected detail
  without a redundant GET. Cached reads cannot create an achievement event.
  Accepted newer versions survive older queries; receipts carry no query time.
- Goal and Stats reads preserve explicit HTTP refusal and distinguish transport
  loss from actual JSON/empty-body decode failures. Refusal clears their binding
  snapshots and affected views; late reads cannot repopulate after refusal,
  cache clearing or a binding transition. Existing drafts and commands survive.
- Room 19 → 20 only adds Goal snapshots; existing cache/session clearing reaches
  that table. Direct producers cover original Outbox bytes, query dimensions,
  empty lists, unvisited detail after disk reopen, binding/refusal and actual
  list-to-detail navigation. Original command and query results remain distinct.
- Accepted Goal commands retire known-stale Goal snapshots through the same
  query owner, including both verified Outbox receipt exits and all five direct
  Goal commands. Failed commands retain their reads. Invalidating the query's
  existing request tickets also blocks old GET completion; the callback never
  acquires the session coordinator lock from the dispatcher. Receipts and
  original command bytes are preserved, including on replay and disk reopen.

- Both archive return paths apply the accepted result to the active list before
  refreshing. Other goals and a later read failure remain visible; no fake empty
  query, duplicate archive or wrong-binding list update is introduced.

- Direct Room producers open the database before using its current graph and
  bind verified command callbacks to that graph after reopen. The generated
  Room 20 schema adds only Goal snapshots; existing entity schemas are unchanged.
  Session-write auditing recognizes implicit receiver calls without dropping
  sanctioned writes or treating declarations as calls. Receipt adoption uses
  the same accepted result once, preserving version and source semantics.

Status: #401 CLOSED and independently main-qualified at f06983be. Candidate
CI34591130351, CodeQL34591130415 and Connected34591130460 passed; main
CI34593146043, CodeQL34593145923 and Connected34593145951 passed. No local
Gradle or long suite ran. Budget/debt offline queries remain separate RC work.
