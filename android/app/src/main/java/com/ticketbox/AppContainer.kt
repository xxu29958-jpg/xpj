package com.ticketbox

import android.content.Context
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.LocalSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
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
import com.ticketbox.data.repository.PatchExpenseDispatcher
import com.ticketbox.data.repository.RecurringRepository
import com.ticketbox.data.repository.ReportsRepository
import com.ticketbox.data.repository.DeleteCategoryRuleDispatcher
import com.ticketbox.data.repository.DeleteMerchantAliasDispatcher
import com.ticketbox.data.repository.RuleRepository
import com.ticketbox.data.repository.UpdateCategoryRuleDispatcher
import com.ticketbox.security.SecureTokenStore
import kotlinx.coroutines.flow.map

class AppContainer(context: Context) {
    private val appContext = context.applicationContext
    val settingsStore = LocalSettingsStore(appContext)
    val tokenStore = SecureTokenStore(appContext)
    private val database = AppDatabase.getDatabase(appContext)
    private val apiClient = ApiClient(appContext)
    private val apiServiceProvider = ApiServiceProvider(apiClient, settingsStore, tokenStore)
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
    // dispatcher rebuilds the token from row.expectedUpdatedAt on
    // replay (single source of truth — round-8 P3#5).
    private val categoryRuleDeleteAdapter = outboxMoshi.adapter(CategoryRuleDeleteRequest::class.java)
    private val merchantAliasDeleteAdapter = outboxMoshi.adapter(MerchantAliasDeleteRequest::class.java)

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
     * (2 DELETE shapes, shared [DeleteOutcome] sealed). The
     * remaining 12 ``PendingMutationType``s land one-per-batch in
     * PR-2g.6+ follow-ups grouped by mutation shape; each
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
        outbox = outboxRepository,
        patchExpenseAdapter = patchExpenseAdapter,
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
    )

    val reportsRepository = ReportsRepository(
        apiClient = apiClient,
        settingsStore = settingsStore,
        tokenStore = tokenStore,
        apiProvider = apiServiceProvider,
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
        // PR-2g.5: outbox + delete adapter for
        // deleteMerchantAliasAllowingOffline.
        outbox = outboxRepository,
        merchantAliasDeleteAdapter = merchantAliasDeleteAdapter,
    )
}
