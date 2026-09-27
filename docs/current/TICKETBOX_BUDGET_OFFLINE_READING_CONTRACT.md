# Previously read monthly budgets remain usable offline

## Outcome and scope

Reopen a previously read month after Android/Room recreation and inspect the
complete original budget, including configured/unconfigured state, currency,
categories and unknown progress. The actual Plans entry, Budget and Insights budget card show
the read's source and time. New months without a saved read remain unavailable.

BudgetRepository stays the query owner. Reuse ReadSnapshot, existing transport
classification, binding/refusal coordination, Room and the existing save owner.
Keep original drafts and Outbox commands intact. A verified save invalidates old
reads; its accepted result cannot be downgraded by an older query. Never store a
save receipt as a newly fetched query.

An accepted revision only retires older queries. A same-or-newer GET already
obtained while recovering a lost acknowledgement must retain its original read
time, including after Room recreation. Independent readers cannot cancel one
another merely by starting later; an older response must not downgrade a newer
stored query. Access denial must withdraw every retained budget display for the
same binding, even when only one screen issued the refused request.

A verified save remains accepted if local query cleanup fails. Persist its original
receipt and a local read-recovery marker in the existing Done update; do not expose
it as a failed financial command or resend it. Keep that marker through pruning and
Room recreation. Both Budget and global sync show the saved intent and offer read
recovery, including for a reader. The same query owner repairs the local projection
before another read; a persistent local failure cannot revive a known-stale snapshot.

## Impact closure before construction

| Boundary | Entry, consumer, old exit and direct producer |
|---|---|
| Budget queries | BudgetActions/BudgetRepository and Graph; exact binding, month and timezone; complete BudgetMonthlyDto snapshot, no local financial recomputation |
| User displays | MainNavGraph → PlanRoute → BudgetRoute/BudgetViewModel; StatsBudgetViewModel → StatsUiState → actual overview budget card. Preserve month navigation, raw drafts/OCC and configured/unknown states |
| Shared refusal consumers | MonthlyStats, StatsReports, SpendingGoals, SpendingGoalDetail, DebtGoal and BudgetAdvice subscribe to the existing binding denial. Withdraw retained queries, timestamps and unedited server forms; reject late reads. Keep edited raw input, original submissions and command receipts; a later fresh read must not overwrite the draft |
| Background consumer | NotificationRuntimeGraph → BudgetOverspendChecker must use a fresh query. Existing fresh entry stays explicit; a stored overspend snapshot cannot trigger a new notification |
| Accepted save | SaveMonthlyBudgetDispatcher verified original receipt, AppContainer wiring, BudgetSaveRepository observation and both sync surfaces. Invalidate known-stale reads, or persist Done/receipt/local read-recovery marker together if cleanup fails; never change bytes/key/OCC or send an accepted command again |
| Refusal/recovery | Only transport unavailability can restore a snapshot. HTTP 401/403 clears affected read displays and binding snapshots; late requests cannot refill after clear/refusal/binding change. Malformed responses and protocol refusal remain failures |
| Storage/producers | The existing stats_projection_cache can hold complete BudgetMonthlyDto reads, identified by kind/binding/month/timezone; reuse it if it meets the current requirements instead of creating a parallel cache owner. Existing cleanup already owns binding snapshots. Budget/Stats VM, notification and save-dispatch producers migrate together; Room tests preserve original intents |

## Verification and boundary

Direct producers: BudgetOfflineReadingConnectedTest (actual Plans → Budget after
Room/VM reopen, original read time and Outbox bytes); BudgetOfflineSnapshotConnectedTest
(fixed September JPY/unknown values, unvisited month/timezone, binding/refusal, accepted-save ordering and
actual NotificationRuntimeGraph freshness with a SENT delivery control); BudgetReadAccessTest (both visible consumers clear on 403,
original draft/OCC retained). The Plan entry uses its actual ledger-calendar month so
this test does not expire at a calendar boundary. The reopened graph also replaces
the calendar repository. Notification warmup and the actual graph must read the same
month and query timezone; the SENT control prevents disabled delivery or a cache-key
mismatch from hiding an invalid notification. Its existing fresh-only behavior must
remain green when the display read gains persistence.

