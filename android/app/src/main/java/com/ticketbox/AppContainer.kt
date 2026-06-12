package com.ticketbox

import android.content.Context
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.BudgetRepository
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.data.repository.LocalLedgerSessionCoordinator
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.OutboxBinding
import com.ticketbox.data.repository.OutboxMutationDispatcher
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.OutboxScheduler
import com.ticketbox.data.repository.AcknowledgeItemsMismatchDispatcher
import com.ticketbox.data.repository.ConfirmExpenseDispatcher
import com.ticketbox.data.repository.PatchExpenseDispatcher
import com.ticketbox.data.repository.RecognizeTextDispatcher
import com.ticketbox.data.repository.ReplaceItemsDispatcher
import com.ticketbox.data.repository.ReplaceSplitsDispatcher
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsRepository
import com.ticketbox.data.repository.DeleteCategoryRuleDispatcher
import com.ticketbox.data.repository.DeleteMerchantAliasDispatcher
import com.ticketbox.data.repository.MarkNotDuplicateDispatcher
import com.ticketbox.data.repository.RejectExpenseDispatcher
import com.ticketbox.data.repository.RetryOcrDispatcher
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.data.repository.TagRepository
import com.ticketbox.data.repository.UpdateCategoryRuleDispatcher
import com.ticketbox.data.repository.UpdateGoalDispatcher
import com.ticketbox.data.repository.UpdateIncomePlanDispatcher
import com.ticketbox.data.repository.UpdateMerchantAliasDispatcher
import com.ticketbox.notification.TicketboxNotifier
import com.ticketbox.notification.recurring.NotifierRecurringReminderDispatcher
import com.ticketbox.notification.recurring.RecurringReminderEngine
import com.ticketbox.notification.recurring.RecurringReminderPolicy
import com.ticketbox.notification.recurring.RecurringReminderRuntime
import com.ticketbox.notification.recurring.RepositoryRecurringReminderSource
import com.ticketbox.notification.recurring.SharedPrefsRecurringReminderStore
import com.ticketbox.notification.recurring.WorkManagerRecurringReminderScheduler
import com.ticketbox.security.SecureTokenStore
import java.time.LocalDate
import kotlinx.coroutines.flow.map

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient(appContext)
    private val apiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore)

    // 通知闭环 PR-1：草稿创建成功后的系统通知出口（NLS 与 App 同进程，进程内直发）。
    // 开关状态在发出时从 settingsStore 现读，channel 在 publish 前惰性创建。
    val notifier = TicketboxNotifier(appContext, settingsStore)
    // ADR-0038 PR-2g.2 + 2g.3: outbox plumbing.
    //
    // A dedicated Moshi instance for the outbox dispatcher layer.
    // We don't share the one ApiClient builds internally because it
    // lives in private scope; using a separate instance is fine
    // since Moshi adapters are immutable and stateless. The outbox
    // payloads we serialise here MUST line up with the Retrofit DTOs
    // (same nullability + @Json names) since the dispatcher
    // deserialises a row back into the same DTO shape on replay.
    private val outboxMoshi: Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    // PR-2g.3: the SAME adapter is shared between the call-site
    // serialiser (ExpenseRepository routes IOException → outbox.enqueue)
    // and the dispatcher (PatchExpenseDispatcher deserialises on
    // replay). Sharing guarantees toJson/fromJson roundtrip — if we
    // built two independent adapters they'd be byte-compatible
    // today but could drift if Moshi options change in one place.
    private val patchExpenseAdapter = outboxMoshi.adapter(ExpenseUpdateRequest::class.java)

    // PR-2g.4: shared between [UpdateCategoryRuleDispatcher]
    // (deserialises on replay) and [RuleRepository.
    // updateCategoryRuleAllowingOffline] (serialises before
    // enqueue). Same roundtrip guarantee as patchExpenseAdapter.
    private val categoryRuleUpdateAdapter = outboxMoshi.adapter(CategoryRuleUpdateRequest::class.java)

    // PR-2g.5: DELETE adapters. Token-only payload shape; the
    // dispatcher rebuilds the token from row.expectedRowVersion on
    // replay (single source of truth — round-8 P3#5).
    private val categoryRuleDeleteAdapter = outboxMoshi.adapter(CategoryRuleDeleteRequest::class.java)
    private val merchantAliasDeleteAdapter = outboxMoshi.adapter(MerchantAliasDeleteRequest::class.java)

    // PR-2g.6: PATCH merchant alias adapter. Shared between
    // UpdateMerchantAliasDispatcher and
    // MerchantRepository.updateMerchantAliasAllowingOffline.
    private val merchantAliasUpdateAdapter = outboxMoshi.adapter(MerchantAliasUpdateRequest::class.java)

    // PR-2g.7: token-only adapter shared between the confirm / reject
    // dispatchers and ExpensePendingRepository's offline call sites.
    // POST /api/expenses/{id}/confirm and .../reject take the same
    // ExpenseStateTokenRequest body, so one adapter serves both.
    private val expenseStateTokenAdapter = outboxMoshi.adapter(ExpenseStateTokenRequest::class.java)

    // PR-D: body-carrying adapter shared between ReplaceItemsDispatcher and
    // ExpenseDetailRepository's offline items-editor call site (PUT
    // /api/expenses/{id}/items). Same roundtrip guarantee as patchExpenseAdapter.
    private val replaceItemsAdapter = outboxMoshi.adapter(ExpenseItemReplaceRequestDto::class.java)

    // ADR-0042 Slice E-1: body-carrying adapter shared between
    // ReplaceSplitsDispatcher and ExpenseDetailRepository's offline
    // splits-editor call site (PUT /api/expenses/{id}/splits). Same roundtrip
    // guarantee as replaceItemsAdapter.
    private val replaceSplitsAdapter = outboxMoshi.adapter(ExpenseSplitReplaceRequestDto::class.java)

    // ADR-0042 Slice E-2: body-carrying adapter shared between
    // RecognizeTextDispatcher and ExpenseDetailRepository's offline
    // "粘贴文字识别" call site (POST /api/expenses/{id}/recognize-text). Same
    // roundtrip guarantee as replaceItemsAdapter.
    private val recognizeTextAdapter = outboxMoshi.adapter(ExpenseRecognizeTextRequestDto::class.java)

    // ADR-0042 Slice F: PATCH /api/goals/{publicId} adapter. Shared between
    // UpdateGoalDispatcher and ReportsRepository.updateGoalAllowingOffline.
    private val goalUpdateAdapter = outboxMoshi.adapter(GoalUpdateRequestDto::class.java)

    // ADR-0042 Slice F: PATCH /api/income-plans/{publicId} adapter. Shared
    // between UpdateIncomePlanDispatcher and
    // IncomePlanRepository.updateAllowingOffline.
    private val incomePlanUpdateAdapter = outboxMoshi.adapter(IncomePlanUpdateRequestDto::class.java)

    val outboxScheduler = OutboxScheduler()

    val outboxRepository = OutboxRepository(
        dao = database.pendingMutationDao(),
        bindingProvider = {
            OutboxBinding(
                serverUrl = settingsStore.serverUrl().orEmpty(),
                ledgerId = settingsStore.activeLedgerId().orEmpty(),
            )
        },
        // Reactive binding for the live status streams: re-read the binding
        // whenever the active ledger changes so the queue-depth pill / banners
        // follow a ledger switch instead of staying pinned to the first
        // binding observed. (Server rebind without a ledger change is rare and
        // goes through sign-out, which clears the queue anyway.)
        bindingChanges = settingsStore.observeActiveLedgerId().map { ledgerId ->
            OutboxBinding(
                serverUrl = settingsStore.serverUrl().orEmpty(),
                ledgerId = ledgerId.orEmpty(),
            )
        },
        // PR-2g.3: an enqueue immediately fires a one-time drain so
        // the user doesn't wait up to 15 min for the periodic tick.
        // OutboxScheduler.enqueueOnce uses KEEP policy → a burst of
        // 20 enqueues collapses into one drain pass.
        onEnqueued = { outboxScheduler.enqueueOnce(appContext) },
        // Session-boundary pause: cancel any in-flight or scheduled
        // workers so they do not keep draining rows from the old
        // binding after credentials change.
        //
        // PR-2g.3 round-9 P2: cancel ALSO drops the periodic worker.
        // Without immediately re-arming, the next 15-min heartbeat
        // never fires until cold restart calls TicketboxApplication.
        // onCreate again — meaning every mutation queued under the
        // new session would have to wait for an explicit
        // enqueueOnce trigger (or the next app launch) to drain.
        // Re-arm right here so the periodic tick survives the
        // session boundary.
        onClearAll = {
            outboxScheduler.cancel(appContext)
            outboxScheduler.ensurePeriodic(appContext)
        },
    )

    // Session coordinator depends on outbox so it can wipe the queue
    // alongside the local expense cache on a cache-invalidating
    // transition (round-8 P1). Constructed AFTER outboxRepository
    // for this reason.
    private val ledgerSessionCoordinator = LocalLedgerSessionCoordinator(
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
        outbox = outboxRepository,
    )

    /**
     * Registered dispatchers. PR-2g.2 wired the first dispatcher
     * [PatchExpenseDispatcher]; PR-2g.3 routed the matching call
     * site (PATCH expense). PR-2g.4 added
     * [UpdateCategoryRuleDispatcher] + matching call site. PR-2g.5
     * added [DeleteCategoryRuleDispatcher] +
     * [DeleteMerchantAliasDispatcher] + matching call sites
     * (2 DELETE shapes, shared [DeleteOutcome] sealed). PR-2g.6
     * added [UpdateMerchantAliasDispatcher] + matching call site
     * (PATCH merchant alias). PR-2g.7 added [ConfirmExpenseDispatcher]
     * + [RejectExpenseDispatcher] + matching call sites (the
     * standalone single-tap confirm / reject state-machine POSTs;
     * shared [ExpenseStateOutcome] sealed). The remaining
     * ``PendingMutationType``s land one-per-batch in PR-2g.8+
     * follow-ups grouped by mutation shape; each
     * follow-up appends dispatchers here AND routes its matching
     * call sites through [OutboxRepository.enqueue] in the
     * appropriate Repository.
     * [OutboxDrainEngine] marks rows of types with no registered
     * dispatcher FAILED with ``no_dispatcher_registered:<wire>``
     * (codex round-1 P2#5).
     */
    private val outboxDispatchers: List<OutboxMutationDispatcher> = listOf(
        PatchExpenseDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = patchExpenseAdapter,
        ),
        // PR-2g.4: PATCH /api/rules/categories/{id} via outbox.
        UpdateCategoryRuleDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = categoryRuleUpdateAdapter,
        ),
        // PR-2g.5: DELETE /api/rules/categories/{id} via outbox.
        DeleteCategoryRuleDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = categoryRuleDeleteAdapter,
        ),
        // PR-2g.5: DELETE /api/merchants/aliases/{publicId} via outbox.
        DeleteMerchantAliasDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = merchantAliasDeleteAdapter,
        ),
        // PR-2g.6: PATCH /api/merchants/aliases/{publicId} via outbox.
        UpdateMerchantAliasDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = merchantAliasUpdateAdapter,
        ),
        // PR-2g.7: POST /api/expenses/{id}/confirm via outbox.
        ConfirmExpenseDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = expenseStateTokenAdapter,
        ),
        // PR-2g.7: POST /api/expenses/{id}/reject via outbox.
        RejectExpenseDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = expenseStateTokenAdapter,
        ),
        // PR-2g.8: POST /api/expenses/{id}/mark-not-duplicate via outbox.
        MarkNotDuplicateDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = expenseStateTokenAdapter,
        ),
        // PR-2g.8: POST /api/expenses/{id}/ocr/retry via outbox.
        RetryOcrDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = expenseStateTokenAdapter,
        ),
        // PR-2g.9: POST /api/expenses/{id}/items/acknowledge-mismatch via outbox.
        AcknowledgeItemsMismatchDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = expenseStateTokenAdapter,
        ),
        // PR-D: PUT /api/expenses/{id}/items via outbox (offline items editor).
        ReplaceItemsDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = replaceItemsAdapter,
        ),
        // ADR-0042 Slice E-1: PUT /api/expenses/{id}/splits via outbox
        // (offline splits editor).
        ReplaceSplitsDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = replaceSplitsAdapter,
        ),
        // ADR-0042 Slice E-2: POST /api/expenses/{id}/recognize-text via outbox
        // (offline "粘贴文字识别").
        RecognizeTextDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = recognizeTextAdapter,
        ),
        // ADR-0042 Slice F: PATCH /api/goals/{publicId} via outbox.
        UpdateGoalDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = goalUpdateAdapter,
        ),
        // ADR-0042 Slice F: PATCH /api/income-plans/{publicId} via outbox.
        UpdateIncomePlanDispatcher(
            apiProvider = { apiServiceProvider.current() },
            payloadAdapter = incomePlanUpdateAdapter,
        ),
    )

    val outboxDrainEngine = OutboxDrainEngine(
        outbox = outboxRepository,
        dispatchers = outboxDispatchers,
    )

    val expenseRepository = ExpenseRepository(
        expenseDao = database.expenseDao(),
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
        // PR-2g.3: pass the outbox + adapter so the PATCH expense
        // call site can fall back to enqueue on IOException.
        // PR-2g.7: + token adapter for confirm/reject offline routing.
        outbox = outboxRepository,
        patchExpenseAdapter = patchExpenseAdapter,
        expenseStateTokenAdapter = expenseStateTokenAdapter,
        replaceItemsAdapter = replaceItemsAdapter,
        replaceSplitsAdapter = replaceSplitsAdapter,
        recognizeTextAdapter = recognizeTextAdapter,
    )

    val ledgerRepository = LedgerRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        expenseDao = database.expenseDao(),
        apiProvider = apiServiceProvider,
        sessionCoordinator = ledgerSessionCoordinator,
    )

    val recurringRepository = RecurringRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val budgetRepository = BudgetRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    val incomePlanRepository = IncomePlanRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        // ADR-0042 Slice F: outbox + adapter for updateAllowingOffline.
        outbox = outboxRepository,
        incomePlanUpdateAdapter = incomePlanUpdateAdapter,
    )

    val reportsRepository = ReportsRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        // ADR-0042 Slice F: outbox + adapter for updateGoalAllowingOffline.
        outbox = outboxRepository,
        goalUpdateAdapter = goalUpdateAdapter,
    )

    val ruleRepository = RuleRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        onConfirmedChanged = { expenseRepository.syncConfirmed() },
        // PR-2g.4: outbox + adapter for updateCategoryRuleAllowingOffline.
        // PR-2g.5: + deleteAdapter for deleteCategoryRuleAllowingOffline.
        outbox = outboxRepository,
        categoryRuleUpdateAdapter = categoryRuleUpdateAdapter,
        categoryRuleDeleteAdapter = categoryRuleDeleteAdapter,
    )

    val merchantRepository = MerchantRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
        // PR-2g.5: outbox + delete adapter.
        // PR-2g.6: + update adapter for updateMerchantAliasAllowingOffline.
        outbox = outboxRepository,
        merchantAliasDeleteAdapter = merchantAliasDeleteAdapter,
        merchantAliasUpdateAdapter = merchantAliasUpdateAdapter,
    )

    // ADR-0043 slice C — tag management. Online-only (契约 7): no outbox / no
    // idempotency adapters, unlike MerchantRepository.
    val tagRepository = TagRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
    )

    // ADR-0046 Slice 5: 固定支出提醒检测源的 WorkManager 调度器。
    // TicketboxApplication.onCreate 调 ensurePeriodic()（幂等）注册 24h 周期 worker。
    val recurringReminderScheduler = WorkManagerRecurringReminderScheduler()

    // ADR-0046 Slice 4: 提醒编排核心。source 只读 recurringRepository（active items），
    // dispatcher 委托 notifier（Slice 1 返回 outcome），store 本地去重，policy 纯函数判 due/overdue。
    // 全部 IO / 时钟 / 设置依赖在此注入，engine 本身保持可纯 JVM 测试（业务契约落 EngineTest）。
    val recurringReminderEngine = RecurringReminderEngine(
        source = RepositoryRecurringReminderSource(recurringRepository),
        policy = RecurringReminderPolicy(),
        store = SharedPrefsRecurringReminderStore(appContext),
        dispatcher = NotifierRecurringReminderDispatcher(notifier::onRecurringDue),
        runtime = RecurringReminderRuntime(
            // 「固定支出提醒」开关现读：关 → engine 不拉 source、不发、不 markSent（Contract 8）。
            recurringRemindersEnabled = { settingsStore.notificationPreferences().recurringReminders },
            // session 就绪 = 已绑定 token + 有 active ledger + server 地址。任一缺失 → safe success
            // 不提醒（未登录 / 无 active ledger，Contract 8 / Contract 11 仅扫当前 active ledger）。
            sessionReady = {
                !tokenStore.getToken().isNullOrBlank() &&
                    !settingsStore.activeLedgerId().isNullOrBlank() &&
                    !settingsStore.serverUrl().isNullOrBlank()
            },
            // 设备本地当天（与 RecurringRepository 的 API timezone=TimeZone.getDefault() 一致），
            // 用户看到的「今天」即提醒窗口锚点；day-level 比较，可注入便于测试钉边界。
            today = { LocalDate.now() },
        ),
    )
}
