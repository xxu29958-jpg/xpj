# 已接受上传意图的跨实例恢复

- Goal：完成总 Goal / 最终产品合同已要求的 Capture 离线、草稿与恢复任务。原 A/B/C 分享在 A 已保存、B 容量拒绝、C 未发送后，即使原 VM / graph 不再存在且来源 URI 不可再读，用户仍能找到并继续原 B/C，A 不重发。此处是 [Atlas 唯一已登记缺口](TICKETBOX_CURRENT_PRODUCT_ATLAS.md) 的下一纵向片；#381 的 VM 内容量续传仍保持 CLOSED。
- Authority：总 Goal 与最新用户裁决 → 2026-08-26 最终产品合同 Capture 责任及离线意图条款（225–229、372–400），G2 后合同 Inbox 条款（242–249）→ exact source / 实际执行证据。旧代码的 online-only 注释不决定产品范围。
- Allowed Changes：当前阶段只新增两个直接行为反例、必要的真实仓储 fixture、本合同和 Atlas 原 gap 链接。后续生产须复用现有上传、Room Outbox、幂等、身份与恢复 owner；本阶段没有生产实现授权。
- Forbidden Surface：不新增 queue / status ledger / bus；不把图片相同当作命令幂等；不把本地保存冒充服务端 receipt；不清除未完成原意图来满足回归；不修改鉴权、金额 writer、容量政策或其它领域；不扩展任何 Windows 生命周期 HOLD。无本机 Gradle / PG / 长测，无 stage / commit / push。
- Done Checks：来源失效后重开的真实 Room / repository / VM 可读原恢复，原 Retry 最终只发送 A/B/B/C；同一原 key、文件及 timezone 重放返回同一 receipt，账单、任务、文件和执行器提交不增加；不同 key 同图仍新增 Pending 并进入重复核查；容量准入失败仍回滚 Expense / task / file。绑定、权限、未知 payload、协议拒绝与过期不得改绑、换 key 或静默结算；全部直接消费者和旧出口在生产施工后按下表重新闭合。
- Evidence：准备基线 `61aa4f7e94667778e82584a3ba878e30eef9d38a`，隔离树 `codex/upload-intent-continuity-20260907`。test-first 经主控提交并整合父链后发布 `e22ff121e7cde6ab600a7f716fae0451fb691463`；实际云端已取得 PG 回执反例 RED，Android 新反例的原始退出原因被 fixture 清理异常覆盖，不能算恢复业务 RED。下文记录此证据及两处测试修正；没有生产 GREEN 或全 Goal 完成声明。

## 施工前 impact closure

| 当前入口 / owner / 直接消费者 | 已核实源行为与本片边界 | 直接验证生产者与保留控制 |
| --- | --- | --- |
| 冷 / 热分享 → Activity / Shell | `MainActivity`、`LaunchIntents`、`TicketboxApp`、`LaunchActionState` 保序合并未交接分享。Activity 在 shell 内存接收后清 ACTION_MAIN；`PendingLaunchActionEffect` 在 VM 同步接收后 consume。没有持久接受回执。后续要让全部已接受 URI / 顺序在原绑定下落盘后才确认移交；保留双 post / 消费前缀，准备失败不能静默消费。 | `LaunchShareHandoffTest`；本片新增 `PendingLaunchActionEffectTest.reopenedRoomAndNewOwnerRecoverConsumedBatchAfterTheSourceUrisAreGone` 直接使用既有 effect，而非重写分享循环。 |
| Picker / shortcut / 页面重入 | `PendingRoute.rememberSingleImageUploadLauncher` 的非空 PickVisualMedia 结果也 post UploadSharedImages；普通与空态上传按钮及 UploadReceipt shortcut 共用它。取消没有上传意图；暂停后 picker 等待，share 可在原 binding 下追加且不自动重试 B。 | 同一 Connected 文件保留原 picker、shortcut、页面移除 / 重入实际 Retry 三例；保留 `PendingViewModelUploadContinuationTest` 的暂停追加 D/E、明确停止与旧 callback。 |
| URI → 准备字节 | `PendingUploadSource` 只保留 applicationContext 并在 IO 调 `ScreenshotUploadPreprocessor`，没有持久文件或持久 URI 授权；尾部 C 到发送前才读。准备器原图回退上限为 10 MiB。另一实际调用者 `StatsRoutes.rememberDebtBillImageLauncher` 用同一准备器给 Debt bill parse；这不是 Pending 上传入口，本片不能改变其输出/限额。 | 新 Connected 通过真实 MediaStore、真实 ContentResolver 和准备器读三张不同的测试 PNG，撤回这三条源 URI 后不得借测试字节数组恢复。原准备/异常/容量累计控制保持；若后续改共享准备器，Debt 这个直接消费者必须验证，不能默认跳过。 |
| VM 上传 owner / 旧成功与失败出口 | `PendingUploadSession` 仅用内存保存 batch、cursor、binding/generation、B preparedImage；容量暂停保留 B/C，普通失败却推进 cursor 并释放字节。VM onCleared / invalidate 释放 batch。后续持久上传 owner 接管原状态推进，VM 留投影及动作，不能保留第二套内存发送循环。 | `PendingViewModelShareUploadTest` 的 A/B/B/C、`secondImageStillUploadsAfterFirstFails`；`PendingViewModelUploadFailureTest` 的不可读、反复容量、取消、换账本。新反例不改这些原断言。 |
| Repository → API → receipt 消费者 | `PendingReviewActions` → `ExpenseRepository` → `ExpensePendingRepository.uploadScreenshot` 直接 multipart；真实 `bindExact` 冻结/核准 logical binding。当前请求没有幂等 key，timezone 在每次调用取设备当前值。成功才写 lastUploadAt，VM onDataChanged → refresh → receipt enrichment observer；该链不是本地接受出口。 | `ExpenseUploadBindingTest` / `PendingViewModelEnrichmentTest` / `PendingAdviceInvalidationTest`；新增真实 graph fixture 提供全部当前 DTO，保留 pending 缓存与 category/enrichment 查询；本地意图不触发 confirmed/advisor writer。 |
| 已有唯一持久与发送通道 | `AppDatabase` / `PendingMutationDao`、`OutboxRepository`、`OutboxAdapterGraph`、`AppContainer` dispatcher 注册、`OutboxDrainEngine`、`OutboxDrainWorker` / `OutboxScheduler` 已拥有绑定、原 payload/key、串行发送与恢复；当前没有 upload 类型、adapter、dispatcher 或待上传文件 owner。最小方向是在此既有通道增加具体上传意图与受控文件引用，不建立另一队列。 | 新 Connected 的持久 authority 是磁盘 Room + 实际 RepositoryGraph；fake HTTP 只拥有已接受的远程 A，不保存或重建 B/C。它未驱动 WorkManager，不证明 OS 调度或进程死亡；生产接入 worker 后仍须用同通道直接生产者验证。 |
| 顺序 / 普通失败的横向限制 | 当前 DAO 同 target 排除未解 InFlight / Conflict / Failed。把每个图片意图机械设成同一个 batch target，会让普通 Failed 也永久堵住 C，破坏既有“普通失败继续尾部”。批次序号、原单项 key 和继续裁决必须由一个上传 payload/dispatch owner 统一承担：容量暂停挡尾部，普通未确认失败保留可见原件且按既有任务继续其余项。不能以改为 Done / 丢弃原件解除阻塞。 | 保留 `secondImageStillUploadsAfterFirstFails` 和 `repeatedCapacityRetryKeepsEarlierAndUnreadableTailFailuresThenContinues`；这两个既有行为约束须与新磁盘恢复一起通过。当前只记录模型限制，尚未实施通用队列改动。 |
| 身份 / 撤销 / 文件清理 | 完整 LogicalSessionBinding / `bindExact` 已区分 origin、server/data generation、account/device、ledger。token 轮换不应创造新意图；换账本、换身份、降权与旧 callback 不能发送或采用旧结果。`OutboxStatusViewModel` 与两处 SyncStatus、显式 Drop / clearQuarantined，`OutboxRepository.clearAll` / `gcCompleted` / 超龄 reaper 都是持久文件的新直接清理消费者。 | 原 binding / viewer / quarantine / expiry 控制复用；后续逐个接上原文件释放，不准在 VM dispose、失败、刷新或身份变化时删除仍未解决的原件。两个最小反例不声称已覆盖全部清理与权限恢复。 |
| 后端提交 / 共享上传调用者 | `uploads.app_upload_screenshot` → `_upload_request.handle_upload` 保存文件 → `stage_pending_expense` → `prepare_pending_expense_enrichment` → 一个 commit → task submit / receipt。容量异常在 commit 前 rollback 并补偿文件。同 helper 还服务 UploadLink 与 `web_inbox_capture`；其权限、来源、字节保留及拒绝 flash 不能受新 Android 命令协议破坏。 | 本片 `test_uploads.py` 新 real_db 用例；原 `test_upload_enrichment_admission.py` 的 Android / UploadLink / Web 容量拒绝、行与文件回滚、UploadLink 字节预约补偿、并发容量控制保持。 |
| 幂等 / 协议门限 | `stage_pending_expense` 先新增行再标 suspected duplicate，不能作重放 owner。既有 `services/idempotency.py` 能把原 key/fingerprint/首次稳定响应与业务事务合并。新可靠 replay 必须由 API/runtime protocol owner 声明支持并在发送前核准；旧后端忽略 Idempotency-Key 不得被当作支持。不能只改客户端常量或把一般 HTTP 拒绝结算 Done。 | 新 PG 用例当前给真实路由发送既有 headers / multipart，不引入未来 API。协议门限、旧客户端/旧服务端拒绝及原 key/file/timezone 保留的直接测试在生产设计明确后补齐；本轮不声称此门已成立。 |