Run short local checks; compilation and real Room/Route execution use exact cloud
qualification. Close the changed consumers
and replaced exits after implementation; do not expand into advice generation,
new commands, Windows lifecycle or a generic caching framework.

Status: production and consumer implementation is present; final native qualification remains open.
The original preparation is preserved and based on independently qualified main 9711aa781.
4380333's unit execution found both Budget and Insights retaining old values after 403
(CI 36283570688, Android fast 108519996295). Its first Connected attempt failed fixture
compilation and is not business RED. After wiring the actual separate calendar owner,
35a5ed7bd reached real Room/route business RED in Connected 36284411993: an offline reopen
lost the saved query, a v7 GET republished after accepted v8, and a pre-refusal GET restored
a withdrawn read. The Plans amount was present online and absent after reopen.

BudgetRepository now owns a complete ReadSnapshot backed by the existing stats projection
table. Plans and Budget share BudgetViewModel; Insights propagates the same source/time
only for the matching binding and month. Both visible consumers retire known old queries
on accepted original saves and preserve newer drafts. NotificationRuntimeGraph explicitly
requires a fresh query. The verified dispatcher attempts to invalidate older
timezone projections for the original month while preserving already-read accepted
or newer revisions. Failed local cleanup remains a recoverable read task after Done;
recovery must not seed a query or alter the original command. It uses the existing
Outbox binding boundary and the same reader, with no reverse coordinator lock.
The old network-only read exit has been replaced in every direct consumer. No new table,
writer, protocol, notification framework or Windows lifecycle work is introduced.

Short source-only checks pass for changed production/consumer files; they do not prove
native execution. Final source and independent main qualification belong to #438, and
are not added to #437's merge requirements.

The final bccb92a94 review identified three bounded corrections: retained consumers
were not notified of another reader's denial; recovery of an earlier receipt removed
newer queries; and independent reads superseded one another. The test-only 56dc9becf
adds real Room/Outbox/consumer counterexamples and a focused ViewModel recovery case.
All three native counterexamples actually failed in Connected 36288046205; the
ViewModel case failed in CI 36288046213 with the already-read budget replaced by null.
The corrected implementation remains subject to final qualification, including the
existing unconfigured/archived state: positive revisions can be compared, but a new
legitimate unconfigured GET must not be hidden by an older configured snapshot.
A save boundary rejects an unknown response issued before acceptance without
blocking a new post-save read. bccb92a94's route reached and rendered the offline Plans and Budget
surfaces with the original amount/time and locked intent. Its Insights assertion
incorrectly expected a standalone amount instead of the actual labelled remaining
amount; the assertion now uses that complete label and still requires the amount,
source, original time and unchanged intent. That route passed on 56dc9becf and
produced all three previews, including the offline Insights remaining amount.

The following bounded review found that a local cleanup exception could mislabel a
verified save as unverified. Test-only db8049627 adds dispatcher, real Room failure,
restart and both recovery-entrance counterexamples. A real SQLite DELETE trigger
keeps the old query present while cleanup fails; assertions require accepted Done,
durable receipt/marker, no offline resurrection, and recovery without another PUT.
CI 36289507084 actually failed the dispatcher case (expected Success, got Failure)
and the ViewModel recovery case (expected the recovered budget, got null). That
source's native attempt failed a missing import for the existing pruning helper;
it is not native business RED. The import is corrected without changing the
pruning or recovery assertions, and final native execution remains required.
The implementation also keeps Done persistence through cancellation after receipt
verification. 59ee047eb's actual unit and native failures exposed the nullable
generation comparison using an Int fallback; the fix uses Long zero throughout
and retains the original unconfigured-month and first-use assertions.

