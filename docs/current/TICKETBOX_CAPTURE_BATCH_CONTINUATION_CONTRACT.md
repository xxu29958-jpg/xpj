# 多图上传的中断续传

- Goal：完成总 Goal 已接受的 Capture 缺口。A/B/C 分享批次在 B 因容量受阻后，原 Retry 应继续 B、C；A 不重发，所有发送仍属于原账本与权限上下文。
- Allowed Changes：既有 Pending 上传意图 owner、URI 准备的薄边界、真实 Route/Retry 接线及直接测试。复用现有 repository/receipt/enrichment，不新增上传框架或 outbox。
- Forbidden Surface：不改服务端容量与附件归属规则、不删原图/已接受附件，不更改 Windows 生命周期。不把内存 URI 字符串声称为持久读权限，不宣称进程重启恢复已成立。
- Done Checks：A/B/B/C 实际调用序列；B 复用已准备字节，C 最终产生 receipt；再次容量拒绝保留尾部；尾部不可读有准确累计失败且继续剩余项；切账本、降权、旧代次回调、取消、页面重入不会重复或跨账本发送。真实 Pending Retry 接线可执行；暂停只由原 Retry 继续或明确停止余下上传，新分享不能静默替代旧批次。原 picker/shortcut/share 消费语义成立，被替代批次循环与单图恢复责任退役。
- Evidence：短源码/纯反例优先，JVM/Connected 在 exact head 云端；禁止本机十分钟级测试。该片闭合不代表全 Capture 生命周期或全 Goal 完成。

## 施工前 impact closure：实际基线 5d460626

| 路径 | 已核实旧行为 / 待完成迁移 |
| --- | --- |
| 所有入口 | MainActivity 冷/热 ACTION_SEND 与 ACTION_SEND_MULTIPLE，经 LaunchIntents 的保序去重进入 ShareImages；TicketboxApp 的 LaunchActionState 单槽交 PendingRoute。Pending 普通/空态/只读提示的上传入口及 UploadReceipt shortcut 共用 Route 单图 picker。逐项确认接受、取消和 consume 时机。 |
| 批次 owner 与旧出口 | PendingRoute 先消费整个分享；PendingUploadConsumers 的 for 游标活在 Route coroutine，B capacity 后 Stop 直接 return；PendingViewModel 的 CapacityRetryIntent 仅保留 B 的 PreparedUploadImage。移交完整批次给现有 VM owner 后再 consume；退役页面协程的业务循环和只能恢复单图的责任。 |
| 持久化、权限和恢复 | 当前 Activity 明确内存路由，无持久 URI 授权；C 到执行时才读取。使用 applicationContext/既有 IO，不能把 Activity 留在状态里。原 upload guard/账本代次及取消 owner 继续限制发送；不得把尾部重绑到新账本。VM 生命周期内的继续与进程死亡恢复是不同证据，后者保持未资格化。 |
| 实际消费者与成功出口 | ExpensePendingRepository 在线 upload/guard、lastUploadAt → PendingViewModel refresh 与 enrichment receipt 观察 → Pending UI。单图及批次必须汇总真实 accepted/unreadable/failed/paused 状态，暂停不能冒充整个批次结束。Retry 必须由同一批次 owner 推进余项。 |
| 直接验证生产者 | 现有 share upload 与 upload failure 测试只证明暂停在 B，未证明 Retry 后 C。延长实际生产边界反例；保留 picker null/shortcut/share consume 不自取消用例。Android source/test 逐路径核 ci_scope 的 android 输出，fast 与 Connected 的真实消费范围分别记录，不能用整体 PR 恰好触发掩盖漏线。 |

施工后须按同表逐项核实入口/消费者/旧成功出口/持久化协议恢复/生产者；任何“不受影响”结论必须给出实际调用或执行证据，未知影响不得跳过。完成声明严格限定在可验证用户后置条件。

## Test-first 反例交接（生产仍为 5d460626）

`PendingViewModelShareUploadTest.capacityRetryContinuesTheUnsentShareTailWithoutRepeatingAcceptedImages` 延长原来的容量暂停用例：调用真实 `uploadSharedImageSequence` 一次，A 成功、B 首次容量拒绝，随后只调用 UI 已绑定的 `retryCapacityUpload`。断言暂停时仅准备/发送 A、B，Retry 后发送 A/B/B/C、仅准备 A/B/C、四次请求仍属 owner 账本，三个已接受 receipt 对应记录经现有 refresh 出现在 VM 列表。仓储 fake 仅模拟拒绝及成功后查询结果，没有测试自写的批次推进循环。

本阶段只修改该测试，保留既有单图重试、切账本、旧准备结果及失败累计用例；没有宣称这些用例已重新运行。静态可见旧 owner 预计只能发送 A/B/B，实际 RED 与后续 GREEN 交 exact head 云端 `Android fast` 的 `:app:testGrayDebugUnitTest` 取得；本机未运行 Gradle、PG 或产品。实际 `classify_ci_paths` 对该测试及 `PendingRoute`、`PendingUploadConsumers`、`PendingViewModel` 四个路径逐项执行，均仅置 `android=true`。Connected 的 picker/shortcut/share 接线仍需独立执行证据，本 JVM 反例不替代它。