## 文件、有效期与原文保留的施工约束

接受前必须把尚未发送的可读原件/准备结果写入应用控制的目录并完成有界校验，Room 只引用该 owner 下的文件。除了既有单图读取上限，生产开始前须明确批次数量和累计暂存字节上限；空间不足/源不可读要保留可理解的未接受结果，不能先 consume 后丢尾部。不能把未限制的图片 bytes 填入 Room JSON，不能扫描或复制其它图库内容。

原 filename、content type、bytes/fingerprint、timezone、创建/到期时间、顺序、单项 key、payload revision 与 logical binding 一次冻结；新 token、时区变化或重开不能重造。现有 Outbox 七天 age cap 保留 `outbox_row_expired` 原行并去掉无效 Retry，不能旋转 key 绕过可能已经失效的服务端幂等窗口。到期/unsupported/quarantine/拒绝仍要展示原文上下文；未完成文件保留到用户明确处理，空间总量通过接受前限额约束，不以后台过期删除原件来释放容量。明确 Drop、已安全完成后的保留期及 clearAll/quarantine 清理须共同验证文件生命周期，不能建立第二份清理状态账。

## 两个 test-first 反例与证据层

1. `PendingLaunchActionEffectTest.reopenedRoomAndNewOwnerRecoverConsumedBatchAfterTheSourceUrisAreGone`：先实际创建三个 MediaStore PNG，原 effect → 实际 repositoryViewModelFactory / VM → RepositoryGraph 发 A/B，断言容量暂停、A 的 Room 缓存/lastUploadAt 成立、分享已消费。移除页面后真正清空旧 ViewModelStore、等待旧 VM 子任务结束，撤回源 URI，关闭/重开同一磁盘 Room；建立全新 VM 与空 shell。恢复状态最终应可达，点真实“重试上传”后应有 A/B/B/C，B/C 内容与原图相同且三个 Pending 经原 refresh 可见。当前源预计在新 VM 等待恢复状态处失败；先决条件失败必须单独标为 fixture/接线问题，不能归作此缺口 RED。测试保留源 bytes 仅供断言，生产 owner 无法访问它；不注入 fake PendingReviewActions、不手动重放 refs、不写恢复 loop、不声明 OS 死亡或真实 WorkManager 资格化。
2. `test_android_upload_same_intent_returns_the_original_receipt_without_another_expense_or_task`：真实 authenticated app 路由 + PostgreSQL + 文件存储，首次提交先验证一条 Expense、一条 task、文件与 timezone/execution submission。完全相同 key/file/timezone 再提交，要求 expense/public/task/status/message receipt 不变，行数、文件集合和执行器提交不增加。只替换原 executor submit，仍使用真实 file-save/准入/claim候选/事务 owner，不调用 OCR/网络。当前源预计在 receipt 标识比较处失败。最后不同 key 同图须新增 Pending/task 并保持 suspected duplicate；该后续正控可能被首次 RED 遮住，不能提前声称执行。

现有两个 workflow 共用 `classify_ci_paths`：两个 Android 测试路径直接触发 Android fast / actual Connected，PG 文件走既有 PostgreSQL lane；没有新增 workflow 或改阈值。实际纯 classifier 逐路径结果为：两个 Android 路径仅 `android=true`，`test_uploads.py` 仅 `postgres=true`，两份文档不触发 heavy scope。新增 PG 例带 `real_db`，由 `tests/conftest.py` 的现有 collection/lane 约束送入 CI 的 real-db lane，不是 ordinary 的事务回滚替代。Connected 现有 producer 使用 API 36；初版在测试方法上使用 `RequiresApi(29)` 被实际 lint 拒绝，本轮按标准改为 `SdkSuppress(minSdkVersion = 29)`。该 API 36 lane 仍实际执行此例，原 no-skip / count 门不变。

准备阶段本地实际检查：Python AST 有效、31 个原上传测试函数体不变；三个原 Connected 方法正文不变；Ruff / `git diff --check` 通过，逐项复核当时 factory、RepositoryGraph、DTO 和 API 参数。没有本机 pytest、PG、Gradle、Connected 或设备执行；当时的源码检查不能代替下述云端编译、XML 与日志。

施工后须在本合同同表补每条实际迁移与验证结果，再更新 Atlas 这一原 gap；当前不得填写完整闭合或 RC 完成。

test-first 发布前 Root 已完整读取五文件及真实上传准备/仓储/事务入口；当时的独立 bounded review 未发现会先于目标行为失败的具体接线问题，但下述云端发现证明该源码检查遗漏了两处 fixture / lint 问题。31 个原 PG 测试 AST 与三个原 Connected 方法正文保持不变。准备阶段的 pinned Lizard 1.24.0 producer 对三个代码路径定向解析（0.31 秒）没有 over-80 或 over-15 项；该测量不代表 Kotlin 编译、完整 Detekt 或运行结果。

## e22 实际失败与测试夹具修正

实际 source 为 `e22ff121e7cde6ab600a7f716fae0451fb691463`，PR checkout 为 `27749dd44ce038b6357451e315cc66b19c180c49`；GitHub commit tree 读回均为 `9263c105696463e06f92b790099b31aade5c3083`。CI `34059100042` 的 PG real-db 1/3 job `101556343704` 实际为 97 passed / 1 failed：新增 `test_uploads.py:192` 在相同 key/file/timezone 的第二个 200 响应发现 id 从 1 变为 2，public_id / enrichment_task_public_id 也不同。首次行、文件、单次执行器提交与 timezone 前提均已越过；其后的无第二条行/文件/提交及不同 key 正控因首失败未达，不宣称已执行。五个 PG 分片合计 4021 passed / 1 failed / 6 skipped；当前 lane 没有 JUnit 输出，以原始 pytest 日志为证。

Connected `34059100141` / execution `101556387743` 的 artifact `9997091930` 实际 XML 为 129 tests / 1 failure / 0 skips，原三个 `PendingLaunchActionEffectTest` 用例全部通过。唯一栈为 `UploadIntentConnectedFixture.close:114` → 新例 finally `PendingLaunchActionEffectTest:190`：已撤销的 URI 仍留在待清理集合，退出时再次 delete 触发 SecurityException。XML 和该例 logcat 都未保留被覆盖的原始退出原因；7.166 秒时长不能证明预期恢复超时。这是新增 fixture 失败，不能归作 Android 恢复业务 RED。

Android fast job `101556343768` 的 artifact `9997142562` 实际 JVM XML 为 2155 tests / 0 failures / 0 errors / 0 skips。job 失败来自 `lintGrayDebug` 的唯一 `UseSdkSuppress` error，指向新增测试方法 `@RequiresApi(29)`；不是生产编译或 JVM 业务失败。CodeQL `34059100054` 全部成功。e22 CI 已全部结束：Windows installer job `101556343725`、release packaging、Desktop manager 和其它执行 lane 成功；CI failure 只有 PG 新业务反例及 Android lint 两个执行源头，相应 aggregate failure 不算额外反例。上述是 e22 的执行事实，不能给本轮未提交修正背书。

| 本轮直接影响面 | 修正前的实际问题 / 保留边界 | 修正后 owner 与验证生产者 |
| --- | --- | --- |
| MediaStore 创建 → revoke → close | 现有 sourceUris 同时记录已删除和待清理 URI；finally 的重复删除遮住原失败。 | 每次 delete 返回 1 后立即从同一集合移除该 URI，然后仍断言原 URI 不可读。close 仅清理尚未撤销的本例 URI；无额外集合、权限或生产文件 owner。 |
| 新 Connected 例的资源退出 | 手写 finally 直接 close 可以替换主断言异常。 | fixture 实现标准 Closeable，由唯一测试调用者使用 Kotlin use 释放。业务失败仍为主异常，后续 close 异常按标准 suppressed 保留；原 VM dispose / Job join / Room reopen、全部业务前提与 A/B/B/C 断言保持。 |
| 测试入口 / API 前提 | 测试方法 RequiresApi 被 Android lint 拒绝。 | 改标准 SdkSuppress(minSdkVersion = 29)，保留 fixture 的 API 使用声明。实际 cloud API 36、真实 factory / graph / Room / effect / Retry 点击以及既有 no-skip 门全部保留；没有调整生产、manifest 或 workflow。 |
| 直接验证与未改出口 | 原三个 Connected 入口及 31 个原 PG 测试不得为新反例让步。 | 只改两份 Android 测试文件与本合同；PG 文件、HTTP fixture 返回、原 3 例、生产 owner/权限/协议/容量/重试次数不变。秒级源码、Lizard、diff 检查后由主控发布新的 exact source 再取得实际 Android 业务 RED。 |

本轮不把清理失败算作业务反例，也不以捕获异常、放宽不可读前提或跳过当前 emulator 测试制造 RED/GREEN。证据保存在独立 qualification 目录，源码树不保存 raw log 或 credentials。

