# 多图上传的中断续传

- Goal：完成总 Goal 已接受的 Capture 缺口。A/B/C 分享批次在 B 因容量受阻后，原 Retry 应继续 B、C；A 不重发，所有发送仍属于原账本与权限上下文。
- Allowed Changes：既有 Pending 上传意图 owner、URI 准备的薄边界、真实 Route/Retry 接线及直接测试。复用现有 repository/receipt/enrichment，不新增上传框架或 outbox。
- Forbidden Surface：不改服务端容量与附件归属规则、不删原图/已接受附件，不更改 Windows 生命周期。不把内存 URI 字符串声称为持久读权限，不宣称进程重启恢复已成立。
- Done Checks：A/B/B/C 实际调用序列；B 复用已准备字节，C 最终产生 receipt；再次容量拒绝保留尾部；尾部不可读有准确累计失败且继续剩余项；切账本、降权、旧代次回调、取消、页面重入不会重复或跨账本发送。真实 Pending Retry 接线可执行，原 picker/shortcut/share 消费语义成立，被替代批次循环与单图恢复责任退役。
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