生产施工应让既有 VM 上传 owner 接受并保留完整批次后再消费 launch action，由原 Retry 推进 B 与未准备尾部；URI 边界继续只负责准备。现有 `PendingUploadConsumers` 的页面协程业务循环与仅保存单图的恢复责任必须随迁移退役，repository 的账本 guard、receipt/refresh/enrichment 仍由现有 owner 承担。完整施工后 impact closure 留待生产修改与对应验证，当前仅完成直接验证生产者的反例补齐。

首个云端 run `34034258931` / Android fast `101489352058` 在 Kotlin 测试编译阶段失败：新增断言将 `List<String>` 与 fake 已有的 `MutableList<String?>` 交给泛型 `assertEquals`，不能推断统一类型。仅将期望列表显式声明为 `List<String?>`，四个非空 owner 值与全部断言不变；未改 fake、生产协议或账本可空性。该失败不是上传缺口的运行反例，必须等修正 head 执行 JVM 后再记录 RED。没有本机 Gradle 执行。

## 生产施工与 impact closure（028e1393 后工作差异，待云端资格化）

主控已读 source `028e139369b9de73bd5f5becb7e48878ddaadbf9` 的 run `34034849819` / Android fast `101490961229`、artifact `9989886610` 实际 XML：2089 tests、1 failure；上述 share 测试明确 expected A/B/B/C、actual A/B/B。这是实际行为 RED，不是编译线索。本节记录其后的未提交施工，不能借 RED head 的其他 PASS 声称新实现 GREEN。

| 已核路径 | 施工后 owner / 全部直接消费者 / 对应验证生产者 |
| --- | --- |
| Activity → Shell 的连续分享 | `MainActivity.onNewIntent` 使用 `LaunchIntents.mergeLaunchRequest` 合并未移交 ShareImages；`clearHandledLaunchIntent` 只删本次已移交的前缀。Shell 的 `LaunchActionState.post/consume` 同样保序合并、只消费已接受前缀。`TicketboxApp.LaunchRequestEffect/dispatchLaunchRequest` 原路由不变。`LaunchShareHandoffTest` 对真实 state 的双 post、移交窗口、Activity 纯裁决与非 share 变体逐项断言，原单槽“后分享覆盖前分享”责任退役；不建立持久队列。 |
| 分享 / picker / shortcut → 接受 | `PendingRoute` 的 picker 结果非空时也 post UploadSharedImages；null 不 post。`PendingLaunchActionEffect` 同步调用 `PendingViewModel.acceptUploads` 成功后才 consume。普通及空态按钮由 `PendingUiState.canStartUpload` 禁止 busy/paused 新选图，shortcut 等可打开时才消费；外部 share 可加入正在运行或暂停的同一批次。`PendingLaunchActionEffectTest` 用实际 ActivityResultRegistry 验证取消/选中，实际 effect 验证 shortcut 暂停与消费；原空态 / viewer CTA Connected 测试继续消费这两个组件。 |
| 唯一上传 owner / 明确停止 | `PendingUploadSession` 是 VM 生命周期内的具体批次 owner，持有 cursor、原 B 字节、尚未准备的 tail、逐项 URI 准备入口、失败累计、原 binding/generation。暂停追加 D/E 只接到 C 后，不自动重试；原 Retry 驱动 B/C/D/E，连点不启第二 worker。`discardCapacityUpload` 只停止暂停中未发送余项，真实 `PendingScreen` 显式按钮经 `pendingScreenChromeActions` 接线；已接受 receipt 不撤销、不删附件。`PendingUploadConsumers.kt` 整文件及 VM 旧 CapacityRetryIntent / PendingUploadAttempt / 单图 performUpload 链物理退役。`PendingViewModelShareUploadTest` 保留原 A/B/B/C 后置条件；`UploadContinuationTest` 补暂停追加、原 bytes 引用、明确停止后新选择。 |
| URI、页面和取消边界 | `PendingUploadSource` 只捕获 applicationContext，在原 Dispatchers.IO/prepareScreenshotUpload 边界按执行顺序读 URI；不保留 Activity。Route effect 结束不取消 VM job；VM scope 结束或旧代次失效会取消并释放该内存批次，旧回调不能释放新批次。`UploadFailureTest` 覆盖 scope 取消、不可读及两次容量暂停后的累计失败；Share 旧准备回调用 NonCancellable 延迟交回验证不会借新代次。Connected 使用实际 VM、effect、生产 chrome 与 PendingScreen：A 准备时接收第二分享 C，移除页面组合，B 暂停后重入点真实 Retry，断言 A/B/B/C、C 经 refresh 进入列表。它不证明进程死亡恢复或真实图库持久权限。 |
| 原 binding / 权限 / repository | 施工前补查发现 ledgerId flow 会 distinct 掉同账本 ID 下的 origin/account/session 变化。`PendingReviewActions.currentUploadBinding` 由 ExpenseRepository → ExpensePendingRepository → 原 LedgerRequestGuard.captureLogicalBinding 提供；接口无默认实现。唯一生产 ScreenshotUploadRequest producer 是新 session，`expectedBinding` 必填并替代 ledger-only 字段；接收、追加、准备后、Retry、结果发布均核原 binding/generation/role，repo 最后用现有 bindExact 防检查到发送之间的重绑。FakeReviewActions、ThumbnailFakeReviewActions 与 Connected fixture 全部显式实现新入口，Thumbnail fixture 意外上传直接失败。`ExpenseUploadBindingTest` 用真实 repo/guard/session fixture 与 ApiService fake，断言同 ledger 换 origin/account 零发送、同 binding 重试两次相同 bytes 调用及原解析器保留构造的结构化 HttpException；不是实际 HTTP 网络资格化。VM 测试覆盖同 binding 拒绝后成功。无 wire API、token、OCC、Outbox 协议修改，其余 Pending mutation owner 未迁移。 |
| receipt / 旧成功出口 / 提醒与列表 | upload 仍走 ExpensePendingRepository 原在线 API、guard、lastUploadAt 更新；每个 accepted receipt 仍由 VM 调 onDataChanged → refresh 与原 enrichmentObserver.track。失败或 capacity 不调用 receipt 出口；onState 区分运行、暂停及失败汇总。Enrichment / AdviceInvalidation 原测试全部迁移至 acceptUploads，保留 terminal observation、独立任务、旧刷新丢弃、上传不失效预算建议的语义；更正/确认等旧消费者未重写。类拆分降低 PendingViewModel 960 → 740 物理行，新 session 169 行、URI 边界 18 行；此行数只作导航，不能代替 detekt/weight 云端判定。 |