本轮实际秒级检查：三个原 Connected 方法逐字不变；新方法排除标准 resource lifecycle 改动后，全部业务源码行不变；PG 文件与 e22 相同。复用既有 `repository_weight_functions._lizard_functions` 和 pinned Lizard 1.24.0 检查两份 Kotlin 文件，未报 over-80 / over-15；新方法实际文本跨度为 74 行，Kotlin 嵌套解析仍只是导航估计。`git diff --check` 通过。没有安装依赖、运行本机 Gradle / PG / emulator、stage / commit / push；新候选仍需云端证明预期恢复业务 RED。

## 1582 的实际编译失败与 test source 依赖闭合

Root 核准并发布 `1582d819956ecf6d4dc7053145bebc2bc5882bd4`，tree `12744d36ffde91649756f99027294bf2432acdd7`；actual PR checkout `633775bdc669e40aae2526ab5c82f6caad3e620a` 同 tree。CI `34060606812` 的 Android fast job `101560358778` 成功，之前的 UseSdkSuppress lint 错误已不再阻断；CodeQL `34060606782` 成功。但 Connected `34060606814` / job `101560365404` 的 `compileGrayDebugAndroidTestKotlin` 实际失败：PendingLaunchActionEffectTest:27/118 无法解析 filters / SdkSuppress。Emulator 实际已启动；没有执行测试或生成 JUnit XML。artifact `9997433976` 只有运行前后诊断，不能用它声称 Android 业务 RED。这是测试源依赖遗漏，也说明 fast/lint 通过不能替代 instrumentation-source 编译。原 PG 回执业务反例仍使 real-db 1/3 失败；后续门禁继续按 actual head 记账。

