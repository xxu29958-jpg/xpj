package com.ticketbox

import android.content.Context
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.repository.AcknowledgeItemsMismatchDispatcher
import com.ticketbox.data.repository.ApiServiceProvider
import com.ticketbox.data.repository.ConfirmExpenseDispatcher
import com.ticketbox.data.repository.CreateExpenseDispatcher
import com.ticketbox.data.repository.DeleteCategoryRuleDispatcher
import com.ticketbox.data.repository.DeleteMerchantAliasDispatcher
import com.ticketbox.data.repository.MarkNotDuplicateDispatcher
import com.ticketbox.data.repository.OutboxBinding
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.OutboxMutationDispatcher
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.OutboxScheduler
import com.ticketbox.data.repository.PatchExpenseDispatcher
import com.ticketbox.data.repository.RecognizeTextDispatcher
import com.ticketbox.data.repository.RejectExpenseDispatcher
import com.ticketbox.data.repository.ReplaceItemsDispatcher
import com.ticketbox.data.repository.ReplaceSplitsDispatcher
import com.ticketbox.data.repository.RetryOcrDispatcher
import com.ticketbox.data.repository.UpdateCategoryRuleDispatcher
import com.ticketbox.data.repository.UpdateGoalDispatcher
import com.ticketbox.data.repository.UpdateIncomePlanDispatcher
import com.ticketbox.data.repository.UpdateMerchantAliasDispatcher
import com.ticketbox.data.repository.toEntity
import com.ticketbox.security.SecureTokenStore
import kotlinx.coroutines.flow.map

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient(appContext)
    private val apiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore)
    private val outboxAdapters = OutboxAdapterGraph()

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
        // never fires until a cold launch calls
        // TicketboxApplication.scheduleStartupWorkersAfterLaunchSettles
        // again — meaning every mutation queued under the
        // new session would have to wait for an explicit
        // enqueueOnce trigger (or the next app launch) to drain.
        // Re-arm right here so the periodic tick survives the
        // session boundary.
        onClearAll = {
            outboxScheduler.cancel(appContext)
            outboxScheduler.ensurePeriodic(appContext)
        },
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
    private val outboxDispatchers: List<OutboxMutationDispatcher> by lazy {
        listOf(
            PatchExpenseDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.patchExpenseAdapter,
            ),
            // issue #65 slice 4: POST /api/expenses/manual via outbox (offline manual
            // create). On success, write the server-assigned id/public_id/row_version
            // back onto the optimistic local row (resolved by clientRef) so its domain
            // id flips from the negative local stand-in to the real server id.
            CreateExpenseDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.manualCreateAdapter,
                applyServerIdentity = { ledgerId, clientRef, created ->
                    database.expenseDao().applyLocalCreateServerIdentity(
                        ledgerId,
                        created.toEntity(ledgerId).copy(clientRef = clientRef),
                    )
                },
            ),
            // PR-2g.4: PATCH /api/rules/categories/{id} via outbox.
            UpdateCategoryRuleDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.categoryRuleUpdateAdapter,
            ),
            // PR-2g.5: DELETE /api/rules/categories/{id} via outbox.
            DeleteCategoryRuleDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.categoryRuleDeleteAdapter,
            ),
            // PR-2g.5: DELETE /api/merchants/aliases/{publicId} via outbox.
            DeleteMerchantAliasDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.merchantAliasDeleteAdapter,
            ),
            // PR-2g.6: PATCH /api/merchants/aliases/{publicId} via outbox.
            UpdateMerchantAliasDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.merchantAliasUpdateAdapter,
            ),
            // PR-2g.7: POST /api/expenses/{id}/confirm via outbox.
            ConfirmExpenseDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.expenseStateTokenAdapter,
            ),
            // PR-2g.7: POST /api/expenses/{id}/reject via outbox.
            RejectExpenseDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.expenseStateTokenAdapter,
                deleteConfirmedCache = database.expenseDao()::deleteConfirmedByServerIds,
            ),
            // PR-2g.8: POST /api/expenses/{id}/mark-not-duplicate via outbox.
            MarkNotDuplicateDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.expenseStateTokenAdapter,
            ),
            // PR-2g.8: POST /api/expenses/{id}/ocr/retry via outbox.
            RetryOcrDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.expenseStateTokenAdapter,
            ),
            // PR-2g.9: POST /api/expenses/{id}/items/acknowledge-mismatch via outbox.
            AcknowledgeItemsMismatchDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.expenseStateTokenAdapter,
            ),
            // PR-D: PUT /api/expenses/{id}/items via outbox (offline items editor).
            ReplaceItemsDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.replaceItemsAdapter,
            ),
            // ADR-0042 Slice E-1: PUT /api/expenses/{id}/splits via outbox
            // (offline splits editor).
            ReplaceSplitsDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.replaceSplitsAdapter,
            ),
            // ADR-0042 Slice E-2: POST /api/expenses/{id}/recognize-text via outbox
            // (offline "粘贴文字识别").
            RecognizeTextDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.recognizeTextAdapter,
            ),
            // ADR-0042 Slice F: PATCH /api/goals/{publicId} via outbox.
            UpdateGoalDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.goalUpdateAdapter,
            ),
            // ADR-0042 Slice F: PATCH /api/income-plans/{publicId} via outbox.
            UpdateIncomePlanDispatcher(
                apiProvider = { apiServiceProvider.current() },
                payloadAdapter = outboxAdapters.incomePlanUpdateAdapter,
            ),
        )
    }

    val outboxDrainEngine: OutboxDrainEngine by lazy {
        OutboxDrainEngine(
            outbox = outboxRepository,
            dispatchers = outboxDispatchers,
        )
    }

    private val repositories = RepositoryGraph(
        RepositoryGraphDependencies(
            database = database,
            apiClient = apiClient,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            apiServiceProvider = apiServiceProvider,
            outbox = RepositoryGraphOutbox(
                repository = outboxRepository,
                adapters = outboxAdapters,
            ),
        ),
    )

    val expenseRepository = repositories.expenseRepository
    val ledgerRepository = repositories.ledgerRepository
    val recurringRepository = repositories.recurringRepository
    val budgetRepository = repositories.budgetRepository

    private val notificationRuntimes = NotificationRuntimeGraph(
        NotificationRuntimeDependencies(
            appContext = appContext,
            settingsStore = settingsStore,
            tokenStore = tokenStore,
            apiServiceProvider = apiServiceProvider,
            recurringRepository = recurringRepository,
            budgetRepository = budgetRepository,
        ),
    )

    val notifier = notificationRuntimes.notifier
    val recurringReminderScheduler = notificationRuntimes.recurringReminderScheduler
    val recurringReminderEngine = notificationRuntimes.recurringReminderEngine
    val budgetOverspendChecker = notificationRuntimes.budgetOverspendChecker
    val backupStaleScheduler = notificationRuntimes.backupStaleScheduler
    val backupStaleEngine = notificationRuntimes.backupStaleEngine

    val incomePlanRepository = repositories.incomePlanRepository
    val debtRepository = repositories.debtRepository
    val repaymentDraftRepository = repositories.repaymentDraftRepository
    val reportsRepository = repositories.reportsRepository
    val ruleRepository = repositories.ruleRepository
    val merchantRepository = repositories.merchantRepository
    val tagRepository = repositories.tagRepository
    val categoryPreferenceRepository = repositories.categoryPreferenceRepository

    init {
        // 触发接缝注入（var 而非构造参数：facade 构造已 12 参，加参会让 detekt
        // LongParameterList baseline 按签名失配，详见 ExpenseRepositoryCore.onConfirmedCommitted）。
        // checkAfterConfirmedWrite 自身 fire-and-forget，不阻塞确认链路。
        expenseRepository.onConfirmedCommitted = { ledgerId ->
            budgetOverspendChecker.checkAfterConfirmedWrite(ledgerId)
        }
    }
}