2026-09-27 最后定向修正：d704bd3ab 的 CI、CodeQL、Connected 均实际通过，Plans/Budget/Insights 三张离线预览已查看。后续直接审查发现 fresh-only 并发成功请求被错判为缓存、Done 先于 enqueue 返回导致保存后空白、撤权后未修改的查询表单未清理。test-only d76dc5ac4 的 Android fast108540816253 实际重现后两条（2654 tests，仅新增2失败）；Connected108540803108 实际重现第一条，成功 GET 被“预算已有更新的读取”拒绝。最小修复保持原接受版本和 Room 的更新顺序：fresh-only 返回自己的合法网络结果；保存结束后补读已观察到的 Done；撤权清除仅来自查询的表单，真实 dirty 草稿和未完成原提交仍保留。三生产文件 source-only 0，最终源仍须独立 CI/CodeQL/Connected 与合入后 main 验证；不继承 d704 的绿灯。

2026-09-27 定向恢复修正：b6145300b 的 CI、CodeQL、Connected 均实际通过。
test-only fc8931182 随后取得两个真实 Room 业务 RED：Connected 108545203230
在 DELETE 失败时丢失原 403，108545203226 在查询 JSON 损坏时让合法 GET 也失败。
撤权现在先通知消费者，再尝试清理；共用 coordinator 的预算、目标、统计和月度安排
十个 fresh/cache 接纳入口均显式迁移。清理未完成时保留拒绝，合法 GET 可显示自己的
结果，但不能借旧查询或重新开启离线回退；后续 GET 完成清理后恢复缓存读取。
预算查询坏 JSON 可由合法 GET 替换，已接受保存的本地恢复也能退役坏查询行；
接受 command 时仍严格验证原 receipt；已经验证并持久化 Done 的本地读取修复，
即使 receipt 随后损坏，也可保守退役原月份的查询，保留 receipt 原字节和原提交。
恢复不重发保存、不拿 receipt 伪造查询。
既有原生测试覆盖在线/离线恢复交叉、Done marker、Room 重开与原意图不变。
本段记录反例和实现，不替代修复后 exact source 的原生、CI、CodeQL 与 main 资格。

db33a1e12 的 CI 和 CodeQL 通过，Connected 108548722094 的原撤权恢复例仍失败：
清理被 SQLite DELETE trigger 拒绝时，fresh 结果的 INSERT OR REPLACE 同样触发
旧行删除。修复保持原断言：未完成清理时，合法 GET 只显示自己的已校验结果，
不写缓存；原离线拒绝保持，后续清理成功后再恢复持久读取。

最新修复使首次观察到的 Done 同样退役较旧的可见查询，保留同版或较新读取及
正在编辑的原草稿。预算 GET 已校验成功时，本地 SQLite 读写失败不再吞掉网络
结果；未写入缓存则保留旧缓存的原值和原读取时间，不把它标成新鲜。
撤权清理失败的记录复用 settings 持久化，覆盖完整逻辑绑定和月度安排已有的
持久绑定；Room 和协调器重建后不能复活被拒绝的旧查询。Goal、Stats、月度安排
current/history 共用同一接纳条件，合法 fresh 结果仍可用，月度建议输入失效回调
仍执行；只有旧查询清理和拒绝记录清除均成功后才恢复缓存写入。

test-only c5f751d9e 的 Android fast 108552890433 实际复现首次 Done 后仍显示旧预算，
以及 Goal/Stats 在拒绝清理失败时丢失 fresh 结果。该源的 Connected 停在两处新增
JUnit 断言参数顺序错误，不能当作业务 RED；2636dd214 仅纠正参数顺序，保留全部
业务断言。2636dd214 的三个 Connected 分片实际复现损坏 Done 回执隐藏修复、
SQLite 写失败吞掉 fresh 预算、月度 current/history 丢失合法 fresh 结果，以及
重建后丢失原 403。原有坏查询修复流程还暴露同月第二次保存被已完成记录阻止；
预算 admission 现按既有队列语义区分 Done 与未完成记录，保留旧回执，允许新版本
保存，仍拒绝并发未完成提交。该流程继续验证两次原保存和缓存修复，不删除断言。
修复后的 exact source 仍需独立 CI、CodeQL、Connected 和 main 验证。