施工前后 impact：唯一新依赖消费者是 API 29 MediaStore 测试方法的 SdkSuppress；测试 runner 已经通过当前 Compose 测试运行时链存在，但没有进入该测试源码的 compile classpath。读取 Google Maven 原始 POM 得到：当前 BOM 2026.04.01 选择 ui-test 1.11.0；ui-test-android 的 runtime 依赖 espresso-core 3.5.0，其 runner 为 1.5.0。现有本机 runner-1.5.0 AAR 中也实际包含 `androidx/test/filters/SdkSuppress.class`。按[官方 API 归属](https://developer.android.com/reference/androidx/test/filters/SdkSuppress)，将这个已采用的 runner 版本显式加入 androidTestImplementation，并在现有 version catalog 命名，不升级测试运行时或增加 app production 依赖。

该修正仅变更 catalog、app 的 instrumentation compile 依赖和本合同；不改三份原测试、新恢复断言、minSdk、fixture、生产上传、数据库、SDK 执行范围或 no-skip 门。旧的“靠间接 runtime 依赖可编译 SdkSuppress”假设退役。POM/AAR 的秒级来源核对与 TOML/diff 校验只证明依赖归属；新的 exact Connected 编译和实际业务反例仍待云端执行。

## d83 实际双 RED 与后端稳定收据实施

`d83ef631d71428352a3c93baa29365ac0a9aeb70` 的 actual PR checkout 为 `3947cafde96aff737544ed388f5d6f4f856102bd`，GitHub commit tree 读回均为 `8387f364e9ad4ba0dff89121587c27f140daa499`。CI `34061343690` 的 real-db 1/3 job `101562341251` 实际为 97 passed / 1 failed；原 `test_android_upload_same_intent_returns_the_original_receipt_without_another_expense_or_task` 再次到 `test_uploads.py:192`：首次提交、行/文件/任务/时区和单次 submit 前提已通过，相同 key/file/timezone 的第二个 200 收据 id 为 2，首次为 1。其后的无额外副作用及不同 key 正控仍被首失败遮住。五个 PG 分片合计 4021 passed / 1 failed / 6 skipped；以原始 pytest 日志为证，没有声称存在 PG XML。该 CI 唯一执行失败是本 PG 反例，PG aggregate 仅传播失败；Android fast 及其余选中执行 job 成功，CodeQL 全部成功。

Connected `34061343647` / execution `101562337790` 的 instrumentation 编译成功，实际 Starting 129 / Finished 129；artifact `9997783264` 的原始 XML 为 129 tests / 1 failure / 0 errors / 0 skips。唯一失败是新恢复例 `PendingLaunchActionEffectTest:178` 等待 `canRetryUpload`。原 effect 接受 A/B、A 的 Room/lastUploadAt、暂停、消费原分享、旧 VM 退出、三个源 URI 撤回且不可读、磁盘 Room 真正关闭/重开以及新 VM/空 shell 的前提已通过，原三个同类测试通过；Retry 点击及 B/C 最终发送断言未到达。本层证明真实 Room/repository/VM 重开后的业务 RED，不声称 OS 进程死亡或 WorkManager 执行。

主控已读原始回执并授权本段后端生产工作；前文 test-only 阶段限制保留为历史记录，不再限制这个已获授权的后端片。五项边界为：Goal 是同键上传的原始完整收据与单次业务接受；Allowed Changes 限上传 route/request/file reader、现有共享 OpenAPI metadata 消费、原 `test_uploads.py` 和真实生成的 snapshot；Forbidden Surface 是 Android/新队列/幂等表与保留期/鉴权/容量/Windows 生命周期及其它业务 writer；Done Checks 是原 receipt RED、不同 key 正控、变化原文拒绝与事务补偿在新 exact source 上通过；Evidence 严格区分下述秒级源码/生成检查与尚待云端的真实 PG 验证。

| 后端入口 / owner / 消费者 | before → after 与退休边界 | 直接验证与尚待证明 |
| --- | --- | --- |
| Android app route / 原 writer auth | 原 route 忽略幂等 header；现在仅 `/api/app/upload-screenshot` 接受可选 `Idempotency-Key`，仍先走真实 writer context，未提供时保留原上传行为。ledger 取真实 auth，account/device 同样进入原命令指纹；token 轮换不参与命令身份。 | 原 32 个测试函数 AST 不变，包含 headerless Android、UploadLink、降权拒绝、原同键 RED 与不同 key 正控。Android 本片没有生产改动；新持久协议的发送方由主控继续实现。 |
| OpenAPI / 生成客户端 | 实际生成发现 `main._apply_protocol_header_contract` 旧 blanket rule 将新增可选 key 错标必填。复用已有 `x-ticketbox-runtime-required`：上传显式 false，其余原规则默认仍为 true；消费后不把内部 metadata 发布到 schema。旧“每个声明的 key 都必填”假设退役。 | 真实 `check_api_contract.py --update`，硬禁止 `Engine.connect/raw_connection`，生成前观察 required=true，修后为 false；其余 38 个 key header 与基线完整相等且必填。所有组件不变，唯一路径差异为本上传 route。新增现有测试文件内的 schema 控制，未本机执行 pytest。 |
| 请求有界读 / canonical 文件 owner | 原读取立即保存文件，无法在保存前 claim。现在 `_read_request_upload` 与 `file_service.read_upload_bytes` 先按原 multipart/单图限制读取、关闭源；原 `save_upload_bytes` 仍独占类型、清理元数据、真实像素验证、随机存储与 hash。原唯一 caller 已迁移，无消费者的 `save_upload` 包装物理退役。 | 原 raw/multipart/HEIC/伪装类型/大小/非法文件名/元数据测试不变。没有提高上限、额外文件副本、附件 schema 或读取其它图片。 |
| 幂等命令身份 / 共享 claim | 指纹使用原始受限 bytes 的 SHA256、filename、content type、原 timezone 和真实 account/device，claim tenant 为 auth ledger；不把消除元数据后的 image_hash 或 suspected duplicate 作为命令键。原 `claim_idempotency_key` 在持久文件之前执行；复用原 409 in_progress / 422 key_reused。 | 新 real_db 参数控制分别改变 raw PNG metadata、timezone、filename、content type，要求 422 且 canonical save 不被再调用、行/文件不变；不同 key 同图仍由原正控检验创建第二个 Pending 并进入重复核查。四项控制未本机运行。 |
| 一次业务提交 / 完整原收据 | 原 `handle_upload` 已拥有 Expense → queued task → 一个 commit → submit。现在共享 claim 与原两个业务 stage 共用该事务；commit 前构造并存完整 typed `UploadResponse`，同一次 commit 落库，commit 后仍由原 submit owner 执行。HIT 直接验证并返回原 typed body，不保存文件、不创建 Expense/task、不再 submit；不在已提交 handler 外包一层假原子缓存。 | 原 receipt RED 保持全部原断言。新增提交前 receipt-flush 失败：claim/Expense/task/file 全回滚且零 submit，原 key 重试才能首次成功。新增真实 `Session.commit` 先成功再抛确认丢失：行/文件/原 receipt 已持久，第二次必须精确返回 stored body 且零重复 submit。测试替换的是异常/执行器 seam，不冒称真实网络或进程死亡。 |
| 失败补偿 / enrichment 后续 owner | prepare/claim/file 保存均纳入原 rollback barrier；确定 commit 前失败删除已保存文件，commit 已尝试后的不确定异常保留附件，避免已提交 Expense 指向被删除文件。postcommit executor 异常仍由 `submit_pending_expense_enrichment` 返回同一 durable task id；HIT 不重提任务，状态及 orphan/recovery 仍归既有 task owner。 | 原 `test_upload_enrichment_admission.py` 的 task 插入失败、容量拒绝、Web 反馈、UploadLink 字节补偿和并发容量测试源码不变。新事务控制需云端 PG；没有新增后台重试、租约、清理或保留期机制。 |
| Headerless / UploadLink / Web 实际消费者 | `uploads.upload_link_screenshot` 与 `web_inbox_capture.web_pending_upload` 不传新 header，继续使用同一个 `handle_upload` 的原路径。`save_request_upload` 的“文件已存、commit_guard 尚未运行”入口实际保留，未改 UploadLink 撤销/到期重验、字节 reservation/finalize/release、Web 303/watch/flash 或权限来源。 | `_infra/upload_link_commit_concurrency.py` 真实 monkeypatch 的就是该 seam，原 revocation/extension race 仍能停在原边界；现有三入口直接测试保持。这里是源码接线证据，新头真实 PG 执行尚未取得。 |

Keyed receipt 的 `duration_ms/timing_ms` 随成功收据在 commit 前冻结，重放不重算诊断；原服务器 logger 仍记录完整请求耗时。该收据表示上传和任务已经接受，不表示 OCR/enrichment 已完成或账单已确认，后续消费者仍读原 task/Expense。无 header 路径保留原 post-submit receipt。

新增测试仅四个有明确后置条件的函数：一个 schema 控制、一个四参数原文变化控制和两个事务控制，共七个 case；未改原 32 个测试正文，没有复制新的测试框架。五份 Python 源实际 AST 有效，未新增 over-80 函数；Ruff、diff 检查通过。实际逐路径 `classify_ci_paths`：`main.py` 为 postgres/backend_frozen/windows，上传 route/request/file service 为 postgres/backend_frozen，`test_uploads.py` 为 postgres，生成 snapshot 为 android，本合同不触发 heavy scope；CI 与 Connected 仍调用原 `ci_scope.py`，未新增 selector。没有本机 pytest、PG、Gradle、emulator、commit 或 push，以上不能称新生产候选 PG GREEN。

本段不关闭整个 Capture 片：Android 新格式、原文件/Room 接受与恢复、全部持久清理消费者及可靠 API/runtime support negotiation 仍由主控继续实施。当前 API version 未改；旧后端会忽略 header，故新 Android durable replay 不得仅凭 header 存在判定支持，也不得用这次后端源码检查冒充新 exact head 或整个 Goal 合格。

### 主控复核：提交确认丢失后的原任务执行出口

上面的新增 lost-commit-ack 测试把零 submit 当作最终成功，属于不合理的测试语义，不能保留为产品要求。实际调用链表明：`BackgroundTask` 在原事务中已经 queued，commit 确认丢失使 handler 跳过 `submit_pending_expense_enrichment`；之后 HIT 只返回原收据，而 `recover_orphaned_tasks` 仅在服务启动运行，同一进程没有 queued 的周期恢复。Android `PendingEnrichmentObserver` 对该状态持续轮询，原识别任务没有实际执行出口。这是现有异常测试直接构造的缺口，不是要求另造后台队列。

施工前影响闭合：入口为 app keyed upload 的原 commit 异常；消费者为原 task 查询、Pending 识别状态及上传重放；旧错误成功出口为 HIT 收据稳定但 queued 永不执行；持久事实仍是一组原 claim/Expense/task/附件，恢复必须复用当前请求持有的原 prepared task/payload，经权威读回证明已提交后交还现有 task submit owner。读回不能证明提交时，继续保留原错误和不确定附件，不能假造接受；进程启动的 orphan 语义、其他任务调度和无 header 调用不因此重写。

主控先纠正这一新增测试：真实 commit 之后注入确认丢失，期望在确认原提交存在后返回其原收据，并且原 task id、原 timezone 和原 OCC 只提交一次；同 key 重放不再新增或执行另一项任务。新增判定尚待实际云端 RED；前文 seven-case 源码检查不再等于该测试已正确闭合。当前后端稳定收据候选仍是部分生产实现，整个 PR 保持 Draft，未具备合并资格。

提交前实际体量检查发现，把上述案例继续放在通用 `test_uploads.py` 会使它从 880 增至 1037 行。现将完整收据/claim/replay/recovery 责任的五个场景及唯一行数 oracle 一起迁入 `test_upload_intent_continuity.py`，共 240 行；原文件保留上传路由/输入/文件行为，共 811 行。共享文件与图片测试工具复用既有 `api_contract_helpers` 和 `tests._infra.assets`，没有测试模块互相导入、额外框架或阈值修改。AST 对照证明基线 32 个原测试跨两文件各保留一次，正文不变；四个新函数共七 case，包括上述已纠正的恢复判定。所有选中 Python 源的 AST、Ruff 与 diff 检查通过，本机没有执行数据库或应用测试。

### 4e4472ea 的实际恢复 RED 与原提交出口修正

本轮基线 source 为 `4e4472ea2f50ffe9fc5532b4a02cc5c9dcc571de` / tree `aaeb2f091bccad13b076b04284af78abb95d27ca`。主控已核 actual checkout `58419d27f2acd1cc97c409008ef93f78545ce192` 同 tree；CI `34064652217` 的 real-db 3/3 job `101571199638` 原日志实际为 108 passed / 1 failed / 3926 deselected，468.76 秒。唯一失败 `test_upload_intent_continuity.py:216` 已越过真正 commit 后注入确认丢失的前提，但 HTTP 返回 500 而非 200。后续 task/payload/receipt 与重放断言被该首项遮住，不能宣称已执行。该实际行为 RED 已由主控裁 FIX；原断言全部保留。

| 当前直接责任与消费者 | 本轮 after-impact / 退役出口 | 直接验证边界 |
| --- | --- | --- |
| `handle_upload` 的 keyed 原业务 commit | 原来 commit 抛错后只回滚并返回异常，已经落库的 queued task 没有提交出口。现在 `_commit_upload` 在数据库提交异常后先 rollback，再由 `upload_receipt_service.upload_commit_is_durable` 只读核实原 claim id、同 ledger、succeeded 状态、完整原 receipt，以及其原 Expense id/public_id 和 prepared task id/public_id/type。只在这些事实共同成立时继续原 postcommit 段。 | 原 lost-ack 例继续要求一次原 task/payload submit、原 timezone/OCC 和精确原收据；新源码仍须在 exact PG 执行。读回没有修改 ORM、补写 claim 或第二次业务 commit。 |
| 同一 prepared task / submit / HIT | 已证明提交的当前请求仍将内存中的同一个 `PreparedBackgroundTask` 及原 payload 交给既有 `submit_pending_expense_enrichment`；与普通 commit 成功共用唯一后置调用。原 HIT 直接返回已保存 typed receipt，绝不据此重新 submit。 | 旧 same-key 完整收据和不同 key 同图正控、postcommit submission owner 的既有失败语义均保留；没有新增后台扫描、payload 列、队列或启动 orphan 规则。 |
| 未提交或无法读取证明的异常 | 没有匹配持久收据、Expense/task，或 rollback/read 遇到数据库错误时继续抛原 commit 异常；已有不确定附件保留规则不变。退役“内存里已有成功 receipt 就能宣布接受/submit”的可能出口。 | 新增唯一 real-db 负控 `test_android_upload_uncommitted_attempt_cannot_submit_or_return_a_receipt`：提交动作实际抛错且未 commit，要求 500、claim/Expense/task 未持久、零 submit、原附件保留；恢复数据库提交后原 key 才首次成功。该新增例未在本机运行。 |
| Headerless / UploadLink / Web / API 协议 | 无 claim 的调用继续原 commit / rollback / 附件补偿规则；上传 body、header 可选性、鉴权、容量、UploadLink guard、Web 返回和 OpenAPI 均未改变。 | `test_uploads.py` 与本轮基线完整不变；focused 文件的全部既有函数 AST 不变。仅 request owner、focused 测试和本段变更，不改 Android 或其它工作树。 |

本轮实际秒级检查仅覆盖 Python AST、原测试 AST 保留、Ruff、diff、既有逐路径 scope 与定向 Lizard；不是 PG 或产品执行。没有本机 PG/Gradle/长测、提交或推送。修正后原 lost-ack 后置断言和新未提交负控的运行结果仍待主控发布新 exact 候选，不能用本轮源码检查宣称 GREEN。

### ceb36432 实际分层失败与只读收据 owner 迁移

基线 `ceb364325c8657e47c529ee253b3e76ccd44b26d` / tree `23742427e47ffcd278fe202e1862bf9ad4728a62` 的 Backend contracts job `101574447236` 由主控实读为 `route_layer_imports actual=1 allowed=0`：`_upload_request.py:21` 的运行时 model import 使 route 承担了持久查询。迁移前本机只执行现有 `_audit_codebase.audit_layer_violations`，实际复现同一处计数 1；没有执行数据库或产品。

| 直接责任 / 旧出口 | 本轮 after-impact 与退役范围 | 实际验证 |
| --- | --- | --- |
| 原 claim / Expense / task / 完整 receipt 的持久核验 | 原 `_upload_commit_is_durable` 整体迁至 `upload_receipt_service.upload_commit_is_durable`，这是唯一只读查询 owner；route 删除旧函数、select 及运行时 model import，只保留类型注解所需的 TYPE_CHECKING import。全部关联条件和完整 receipt 比较原样保留，没有第二个查询实现。 | 迁移函数仅规范化名称后 AST 完全相同；现有分层审计实际从 1 变为 0。 |
| commit 异常 → rollback / 核验 → 原 postcommit submit | route 仍负责当前请求的提交异常处理、附件补偿和唯一 submit 组合；service 不 commit、rollback、修改 ORM 或提交任务。不能证明原事务存在时仍抛原异常，HIT 和无 header 调用边界不变。 | route 其余 13 个函数仅规范化 service 调用名后 AST 全部不变，实际 submit 调用仍只有一个。`test_upload_intent_continuity.py` 与 `test_uploads.py` 完整保持基线，原 lost-ack 与未提交负控的断言未修改，也无需迁移测试 seam。 |
| 直接验证 producer | 新 service 与现有 request 路径均由原 classifier 选中 postgres/backend_frozen；合同不新增 heavy scope。没有改变 selector、阈值、API/生成 schema 或 Android。 | 两份 Python AST、Ruff、分层审计、逐路径 classifier 与 diff 检查实际通过；本机没有执行 pytest、PG、Gradle、提交或推送。新的 exact 候选仍须云端执行原行为与质量门，不能从该源码迁移宣称产品 GREEN。 |

### 917033ef：上传原收据能力协商的施工前影响与 test-first

本段基线为 `917033efed5d24893444863d0eb6b835b93564c8`。同 API 日期的旧服务器可能忽略上传的 `Idempotency-Key`，因此日期、货币写许可或请求已带 API header 均不能证明支持原收据重放。此次只补直接 producer 的行为反例和本段，不修改生产、DTO、生成 schema、持久化文件或队列。

| 入口 / owner / 实际消费者 | before-impact 与必须关闭的旧出口 | 直接验证 producer / 边界 |
| --- | --- | --- |
| 认证 runtime endpoint → `runtime_compatibility_service` → `_currency.RuntimeProductCapabilitiesResponse` → Android runtime DTO | 现有 `capabilities` 只有 currency。拟复用同一 owner，增加明确 `upload_original_receipt_version=1`；缺失或未知版本不能视为原收据能力成立，不改变 API 日期、鉴权或 currency authority。 | 现有 `test_runtime_snapshot_is_authenticated_private_and_product_facing` 的原 JSON 精确断言增加该字段，401/private/no-store/Vary 和原 currency 断言保留。旧 blanket `"receipt" not in serialized` 会排除合法产品能力，现按用户要求同轮纠正：完整公开 JSON 结构仍精确相等，所有公开对象禁止实际 `InstallationIdempotencyKey` 的 `receipt` / `request_fingerprint` 字段，原 C07 / Alembic 内容禁令保留。依据是 `models/currency_binding.py` 的安装维护回执字段及 runtime owner 的明确隔离，不通过改能力命名绕过隐私约束。 |
| 实际 `buildApiHttpClient` → auth → `RuntimeNegotiationInterceptor` → keyed app upload HTTP | 当前只识别日期和货币，缺能力仍 POST；请求预带 API header 又会绕过 runtime GET。未来带 key 的 app upload 必须先获得当前服务器明确能力，拒绝时零 upload send，不能尝试上传或退回无 key。`normalizeBaseUrl` 可保留 prefix，不能让相对 API 路径加 prefix 绕过 gate；这不裁定完整 prefix 部署支持。 | 新 `ApiClientUploadReceiptCompatibilityTest` 复用现有末端 transport interceptor 模式，真实执行 auth/negotiation。四个独立参数例覆盖 missing/unknown=2 × 原请求无/有 API header；其中 unknown+已有 header 项使用 `/capture/api/app/upload-screenshot`。假 transport 仅接受本例明确 upload 入口和当前根路径 runtime GET，返回 200 JSON，不能用 404 代替能力证据。四例均要求零 upload HTTP/body、409 升级指导；runtime JSON 始终同 API 日期、currency 正常。没有引用尚不存在的 DTO 字段或上传 API 参数。 |
| 支持能力的 keyed 请求 / 旧 headerless 上传 | 明确版本 1 才可发送原 keyed 命令；无 key 的旧消费者继续原语义，不能把新增能力塞进全局 `canWrite` 阻断其它写入。 | 两个独立正控分别为 supported=1 keyed 和 missing capability headerless；均要求一次 POST、原 multipart 字节/文件名/type、timezone、真实 API/currency/ledger/auth header 不变，key 原样或仍缺失。此处替换的是 HTTP 末端响应，不证明服务端实际接受或 PNG 处理。现有 SessionHeaders/Income/Outbox 用例不修改。 |
| 当前直接上传 / 未来持久原意图 / Failed Retry | `ExpensePendingRepository` 当前仍直接调用上传 API，新的 durable file/row/dispatcher 尚未落地。已有通用 Outbox `runtime_version_mismatch` mapped failure 保留原 key/body 身份，但不能据此宣称上传原文件已持久或可恢复。 | 本轮只精确证明 transport 的违规发送出口；既有 `OutboxProtocolRefusalTest` 原测试保留。未来 Capture 持久接线须独立证明原文件/row/binding、拒绝后的 Failed 与同命令 Retry；本轮不伪造这个层级。 |
| Headerless Android / UploadLink / Web / 生成 snapshot / CI | 旧三个实际入口及后端可选 key 仍保持；UploadLink/Web 不因此要求 app capability。生成 snapshot 的真实 Android `OpenApiContractGateTest` consumer 后续必须同步生产生成，不能只改 JSON fixture。 | 后端原 runtime 测试仍由既有真实 PG producer 执行；新增 Kotlin 路径由既有 Android JVM producer 执行。本轮不改 selector、现有后端 keyed receipt/事务反例、旧上传测试或 snapshot。新反例尚未执行，不能称行为 RED、编译通过或 GREEN；仅允许源码/静态短检查，云端由主控发布 exact 测试候选后取得。 |

本轮实际源码检查：Python AST / Ruff / diff 通过，原 runtime 测试文件其余 14 个函数 AST 不变；定向使用既有 Lizard producer，两份代码均无超过 80 行或 CC15 的函数，文件分别 499 / 113 行，未新增体量阈值越界。逐路径 classifier 实际为 runtime 测试 → postgres、新 Kotlin 测试 → android、合同 → 无 heavy scope。六个参数例尚未运行，没有本机 PG/Gradle/Edge、生产或 schema 写入、提交或推送。

### 22dbc9ad 实际能力反例与协议施工后影响闭合

测试候选 `22dbc9ad74c84f751ec1bea9374c1f1a32880d9e` 的 Android fast `101580549997` 已实际编译并执行。artifact `9999693413` 的 372 份 XML 共 2161 tests / 4 failures / 0 errors / 0 skips；四个 negative 参数分别在第 55 行得到 expected upload 0 / actual 1，精确覆盖 missing/unknown × 无/已有 API header，最后一个包含 prefix。其后的 negotiation 和 409 断言被首失败遮住。supported=1 keyed 与 missing headerless 两个正控完整通过，包含原 key、timezone、multipart bytes 与 API/currency headers。实际 backend ordinary 2/2 `101580549978` 为 1862 passed / 1 failed / 3 skipped，唯一失败为 runtime JSON 缺少该 capability；401、200、private/no-store、Vary、observed_at 前置条件已越过，后续私有字段断言被精确 JSON 首失败遮住。这里更正上段只按 heavy selector 将该 producer 记为 PG 的不足：此例实际在 ordinary lane 执行，没有 PG/JUnit 证明。两个执行 job 的 checkout `1b8d2d04` 与 source 同 tree；整轮其它 job 仍由独立证据目录记录。

| 真实入口 / owner / 消费者 | after-impact 与原出口处置 | 直接验证与边界 |
| --- | --- | --- |
| backend runtime capability | 原 runtime contract 增加 `UPLOAD_ORIGINAL_RECEIPT_VERSION=1`，唯一 snapshot producer 显式赋值，required schema 与唯一认证 route 显式投影。该能力对应已经在 `917033ef` 实际通过的八个原收据、fingerprint、rollback 和 lost-ack 控制；不来自客户端日期、数据库安装回执或另一个状态 owner。 | 当前 API 日期、currency/read/write/legacy conclusions、认证和 private/no-store/Vary 不变；原 runtime 精确 JSON 用例保持 test-first 断言。真正 OpenAPI generator 运行 3.3 秒，只增加该 capability 字段及 required 声明，没有手写生成快照或启动数据库。 |
| Android negotiation / keyed upload | 原 RuntimeNegotiationInterceptor 识别带 key 的 app upload POST，包含路径 prefix；即使请求已有 API header 也先查询实际同服务器 runtime。只有明确版本 1 才进入上传，missing、unknown、整个 JSON null 均保留明确 mismatch 409；不退回 headerless，不把未发送意图结算成功。非成功 runtime HTTP 保留 close/IOException，解析异常在上传前退出。 | 同一 interceptor 内的 `readCompatibility` 统一拥有原 runtime GET 的读取、关闭和解析，普通写入、income read 与新上传消费同一证据。六个原行为用例不修改；源码 review 核过 null/解析异常的零发送出口，这两个额外边界不是已运行的参数用例。 |
| Runtime DTO / 旧调用者 | capability 在 Android 为 nullable，缺省表示未证明。`toWriteCompatibility` 显式传递，既有 compatible/blocked helper 的缺省仍为 null。没有把该 capability 放入全局 `canWrite`；旧 income 可读分支、headerless 上传、currency header 替换与 revision-conflict retry 保留。 | 真实 OpenApiContractGateTest 已登记 runtime DTO，消费本轮真正生成的 schema。既有 SessionHeaders、Income、Outbox protocol controls 均保留。完整 durable row/file 的拒绝保留及 Retry 仍须后续真实接线，当前 transport gate 不冒充该证明。 |
| 完整 upload wire receipt | 既有 UploadResponseDto 过去静默遗漏 image_hash、thumbnail_path、duplicate_status、duplicate_of_id；现按真实类型补齐四字段且不设伪默认值。原 PendingUploadReceipt 继续只作为 task 观察投影，不能代替将来的完整持久 receipt。API 增加可选 Idempotency-Key，当前唯一生产 direct sender 完整不变，仍 headerless；未来唯一 dispatcher 必须传原 key。 | 全部五个 fake override 与三个直接 DTO 构造迁移，旧 binding 控制另断言仍无 key。原完整 JSON fixture 和全部旧断言保留，新增真实 Moshi 的包含 null 字段 JSON 往返及 DTO 往返；OpenAPI gate 新增 UploadResponse pairing，后续完整 receipt 存储须使用同等完整序列化。原 Room 恢复反例和八个 backend receipt 控制不改。 |

独立只读 review 对上述七个 capability 路径未发现阻断，九个 wire/API/直接测试路径已冻结。源码及短检查不等于新候选编译或运行通过；Android 文件、整批接受、原行回执持久化、唯一发送、顺序和新 VM 恢复仍未实现，本合同不提前关闭该缺口。

### 持久上传暂存的产品裁决与施工前边界

总 Goal 已授权 Codex 决定此消费级本地恢复能力的可逆产品实现。本片采用每次分享/选择最多 100 项、上传专属暂存目录累计 256 MiB 的接受上限，并在接受新内容时保留至少 32 MiB 可用磁盘余量。这是新本地持久暂存的准入政策，不修改后端 enrichment 容量或并发政策。累计量包含所有绑定、未完成/隔离/过期原件与尚待核准的孤文件，不能通过换账本或清空 VM 绕过。超限或磁盘不足发生在确认持久接受之前，保留尚未接受的原分享并给出明确的减少数量/处理原暂存项提示；不能仅接受前缀后静默吞掉尾部。不可读单项继续采用现有明确失败计数和其余可读项处理语义。

文件 owner 仅管理 app filesDir 下的专属目录、不可复用的原逐项 key 引用、原子写入和原 bytes 的长度/指纹校验，不拥有上传队列或调度器。原 filename/type/timezone/order 和 binding 由原命令 payload 一次冻结；同 key 的重新进入必须读取既有原件/原行，不能覆盖文件或重造 key，不同 key 的相同图片仍为独立意图。准备按顺序逐项落盘以控制内存；只有全部可接受项文件成立且同一个 bound Room 批次事务成功后，入口才可 consume。文件先于行；数据库结果不确定时保留原件供原行核准，不以异常推测未提交而删除。

删除方向相反：既有原行 Drop、明确停止整个未完成批次、clearAll、quarantine 清理或 Done GC 的条件删除成功后，才释放其原件；取消准备、VM dispose、断网、容量拒绝、协议不匹配、换绑定与过期均不删除已接受的文件。孤文件回收只能在此专属目录内，与所有绑定的实际原行引用核对并与接受互斥；存在无法解读其文件引用的原行时不能假定无引用。`onClearAll` 是调度通知而非删除证据，不能作为文件清理 hook。文件锁与 Outbox lease 的次序在真实批量接受/清理接线时必须统一，不能在持有 Outbox lease 时反向等待文件接受锁。

直接生产者继续为原真实 Room 重开反例以及新增窄文件/迁移/原 batch 接受与 engine 续传控制。上述数值与生命周期是施工决定，尚未实现或运行资格化；不得把辅助文件 owner 的存在当成用户恢复任务完成。

### eeabfedb 实际协议正控与协商入口收口

Android fast `101583536322` 的实际 XML artifact `10000063383` 共 2161 tests / 0 failures / 0 errors / 0 skips。能力的六个参数用例全部独立通过，四拒绝场景的零上传、实际 409 与协商断言均越过原首失败，两个允许场景仍保留原 key/body/headers。完整 upload DTO 往返与真实 schema gate 同轮通过。Backend ordinary 2/2 实际 1863 passed / 3 skipped，原 runtime 精确 JSON 及其后的隐私断言通过；三个 real-db 分片为 98/101/110 passed、均无失败/skips，原八个 receipt 控制按实际源码分片 producer 对齐。以上行为证据不等于整轮 CI 通过：实际 Detekt 对 `RuntimeNegotiationInterceptor.intercept` 报 CC 15，超过 14。

施工前后影响只涉及同一个协商入口决定：之前 caller 先判断 keyed upload，再另问 `requiresRuntimeNegotiation` 旧规则，两个位置共同决定是否绕过协商；现在既有 `requiresRuntimeNegotiation` 接收两个明确请求属性，并独自表达 keyed upload 强制协商或原 ordinary/income 规则。caller 只消费这个完整决定。布尔规则、实际 runtime GET、版本与能力拒绝顺序、body/key/headers 和所有原六用例不变，没有新 helper/file/owner 或门禁豁免。此窄修正还需下一 exact 候选真实 Detekt 验证；此前 Lizard 未解析出该函数，不能用其空记录声称复杂度已合格。

### Android 持久命令与原队列：施工前影响闭合

当前 source 为 `77b3e7bcb6e697dd94e1216f0e42b84c91c66946`。先前的 test-only 与 backend-only 限制是各自历史阶段；本阶段按同一总 Goal 施工 Android 真实持久链。原 Room 重开反例已经实际到达来源撤销、新数据库实例与新 VM 后的恢复失败，不能删除这个出口来关闭片。

| 入口 / 唯一责任 / 直接消费者 | 本阶段变更与必须保留的边界 | 直接生产者 |
| --- | --- | --- |
| 分享、picker、shortcut → launch handoff → Pending VM | 接受从 RAM 布尔值改为等待全部文件与一个绑定下的 Room 事务成立；入口在重入与未知提交时保留原逐项 UUID。新分享追加不隐式重试已经暂停的原项；每个明确的新意图仍有新 key，相同图片不能用 hash 去重成旧命令。Activity 与 shell 的旧提前成功出口一并迁移，不能只修改 VM。 | 原 LaunchShareHandoff、三个 Connected 入口、新真实 Room 重开与所有 VM 容量、普通失败、不可读、取消、身份控制；准备时机断言若依赖旧延迟读取模型，按新的接受后原件保证修正并说明，不能删行为断言。 |
| 文件接受 → Room `pending_mutations` → 观察 | 新 `UploadScreenshot` 是既有 Outbox 的具体命令；payload 冻结 batch、逐项顺序/UUID、准备元信息、timezone、原绑定。原行新增 nullable `receiptJson` 与默认 true 的 `blocksFollowing`，既有行迁移为 null/true；不新增表、第二状态账或把 bytes 存进 JSON。完整服务器 DTO 的含 null JSON 与 Done 在同一行更新中成立，原 payload/key 不覆盖。 | DB 17→18 的实际 Room migration 与 DAO；原所有 outbox fake/mapper/默认值消费者同步，生成 v18 只能从真实云端 KSP artifact 获取。 |
| DAO FIFO / claim / dispatch | 仅 Failed 可依据 `blocksFollowing=false` 放行后项，InFlight/Conflict 始终阻塞；其它种类默认 true 保留旧规则。上传容量、协议与身份拒绝挡住尾部并保留原件；普通上传失败保留 Failed 原行但允许后项继续。协议拒绝绝不能进入 Discarded/Done。 | `nextRunnableBatch` 与 `hasUnresolvedRowForTarget`、真实 DAO 和 Fake DAO，以及 engine 的容量暂停/普通失败/显式原 key Retry 控制。旧无生产 caller 的 DAO 方法也不能默认跳过。 |
| 原 engine / worker / scheduler | 现有 drainOnce 一次仅取每 target 一行，完成 A 后 KEEP 唤醒不足以保证 B/C 继续。需在原 owner 有界重取尚未尝试的尾部，同轮不忙重试失败 B，不添加第二 worker 或调度器。原 maxAttempts、七天 expiry、binding lease、取消与未知类型保持。 | 原 OutboxDrainEngine/Worker/Scheduler 控制及真实上传 fixture，不能靠测试手动发送 A/B/B/C 绕开生产队列。 |
| 原 direct sender / 成功收据 / 新 VM | `ExpensePendingRepository.uploadScreenshot` 的唯一 HTTP 发送迁移到具体 upload dispatcher，旧 RAM drain 退役。lastUploadAt、Pending refresh 和 enrichment 只消费服务器原完整收据；新 VM 从同一行恢复观察，不依赖原 URI、原 VM 或旧 scope。 | 原 ExpenseUploadBinding、Pending enrichment/advice 控制、新 Room 重开和完整 DTO 往返；本地接受不能生成已确认财务事实。 |
| Drop / Stop / clearAll / quarantine / Done GC / expiry | 删除由现有行条件变更决定；明确停止处理整个未完成上传批次。文件清理在 Outbox lease 释放后执行；孤文件回收在文件锁内读取所有绑定原行引用，未知引用不删除。dispatch 读文件须核对原 key/length/hash，不重做准备。 | 文件 owner 八项真实 Android 文件测试、行删除与孤文件控制、已有身份和过期测试；onClearAll 调度通知、VM dispose、换账本和网络失败均不是删文件证据。 |

文件 owner 的源码已具备有界顺序写入、AtomicFile 恢复、完整性验证及跨实例文件锁，原件全部成立后才运行 Room 回调；未知回调结果保留原件。八个文件测试已编写但尚未编译执行。该部分没有接入用户入口、队列或调度，不能据此宣称上传恢复完成。

### 77b3e7bc 后 Android 基础模型的施工后影响与验证边界

`77b3e7bcb6e697dd94e1216f0e42b84c91c66946` 的 CI `34070642303` 与 CodeQL `34070642301` 已完成且成功，实际 Android fast `101587250641` 执行了 JVM、两项 Detekt、lint 和 Room schema 门；成功任务没有上传 JVM XML，不能沿用前一个候选的 2161 数量冒充本轮 XML 统计。Connected `34070642318` 的原 XML `10000584636` 为 129 tests / 1 failure / 0 errors / 0 skips，唯一失败仍是原 Room 重开用例等待 canRetryUpload；原三个入口控制通过，原 Retry 与 B/C 发送尾段尚未到达。

| 原责任 / 所有直接消费者 | 本候选 after-impact 与旧出口处置 | 直接生产者 / 尚未闭合 |
| --- | --- | --- |
| Room 原行 / schema / Fake | DB 17→18 增加完整 receiptJson 与默认 true 的 blocksFollowing；原行 key、body、OCC、归属、隔离默认均保留。collection insert 是唯一批次事务，原行查询包含已完成状态；原型映射和 Fake 全部迁移。未知 raw type 仍可供完整文件引用核准。 | 新实际磁盘 Room 八例及 migration 一例，尚未执行。schema18 尚未提交，必须下载下一云端 KSP 实际产物再纳入候选，不手写生成文件。 |
| FIFO / 原子 claim / 同一 engine | DAO 的选择、claim 与 target 检查复用同一 Failed blocking 判定，只有明确非阻塞 Failed 放行；earliest Pending 判定在排除本轮 visited 之前成立。原 dispatch lease 现在包括 claim、epoch 核对、HTTP 与结算，避免 Stop 后旧 claim 仍发送。engine 在原 owner 内分开有界遍历、原行发送、结果结算，每次最多处理 100 个候选且每行只尝试一次；空批次及上限出口都检查未排除 visited 的真实 runnable，保留并发 Retry 后重新可发送的原尾项唤醒。 | 五个新 engine 组合控制覆盖容量、普通失败、transient 不忙重试、100 项上限及 stale C / Retry B 竞态；原 cancel、epoch、maxAttempts 控制未改。拆分后删除 drainOnce 的两条旧 CC/LongMethod baseline，不迁移豁免到新方法，实际 Detekt 仍待云端。 |
| 原 Worker 成功分类 / 旧测试 | mixed Done 不再把尚待 retry 或 binding abort 的命令结算成整轮 SUCCESS，continuation 同样保留 RETRY。旧两条 SUCCESS 断言随错误产品模型纠正。原 engine 三例改为实际观察同轮发送的后项，保留并加强其 OCC、原 payload/key 与实际发送次序断言；不是恢复旧的一轮只发一个 target 的限制。 | 原 Worker/Engine 测试加上述五例尚未执行。KEEP 在当前 worker 最后一次查询后仍可能吞并发 enqueue 唤醒，调度接线继续处理；本候选不宣称 WorkManager 闭合。 |
| 原文件 / 同键接受重入 / GC 引用 | FileStore 在同一跨实例文件锁内，先交还原行 owner 核对既有完整接受，再准备来源；已提交原批次直接返回原 IDs。文件落盘先于单 Room 事务；未知提交结果保留文件。已有直接文件读取、两实例接受/引用互斥、限额、AtomicFile、引用不明禁止 GC 等八例保留，追加同原批次并发重入零 URI 读取例。 | 九个真实 Android 文件用例尚未执行；入口与所有删除 hook 尚待真实接线，不能凭原件辅助 owner 宣称用户恢复完成。 |
| payload / dispatcher / 完整收据 / Sync 类型展示 | 新具体 UploadScreenshot dispatcher 消费固定 revision、batch/order、完整原 owner、文件和 timezone；不重新准备或换 key。容量/协议/身份失败阻塞尾部，普通失败保留 Failed 并放行，404 不进入 Discarded。Success 的完整含 null receipt 与原行 Done 同次更新；上传不触发 confirmed advice。SyncStatus 全枚举 getValue 消费者增加上传标签。 | 四个 payload 与四个 dispatcher 用例和既有全枚举标签控制尚待运行。dispatcher 尚未注册，旧 direct sender / RAM 上传循环、Activity/shell 提前 consume、新 VM 恢复和删除 hook 仍在施工，PR 保持 Draft。 |

本机只执行 diff、现有文案审计（47 条既有 allowlist 未增加）、逐路径 scope 与 pinned Lizard 的秒级源码检查。基础候选代码路径仅选中 android；Lizard 新增函数无 >80 行 / CC15 超额，AppDatabase 旧 migrate 及其解析器误归属的 expenseDao 跨度仍需按实际报告分层解释。这些不是 Kotlin 编译、Room、Detekt 或产品 GREEN；整个上传任务仍须原 Room 重开反例和全部生产消费者完成后才能闭合。

### ff10 实际结果与完整提交链施工

source `ff10e515cc3b1f21513e56face622edbee0d20f6` / tree `ca93123c6a9a29342ff496bb760301e77f40fbc3` 的 CI `34072964200` 已失败结束，CodeQL `34072964201` 成功；实际 Android fast checkout `38c3d6c9aad884710a6d4c44fa0991f761c33a92` 的 tree 已独立读回相同。fast XML 为 375 suites / 2174 tests / 1 failure / 0 errors / 0 skips；新 payload 四例、dispatcher 四例、同轮继续五例与原 engine 27 / worker 17 例均通过。唯一 JVM 失败为 DebtAdjustment 旧测试仍预期一轮只发送一项，实际已经发出两项；后项的原 OCC 与冲突必须保留，不能为了旧计数恢复错误的一轮停工。由于 JVM 先失败，不能宣称本轮 Detekt、lint 或 count ratchet 通过。

Connected `34072964199` 的原 artifact `10001343267` 为 147 tests / 1 failure / 0 errors / 0 skips。九个实际文件例、八个真实 DAO 例及 schema17→18 migration 通过；唯一原 Room 重开反例仍在恢复 Retry 前失败，B/C 尾段未达。CI 的其它实际失败分别为：原 SQL 静态消费者仍匹配已退役别名、Upload dispatcher/实际入队消费者未登记，以及 release KSP 读取新 schema18 的 JSON EOF。不是测试环境已被证明偶发。真实云端 fast KSP 生成的 schema18 已取回，SHA256 为 `631f321f03b391e1f2e43837654cd4a2a60bc38c48fd619e9a88c480762b82cf`；后续候选纳入该实际生成文件再验证 release。原 XML、日志与 `execution-index.json` 位于独立 qualification 目录，不进入产品源码。

下列接线沿前述施工前表继续，仍是未资格化源码；不能把 ff10 的基础测试结果给它们背书。

| 已列入口 / 消费者 | 本次施工后责任与旧出口退役 | 直接验证及待证 |
| --- | --- | --- |
| 原文件 → 一次 Room 接受 → Repo 观察 | `UploadIntentRepository` 复用 FileStore/Outbox；原批次逐项编号先核已接受原行，再读取来源，单次 enqueue collection 持久化。观察包括 Done 的完整 receipt，lastUploadAt 由同一收据投影，设置写失败不重发。 | 真实磁盘 Repo 控制覆盖未知 Room 确认、重开零 URI 读取、原时区/key/完整收据、部分旧行禁止重建、未知类型/错误 owner 禁止回收、权限与取消；尚未执行。 |
| Activity / shell / picker / Route / VM | 每个原 selection 分别保留稳定编号和首次实际尝试的完整 binding；热分享到达不能改变正在接受的正文。只有文件和 Room 成立才 ACK；首次失败、页面重入、未知确认和 binding 变化不能换 key 或改收到账本 B。未接受 selection 的显式重试与已入队原组恢复分开，忙状态翻转不能触发无限 Retry。VM 只观察原行并调用接受/恢复，旧 `PendingUploadSession` RAM sender 退役。 | 原实际 effect 与工厂、真实 Room 重开反例及 Launch handoff 控制同步迁移；准备 A 期间原“已 consume”断言纠正为仍保留，保序、晚到 C、重入和原 Retry 后置条件继续检验。尚待完整接线与云端执行。 |
| 唯一 HTTP / DI / 原成功消费者 | AppContainer 注册唯一 `UploadScreenshotDispatcher`，工厂必填传 UploadIntentActions；ExpensePendingRepository direct HTTP、PendingReviewActions 旧 upload API、ExpenseRepository 委托与旧 direct HTTP fake 物理退役。旧 `ExpenseUploadBindingTest` 两例由真实 Repo/原文件/engine 的绑定与原 key 重试控制接替，不能只删测试。收据任务查询接收原完整 binding 并在实际 IO bindExact。 | 新接受不发 HTTP、A/B/B/C、普通失败继续尾部、容量再次暂停、不可读项不阻塞、完整原收据/文件/时区/key 控制在真实发送链验证；VM 测试只证明 typed projection 和动作，不再伪造另一个上传循环。尚未执行。 |
| Stop / 全部删除 / 文件引用 | Outbox 必填 `onRowsDeleted`，clearAll、clearExistingRows、clearQuarantined、Conflict Drop、Failed Drop、Done GC 和组 Stop 都在实际删行后、释放 lease 后回收。Stop 是单条 owner/ledger/type/target/非 Done 条件删除，保留原 Done 收据和其它记录。FileStore 删除只允许完整原行引用核查；没有生产消费者的按 key 直接删除辅助方法退役。 | 七条入口的真实文件+Room 参数控制、真实 DAO Stop 及错误状态重复删除负控新增待执行；原未知引用负控继续保留。 |
| 无行孤文件与未知接受的唤醒 | 复核取消准备已明确产生“有 A 文件、无 Room 行”，而原 collector 只有删行 callback，下一次接受仍可能被无行孤文件占满。另原 Room commit 成功但 ACK 丢失后，原行重入分支没有补回漏掉的 onEnqueued。这两条旧成功/恢复出口均裁 FIX，不能保留零唤醒为要求。 | 新反例要求下一接受前回收无引用旧 prefix、跨账本仍有引用原件保留；原 lost-ACK 测试改为要求原 Pending 得到一次原调度唤醒，文件/body/key 不变。当前仅 test-first，生产两处尚未修正，需下一 exact 云端 RED 后闭合。 |
| 原 Scheduler 最后读取后的 enqueue | KEEP 在旧 Worker 最后一次空读与完成之间吞掉新 enqueue；更多空读不能关闭该窗口。拟使用同一 unique work 的 APPEND_OR_REPLACE 保留正在运行者及持久后继，取消后可起新链，保留网络约束/backoff/periodic owner。 | 新 JVM Robolectric 4.16.1 / SDK35 / 既有 JDK17 测试使用官方 WorkManager/TestDriver/真实 Room，WorkerFactory 只控制最后 Result 的时机。无 RestrictedAPI、全局 AndroidTest delegate 或 suppression；生产仍 KEEP，等待实际 RED。 |
| 两处 SyncStatus / 通用旧恢复 | Workspace Settings 与 Obligations 同步页都连接原收件箱入口；上传从通用 Retry/KeepMine 消费集合移出，VM 同步禁止该旁路。原行 Drop 仍先确认并经过实际删行回收；收件箱按 typed original 提供文件名/顺序及专属恢复，不解析 raw JSON 冒充上下文。 | 新实际 UI 入口控制要求没有通用 Retry，点击查看待上传截图才进入原组；VM 原行快照控制禁止 fresh token 或通用 Retry 改写。其它更正/往来控制只迁移必填导航参数，未改业务断言。 |

全体 Outbox 构造者显式迁移新的删除 callback；不使用文件的纯持久测试显式空 hook，真实上传 fixture 与生产组合接实际 collector。DataQuality 的修复跳转会真实建立 Pending VM，故它使用同一 UploadIntentRepository/Room 观察，不能保留会在首次订阅即抛错的未实现 proxy。原 SQL 静态消费者与 dispatcher callsite 登记已按实际 source 修正，未增加 allowlist 或放宽阈值。此段仅源码/直接验证生产者闭合记录，PR 仍 Draft，未合并，整个 Capture 与总 Goal 均未完成。

### 2c84d60f 实际反例与接受入口闭合

source `2c84d60f5e5bc502d43691eb14cacefb2c46271c` / tree `161bace602953a6d9db02a6a43d0b42908a4ddcf` 的 Connected `34076984982` 实际 XML artifact `10002669482` 为 166 tests / 2 failures / 0 errors / 0 skips。失败恰为下一次接受未回收无行孤文件、原 Room 已接受但 ACK 丢失后重入未唤醒 Pending。其它 164 项包括真实 Room 重开、来源 URI 撤回、原 A/B/B/C 恢复及全部删除回收入口通过。

对应此前 before-impact 两条 FIX，全部 share/picker/shortcut/显式重试仍进入唯一 `acceptUploadBatch`。该入口在原绑定及写权限核准后调用既有完整引用 collector，再进入既有文件锁下的接受事务。collector 继续保护所有账本/owner 的引用，未知原行禁止回收；未增加后台清理 owner。完整原批次重入仍在读取 URI 前返回原接受收据，同时仅在原行含 Pending 时补发既有调度通知；Failed/Done 不自动重试，原文件/body/key/timezone 不变。原接受后持久化、Activity ACK、receipt 观察、显式恢复与七条删除路径继续复用原链。上述两条实际失败测试及未知引用、跨绑定原件控制负责下一 exact candidate 验证；本段不宣称新源码通过。

CI `34076984994` 的 Android fast 在新 Scheduler 测试编译阶段缺少 `CallbackToFutureAdapter`，没有执行 JVM 行为反例。按照官方 WorkManager 2.11.2 POM 所用 concurrent-futures 1.1.0，仅补直接 testImplementation 依赖及版本目录；生产 KEEP、约束、backoff 与周期 owner 不变，仍待真实调度反例执行。

同一 CI 的 Windows 浏览器 12 项实际执行中有 1 项在 layout probe 产生结果前超时，尚未到 response-loss 注入。与 CSV b9d8f67b 的另一实际超时都不能认定根因或偶发。施工前追踪现有 `evaluate_page` 的所有测试调用者；仅给原超时出口增加固定枚举/布尔的页面阶段观察，并在两条真实 bootstrap 测试补创建/剩余文件计数。原 10 秒判定、两次仅 transport 重试、故障注入与业务断言不变；不输出 URL、路径、cookie、token 或原错误文本。此为测试诊断，不修改 Manager/Backend/Windows 生命周期；下一云端 native 结果才能判定实际停留阶段。

### ded10135 调度反例与完成前的 owner 清理

source `ded1013521bce4de3e62bfa376e6761feee2b666` 的 Android fast job `101610640938` 已实际执行 2176 项 JVM；原 XML artifact `10003189992` 中 Scheduler 两例执行，取消后重建原链通过，最后空读之后的 enqueue 则精确失败于 WorkManager 只有原 RUNNING 工作、缺少持久后继（expected 2 / actual 1）。这不是编译失败。对照同版官方 `ExistingWorkPolicy` 源码，唯一即时工作策略改为 APPEND_OR_REPLACE；全部插入/恢复入口继续调用原 `enqueueOnce`，保留运行者、WorkManager 持久化及取消后新链，网络约束、指数 backoff、周期 UPDATE 与原 Outbox payload/OCC/key 不变。真实队列和发送后置条件由同两例在下一 exact candidate 核准。

同轮另一失败为邀请 JVM 测试的 ViewModel 在 resetMain 后仍有 IO continuation。该类 11 个既有用例都自行创建真实 ViewModel，却未在测试结束前取消并等待其 scope；读取到 UI state 不等于 owner 已结束。现在每例 finally 都先取消并等待自己的 owner，再撤销 Main dispatcher。11 条业务用例及断言、真实 IO、生产邀请接线均保持；不添加 sleep、重试、全局 executor 或弱化协程错误。这是直接验证生产者的生命周期纠正，需要下一 exact JVM 结果验证。

### 57790620 executed scheduler closure and remaining qualification

Android fast job `101613484922` / XML `10003528347` executed 2176 tests / 0 failures / 0 errors / 0 skips, including both real WorkManager controls and all eleven invitation owner lifetimes. Connected `34080032944` and CodeQL `34080032995` succeeded. This candidate still failed CI: Detekt reports PendingRoute length 65 against 60, and Desktop manager had two Node-only probe subprocess timeouts at the existing 10-second boundary. These timeouts precede the fake DOM result and establish no browser/product root cause; original logs remain under the external 57790620 evidence directory.

PendingRoute now returns the existing captured eligibility value directly after its guarded picker launch, removing duplicate true/false branches; its one-expression data-quality navigation callback uses the normal inline form. Both callers, URI acceptance, binding, receipt handling, lifecycle effects and downstream navigation are unchanged. No function extraction, threshold adjustment, suppression, retry or timeout increase is introduced. The next exact candidate must qualify Detekt and the unchanged Desktop producer; prior successes do not qualify this source.

### 207b3c03 persistence encoding duplication

Android fast `101616924006` reaches another existing Detekt boundary: OutboxRepository exceeds the 600-line class limit. Root traced the added acceptance code and found the single-command and batch-command paths constructing the same PendingMutationEntity independently. Before/after closure keeps binding validation, aliases, leases, one batch timestamp, original duplicate-acceptance checks, afterPersisted and scheduler timing at their existing owners; only the duplicated immutable record encoding moves onto the existing PendingMutationIntent value. Both insertion paths now call that one encoder. This removes duplicate representation responsibility without another writer, file, binding callback, suppression or threshold change. Existing single/batch original identity, durable acceptance, replay and Room controls must qualify it at the next exact source. Desktop manager passed at 207b3c03 with the original 10-second pure-probe timeout; the earlier timeout remains recorded and its environmental cause remains unknown.
