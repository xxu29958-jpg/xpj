# B13 Android 多任务与跨端返回（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：单任务 admitted 返回 PRESERVED；A/B 交错 last-admitted UNVERIFIED 偏弱；跨端不共享草稿
修复：PROPOSED（仅当要保证两笔 admitted 不互相抢最后一条；需产品确认是否必要）
证据等级：源码。未跑双任务/迟到导航。

## 链

1. 会话 map 键：`(seriesPublicId, period)`。切 binding：`RecurringOccurrenceViewModel.init` L82–85 `periodPayment.clear()` 丢掉全部 origin。
2. 最后 admitted：`restoreAdmittedPeriodOccurrence` L144 `sessions.values.lastOrNull { it.admitted }` —— 多笔 admitted 时只恢复 map 迭代的最后一条，不是「当前可见任务」。
3. 迟到 create 回调：`applyCreateOutcome` L112–114 要求 visible.clientRef == submitted.clientRef 才 dismiss/onAdmitted。错任务可见时不把 UI 切到迟到结果。
4. 列表晚到：`restoreVisibleOrigin` 在 `load` 成功后调用 L218。
5. 跨端：Web 草稿 localStorage + 身份 scope；Android SavedStateHandle。两端不共享未提交 intent。其他端改动后靠 `refresh`/`fetch`。

## 判定

单系列单期次返回原月：源码成立。A/B 两笔付款都 admitted 后恢复哪一笔：实现是 lastOrNull，可能不符合「真正返回的任务」。未执行，不称为串任务已发生。
