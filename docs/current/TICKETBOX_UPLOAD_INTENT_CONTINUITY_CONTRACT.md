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
| `handle_upload` 的 keyed 原业务 commit | 原来 commit 抛错后只回滚并返回异常，已经落库的 queued task 没有提交出口。现在 `_commit_upload` 在数据库提交异常后先 rollback，再由同文件只读查询核实原 claim id、同 ledger、succeeded 状态、完整原 receipt，以及其原 Expense id/public_id 和 prepared task id/public_id/type。只在这些事实共同成立时继续原 postcommit 段。 | 原 lost-ack 例继续要求一次原 task/payload submit、原 timezone/OCC 和精确原收据；新源码仍须在 exact PG 执行。读回没有修改 ORM、补写 claim 或第二次业务 commit。 |
| 同一 prepared task / submit / HIT | 已证明提交的当前请求仍将内存中的同一个 `PreparedBackgroundTask` 及原 payload 交给既有 `submit_pending_expense_enrichment`；与普通 commit 成功共用唯一后置调用。原 HIT 直接返回已保存 typed receipt，绝不据此重新 submit。 | 旧 same-key 完整收据和不同 key 同图正控、postcommit submission owner 的既有失败语义均保留；没有新增后台扫描、payload 列、队列或启动 orphan 规则。 |
| 未提交或无法读取证明的异常 | 没有匹配持久收据、Expense/task，或 rollback/read 遇到数据库错误时继续抛原 commit 异常；已有不确定附件保留规则不变。退役“内存里已有成功 receipt 就能宣布接受/submit”的可能出口。 | 新增唯一 real-db 负控 `test_android_upload_uncommitted_attempt_cannot_submit_or_return_a_receipt`：提交动作实际抛错且未 commit，要求 500、claim/Expense/task 未持久、零 submit、原附件保留；恢复数据库提交后原 key 才首次成功。该新增例未在本机运行。 |
| Headerless / UploadLink / Web / API 协议 | 无 claim 的调用继续原 commit / rollback / 附件补偿规则；上传 body、header 可选性、鉴权、容量、UploadLink guard、Web 返回和 OpenAPI 均未改变。 | `test_uploads.py` 与本轮基线完整不变；focused 文件的全部既有函数 AST 不变。仅 request owner、focused 测试和本段变更，不改 Android 或其它工作树。 |

本轮实际秒级检查仅覆盖 Python AST、原测试 AST 保留、Ruff、diff、既有逐路径 scope 与定向 Lizard；不是 PG 或产品执行。没有本机 PG/Gradle/长测、提交或推送。修正后原 lost-ack 后置断言和新未提交负控的运行结果仍待主控发布新 exact 候选，不能用本轮源码检查宣称 GREEN。