导航补查：`MainProductNavigationPolicy.OpenRoot` 的 clearBackStack 曾引出 Inbox VM 是否会销毁的疑点；继续核 `MainNavGraph.MainProductNavHost` 发现 startDestination 固定 Inbox，Switch/OpenRoot 的 popUpTo 不含该 start entry。因此没有成立的导航反例，保留现有 PendingRoute ViewModel factory scope，不新增 Main-route owner。页面组合移除和 ViewModelStore 销毁必须分开报告。

“已接受”指 VM 已同步接管这组引用及其当前 binding；网络 receipt 是另一个后置条件。“未接受”分享仍由既有 Activity/Shell 移交槽持有，只合并尚未移交的 ShareImages；非分享变体保留原路由。暂停中的旧批次不会因新 share、picker、刷新或页面重入被静默替代。无本地持久 URI / Outbox 或未知网络提交重放能力的新增声明。

验证层：本地仅执行差异/旧符号及调用搜索、strings XML 解析、真实 `classify_ci_paths` 逐路径分类；28 个 Android 新增/修改/删除路径均 `android=true`，其他 heavy scope=false。当前合同文档为文档 scope；没有修改 workflow、baseline 或门禁阈值。两个 workflow 均消费同一 classifier：`ci.yml` Android fast 执行 compileGrayDebugKotlin / testGrayDebugUnitTest / count / lint / 两个 detekt；`android-connected-test.yml` 执行 connectedGrayDebugAndroidTest。新增 10 个 JVM 用例、Connected 净增 2 个用例仍待主控 exact candidate 云端实际执行。本机未运行 Gradle、PG、模拟器或产品，无 commit/push。

体量基线来源：主控提供的 run `34034849819` repository-codebase-weight artifact `9989905213` 已仅在内存提取相关记录，报告 base=`5d460626`、current=`02ec45d4`（云端 merge checkout，并非 source 028e1393），原 verdict=NO DEBT REGRESSION。PendingViewModel 原 960 行 / code 695，PendingUploadConsumers 原 143 行 / code 123；本片不重跑全仓审计，不用旧 verdict 资格化新 diff。

## Outcome handling within the existing upload owner

On `7a612300`, Android fast job `101499709171` compiled production and JVM tests and passed the unit-test task; its remaining failure was Detekt reporting `PendingUploadSession.drain` complexity 15 against the configured maximum 14. The original error, capacity pause, receipt/failure accounting and cursor advancement block is extracted verbatim into `recordResult` in the same owner. Only its capacity-pause return becomes `false`, consumed by the same immediate return in `drain`; all other outcomes return `true` after the original byte release and cursor increment. Acceptance, binding checks before/after the request, cancellation cleanup, Retry, append and the UI state callbacks retain their order. Existing JVM and actual screen Connected consumers remain the direct verification producers; no alternative sender, state owner, fallback or suppression is added. This is an extraction, with no command, persistence or recovery-protocol change. Exact cloud verification is required for the resulting candidate.

Actual diagnostic artifact `9990970328` contains 2,099 JVM cases with zero failures, errors or skips. The direct UploadBinding, ShareHandoff, ShareUpload, UploadContinuation and UploadFailure suites account for 24 passing cases. The extracted result block preserves every expression and its order after indentation normalization and the explicit pause-return conversion; the final candidate still needs its own full gate.
