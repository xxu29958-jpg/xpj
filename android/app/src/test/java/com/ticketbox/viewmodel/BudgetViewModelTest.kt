package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.LedgerAccessState
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetAdvice
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.BudgetCategoryBudget
import com.ticketbox.domain.model.BudgetMonthly
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.BudgetSuggestion
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
private fun budgetTest(block: suspend TestScope.() -> Unit) = runTest {
    val dispatcher = StandardTestDispatcher(testScheduler)
    Dispatchers.setMain(dispatcher)
    try {
        block()
    } finally {
        Dispatchers.resetMain()
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class BudgetViewModelTest {

    @Test
    fun initialLoadPopulatesBudgetAndForm() = budgetTest {
        val fake = FakeBudgetActions(
            budget = budget(
                totalAmountCents = 500000,
                rolloverAmountCents = -20000,
                categoryBudgets = listOf(categoryBudget("餐饮", 120000)),
            ),
        )

        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.loading)
        assertEquals("2026-05", state.month)
        assertEquals(500000L, state.budget?.totalAmountCents)
        assertEquals("5000", state.form.totalAmount)
        assertEquals("-200", state.form.rolloverAmount)
        assertEquals("餐饮", state.form.categoryRows.single().category)
        assertEquals(1, fake.loadCalls)

        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals(BudgetAdviceLoadState.Idle, adviceViewModel.uiState.value.loadState)
        assertEquals(0, fake.adviceMonths.size)

        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Ready, adviceViewModel.uiState.value.loadState)
        assertEquals(listOf("2026-05"), fake.adviceMonths)
        assertEquals("餐饮", adviceViewModel.uiState.value.result?.advice?.suggestions?.single()?.category)

        fake.adviceResponder = {
            Result.success(
                BudgetAdviceResult(
                    advice = null,
                    providerName = "empty",
                    reasonCode = "ai_advisor_provider_empty",
                ),
            )
        }
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Unavailable, adviceViewModel.uiState.value.loadState)
        assertEquals(
            UiText.res(R.string.budget_advice_unavailable_body),
            adviceViewModel.uiState.value.error,
        )
        assertNull(adviceViewModel.uiState.value.result?.advice)
    }

    @Test
    fun saveBuildsUpdateAndReloadsReturnedBudget() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(configured = false))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount(" 3000 ")
        vm.updateRolloverAmount("-100")
        vm.updateNonMonthlyAmount("200")
        vm.updateExcludedCategories(" 医疗，报销 ")
        vm.updateCategoryRow(0, " 吃饭 ", "1200")
        vm.save()
        advanceUntilIdle()

        val request = fake.savedRequests.single()
        assertEquals("2026-05", fake.savedMonths.single())
        assertEquals(300000L, request.totalAmountCents)
        assertEquals(-10000L, request.rolloverAmountCents)
        assertEquals(20000L, request.nonMonthlyAmountCents)
        assertEquals(listOf("医疗", "报销"), request.excludedCategories)
        assertEquals("吃饭", request.categoryBudgets.single().category)
        assertEquals(120000L, request.categoryBudgets.single().amountCents)
        assertEquals(UiText.res(R.string.budget_message_saved), vm.uiState.value.message)
        assertEquals(MessageTone.Success, vm.uiState.value.messageTone)
    }

    @Test
    fun saveRejectsInvalidAmountsBeforeRepositoryCall() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(configured = false))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount("3000")
        vm.updateNonMonthlyAmount("-1")
        vm.save()
        advanceUntilIdle()

        assertEquals(0, fake.savedRequests.size)
        assertEquals(UiText.res(R.string.budget_validation_nonmonthly_negative), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }

    @Test
    fun viewerSaveShortCircuitsWithoutRepositoryCall() = budgetTest {
        val fake = FakeBudgetActions(
            budget = budget(configured = true),
            canModify = false,
        )
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.updateTotalAmount("3000")
        vm.save()
        advanceUntilIdle()

        assertEquals(0, fake.savedRequests.size)
        assertEquals(UiText.res(R.string.common_readonly_ledger), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertFalse(vm.uiState.value.canModify)

        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Idle, adviceViewModel.uiState.value.loadState)
        assertFalse(adviceViewModel.uiState.value.canRequest)
        assertEquals(UiText.res(R.string.common_readonly_ledger), adviceViewModel.uiState.value.error)
        assertEquals(0, fake.adviceMonths.size)
    }

    @Test
    fun loadFailureSetsRetryableErrorNotLoadingPlaceholder() = budgetTest {
        // 审计 8.4: a failed load must surface a distinct, retryable error (not the
        // permanent "正在读取预算。" loading copy). The error rides loadError, not the
        // message channel that carries save-flow feedback. A code-less, message-less
        // failure resolves to the screen fallback string (toUiText).
        val fake = FakeBudgetActions(budget = budget())
        fake.monthlyBudgetResponder = { Result.failure(RuntimeException()) }
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.loading)
        assertNull(state.budget)
        assertNull(state.message)
        assertEquals(UiText.res(R.string.budget_message_load_failed), state.loadError)

        fake.adviceResponder = { Result.failure(RuntimeException()) }
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Failed, adviceViewModel.uiState.value.loadState)
        assertEquals(UiText.res(R.string.budget_advice_load_failed), adviceViewModel.uiState.value.error)
    }

    @Test
    fun retryAfterLoadFailureClearsErrorAndPopulatesBudget() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 700000))
        fake.monthlyBudgetResponder = { Result.failure(RuntimeException()) }
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals(UiText.res(R.string.budget_message_load_failed), vm.uiState.value.loadError)

        // Retry routes through the same refresh() the UI's onRetry calls; this time it succeeds.
        fake.monthlyBudgetResponder = null
        vm.refresh()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertNull(state.loadError)
        assertEquals(700000L, state.budget?.totalAmountCents)
    }

    @Test
    fun refreshFailureAfterLoadedBudgetKeepsDataAndShowsRefreshError() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(totalAmountCents = 500000))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        fake.monthlyBudgetResponder = { Result.failure(RuntimeException()) }
        vm.refresh()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.loading)
        assertNull(state.message)
        assertEquals(500000L, state.budget?.totalAmountCents)
        assertEquals("5000", state.form.totalAmount)
        assertEquals(UiText.res(R.string.budget_message_refresh_failed_with_data), state.loadError)

        vm.save()
        advanceUntilIdle()

        assertNull(vm.uiState.value.loadError)
    }

    @Test
    fun monthChangeLoadsRequestedMonth() = budgetTest {
        val fake = FakeBudgetActions(budget = budget(month = "2026-05"))
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        fake.budget = budget(month = "2026-04")
        vm.previousMonth()
        advanceUntilIdle()

        assertEquals(listOf("2026-05", "2026-04"), fake.loadedMonths)
        assertEquals("2026-04", vm.uiState.value.month)
        assertNull(vm.uiState.value.message)
        assertEquals(MessageTone.Neutral, vm.uiState.value.messageTone)
    }

    @Test
    fun staleMonthResponseDoesNotOverwriteCurrentBudgetForm() = budgetTest {
        val mayResponse = CompletableDeferred<Result<BudgetMonthly>>()
        val aprilResponse = CompletableDeferred<Result<BudgetMonthly>>()
        val fake = FakeBudgetActions(budget = budget(month = "2026-05"))
        fake.monthlyBudgetResponder = { month ->
            if (month == "2026-05") mayResponse.await() else aprilResponse.await()
        }
        val vm = BudgetViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        vm.previousMonth()
        advanceUntilIdle()

        mayResponse.complete(Result.success(budget(month = "2026-05", totalAmountCents = 999000)))
        advanceUntilIdle()

        assertEquals("2026-04", vm.uiState.value.month)
        assertNull(vm.uiState.value.budget)

        aprilResponse.complete(Result.success(budget(month = "2026-04", totalAmountCents = 111000)))
        advanceUntilIdle()

        assertEquals("2026-04", vm.uiState.value.month)
        assertEquals(111000L, vm.uiState.value.budget?.totalAmountCents)
        assertEquals("1110", vm.uiState.value.form.totalAmount)
    }
}

/** 218-B4 review P2: terminal budget-advisor state mapping (provider-disabled
 *  reason codes and live-advisor 403 gates) vs. the retryable Empty/Failed
 *  states. Kept in a dedicated class to stay under the per-class function cap. */
@OptIn(ExperimentalCoroutinesApi::class)
class BudgetAdviceViewModelTest {
    @Test
    fun nullAdviceWithoutProviderReasonKeepsRetryableEmptyState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        // Backend emits reason_code = null or "ai_advisor_no_advice" when a live
        // provider simply produced nothing — the add-data Empty guidance with its
        // 重新生成 CTA stays the right state there.
        fake.adviceResponder = {
            Result.success(
                BudgetAdviceResult(advice = null, providerName = "mock", reasonCode = null),
            )
        }
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Empty, adviceViewModel.uiState.value.loadState)
        assertNull(adviceViewModel.uiState.value.error)

        fake.adviceResponder = {
            Result.success(
                BudgetAdviceResult(
                    advice = null,
                    providerName = "mock",
                    reasonCode = "ai_advisor_no_advice",
                ),
            )
        }
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Empty, adviceViewModel.uiState.value.loadState)
        assertNull(adviceViewModel.uiState.value.error)
    }

    @Test
    fun transientProviderCallFailureKeepsRetryableFailedState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        // Live openai_compat failures return HTTP 200 with advice == null and
        // last_error_code as the reason (_providers.py:161-180) — they are
        // transient, so the retryable Failed state (with 重试) must survive;
        // only ai_advisor_provider_empty and ai_advisor_payload_invalid are
        // terminal (the latter pinned in BudgetAdvicePayloadInvalidTest).
        val retryableReasons = listOf(
            "ai_advisor_provider_call_failed",
            "ai_advisor_provider_unexpected_error",
            "ai_advisor_response_parse_failed",
            "ai_advisor_response_unexpected_error",
        )
        for (reason in retryableReasons) {
            fake.adviceResponder = {
                Result.success(
                    BudgetAdviceResult(advice = null, providerName = "live", reasonCode = reason),
                )
            }
            adviceViewModel.requestAdvice()
            advanceUntilIdle()

            assertEquals(BudgetAdviceLoadState.Failed, adviceViewModel.uiState.value.loadState)
            assertEquals(
                UiText.res(R.string.budget_advice_load_failed),
                adviceViewModel.uiState.value.error,
            )
        }
    }

    @Test
    fun ownerRequiredErrorMapsToTerminalUnavailableState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        fake.adviceResponder = {
            Result.failure(
                RepositoryException(
                    message = "只有账本拥有者可以调用外部 AI 预算建议。",
                    errorCode = "ai_advisor_owner_required",
                ),
            )
        }
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        val state = adviceViewModel.uiState.value
        // Terminal (no retry affordance): the server code has no R.string arm, so
        // the backend's registered copy rides through as Raw via toUiText.
        assertEquals(BudgetAdviceLoadState.Unavailable, state.loadState)
        assertEquals(UiText.raw("只有账本拥有者可以调用外部 AI 预算建议。"), state.error)
    }

    @Test
    fun advisorNotConfirmedErrorMapsToTerminalUnavailableState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        fake.adviceResponder = {
            Result.failure(
                RepositoryException(
                    message = "AI 预算助手尚未经过拥有者显式确认，已禁用。",
                    errorCode = "ai_advisor_not_confirmed",
                ),
            )
        }
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Unavailable, state.loadState)
        assertEquals(UiText.raw("AI 预算助手尚未经过拥有者显式确认，已禁用。"), state.error)
    }

    @Test
    fun dailyLimitExceededMapsToTerminalUnavailableState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        fake.adviceResponder = {
            Result.failure(
                RepositoryException(
                    message = "AI 预算助手今日调用次数已达上限。",
                    errorCode = "ai_advisor_daily_limit_exceeded",
                ),
            )
        }
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        // 24h-window quota cap (_audit.py:131-138): retrying today can never
        // succeed, so this is terminal (no retry affordance in the state model).
        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Unavailable, state.loadState)
        assertEquals(UiText.raw("AI 预算助手今日调用次数已达上限。"), state.error)
    }

    @Test
    fun rateLimitedStaysRetryableFailedState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        fake.adviceResponder = {
            Result.failure(
                RepositoryException(
                    message = "AI 预算助手调用过于频繁，请稍后再试。",
                    errorCode = "ai_advisor_rate_limited",
                ),
            )
        }
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        // Short-window 429 (errors.py:147): a later retry IS meaningful, so the
        // retryable Failed state (with 重试) must survive. The full code has no
        // R.string arm, so the server copy passes through as Raw.
        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Failed, state.loadState)
        assertEquals(UiText.raw("AI 预算助手调用过于频繁，请稍后再试。"), state.error)
    }

    @Test
    fun initRestoresCachedAdviceAsReady() = budgetTest {
        val cached = BudgetAdviceResult(
            advice = BudgetAdvice(
                summary = "保持弹性支出空间。",
                suggestions = listOf(
                    BudgetSuggestion(
                        category = "餐饮",
                        suggestedAmountCents = 80_000,
                        rationale = "近期支出稳定。",
                    ),
                ),
                confidence = 0.8,
            ),
            providerName = "mock",
            reasonCode = "advisor_ready",
        )
        val fake = FakeBudgetActions(budget = budget(), cachedAdvice = cached)
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        // A reopen after an already quota-counted call renders the cached result
        // instead of firing a second counted request.
        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Ready, state.loadState)
        assertEquals(cached, state.result)
        assertEquals(0, fake.adviceMonths.size)
    }

    @Test
    fun initWithoutCachedAdviceStaysIdle() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        assertEquals(BudgetAdviceLoadState.Idle, adviceViewModel.uiState.value.loadState)
        assertEquals(0, fake.adviceMonths.size)
    }

    @Test
    fun roleReprojectionOnSameLedgerRegatesWithoutWipingContent() = budgetTest {
        val accessFlow = MutableStateFlow<LedgerAccessState?>(
            LedgerAccessState(ledgerId = "owner", canModify = true),
        )
        val fake = FakeBudgetActions(budget = budget(), accessFlow = accessFlow)
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        adviceViewModel.requestAdvice()
        advanceUntilIdle()
        assertEquals(BudgetAdviceLoadState.Ready, adviceViewModel.uiState.value.loadState)

        // Demotion member→viewer on the SAME ledger: re-gate to read-only
        // immediately, but the already-rendered result is not discarded.
        fake.canModify = false
        accessFlow.value = LedgerAccessState(ledgerId = "owner", canModify = false)
        advanceUntilIdle()

        var state = adviceViewModel.uiState.value
        assertFalse(state.canRequest)
        assertEquals(BudgetAdviceLoadState.Ready, state.loadState)
        assertEquals("保持弹性支出空间。", state.result?.advice?.summary)

        // Promotion viewer→member: the gate opens again with content intact.
        fake.canModify = true
        accessFlow.value = LedgerAccessState(ledgerId = "owner", canModify = true)
        advanceUntilIdle()

        state = adviceViewModel.uiState.value
        assertEquals(true, state.canRequest)
        assertEquals(BudgetAdviceLoadState.Ready, state.loadState)
        assertEquals("保持弹性支出空间。", state.result?.advice?.summary)
    }

    @Test
    fun roleDemotionRestoresReadOnlyShortCircuit() = budgetTest {
        val accessFlow = MutableStateFlow<LedgerAccessState?>(
            LedgerAccessState(ledgerId = "owner", canModify = true),
        )
        val fake = FakeBudgetActions(budget = budget(), accessFlow = accessFlow)
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()

        fake.canModify = false
        accessFlow.value = LedgerAccessState(ledgerId = "owner", canModify = false)
        advanceUntilIdle()
        assertFalse(adviceViewModel.uiState.value.canRequest)

        // The viewer short-circuit is live again: no repository call is made.
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Idle, state.loadState)
        assertEquals(UiText.res(R.string.common_readonly_ledger), state.error)
        assertEquals(0, fake.adviceMonths.size)
    }

    @Test
    fun ledgerChangeResetsThenRestoresFromBindingScopedCache() = budgetTest {
        val cached = BudgetAdviceResult(
            advice = BudgetAdvice(
                summary = "保持弹性支出空间。",
                suggestions = emptyList(),
                confidence = 0.8,
            ),
            providerName = "mock",
            reasonCode = "advisor_ready",
        )
        val accessFlow = MutableStateFlow<LedgerAccessState?>(
            LedgerAccessState(ledgerId = "owner", canModify = true),
        )
        val fake = FakeBudgetActions(budget = budget(), cachedAdvice = cached, accessFlow = accessFlow)
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        advanceUntilIdle()
        assertEquals(BudgetAdviceLoadState.Ready, adviceViewModel.uiState.value.loadState)

        // Ledger switch keeps the round-4 semantics: reset to Idle, then the
        // binding-scoped cache restore runs for the new ledger.
        accessFlow.value = LedgerAccessState(ledgerId = "ledger-b", canModify = true)
        advanceUntilIdle()

        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Ready, state.loadState)
        assertEquals(cached, state.result)
        assertEquals(listOf("2026-05", "2026-05"), fake.cachedAdviceMonths)
        assertEquals(0, fake.adviceMonths.size)
    }
}

/** 218-B4 review P2: ai_advisor_payload_invalid is the deterministic
 *  fail-closed outbound guard (rejects before the provider call), so it maps
 *  to the terminal Unavailable state with its own honest copy — separate
 *  class to stay under the per-class function cap. */
@OptIn(ExperimentalCoroutinesApi::class)
class BudgetAdvicePayloadInvalidTest {
    @Test
    fun payloadInvalidMapsToTerminalUnavailableState() = budgetTest {
        val fake = FakeBudgetActions(budget = budget())
        fake.adviceResponder = {
            Result.success(
                BudgetAdviceResult(
                    advice = null,
                    providerName = "live",
                    reasonCode = "ai_advisor_payload_invalid",
                ),
            )
        }
        val adviceViewModel = BudgetAdviceViewModel(fake, initialMonth = "2026-05")
        adviceViewModel.requestAdvice()
        advanceUntilIdle()

        val state = adviceViewModel.uiState.value
        assertEquals(BudgetAdviceLoadState.Unavailable, state.loadState)
        assertEquals(UiText.res(R.string.budget_advice_payload_invalid_body), state.error)
    }
}

private class FakeBudgetActions(
    var budget: BudgetMonthly,
    canModify: Boolean = true,
    private val activeLedgerFlow: Flow<String?> = emptyFlow(),
    private val cachedAdvice: BudgetAdviceResult? = null,
    private val accessFlow: Flow<LedgerAccessState?> = emptyFlow(),
) : BudgetActions {
    val loadedMonths = mutableListOf<String>()
    val savedMonths = mutableListOf<String>()
    val savedRequests = mutableListOf<BudgetMonthlyUpdate>()
    val adviceMonths = mutableListOf<String>()
    val cachedAdviceMonths = mutableListOf<String>()
    val loadCalls: Int get() = loadedMonths.size
    var canModify: Boolean = canModify
    var monthlyBudgetResponder: (suspend (String) -> Result<BudgetMonthly>)? = null
    var adviceResponder: (suspend (String) -> Result<BudgetAdviceResult>)? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun cachedBudgetAdvice(month: String): BudgetAdviceResult? {
        cachedAdviceMonths += month
        return cachedAdvice
    }

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override fun observeLedgerAccessState(): Flow<LedgerAccessState?> = accessFlow

    override suspend fun monthlyBudget(month: String): Result<BudgetMonthly> {
        loadedMonths += month
        monthlyBudgetResponder?.let { return it(month) }
        return Result.success(budget.copy(month = month))
    }

    override suspend fun requestBudgetAdvice(month: String): Result<BudgetAdviceResult> {
        adviceMonths += month
        adviceResponder?.let { return it(month) }
        return Result.success(
            BudgetAdviceResult(
                advice = BudgetAdvice(
                    summary = "保持弹性支出空间。",
                    suggestions = listOf(
                        BudgetSuggestion(
                            category = "餐饮",
                            suggestedAmountCents = 80_000,
                            rationale = "近期支出稳定。",
                        ),
                    ),
                    confidence = 0.8,
                ),
                providerName = "mock",
                reasonCode = "advisor_ready",
            ),
        )
    }

    override suspend fun saveMonthlyBudget(
        month: String,
        update: BudgetMonthlyUpdate,
    ): Result<BudgetMonthly> {
        savedMonths += month
        savedRequests += update
        budget = budget.copy(
            month = month,
            configured = true,
            totalAmountCents = update.totalAmountCents,
            rolloverAmountCents = update.rolloverAmountCents,
            nonMonthlyAmountCents = update.nonMonthlyAmountCents,
        )
        return Result.success(budget)
    }
}

private fun budget(
    month: String = "2026-05",
    configured: Boolean = true,
    totalAmountCents: Long = 300000,
    rolloverAmountCents: Long = 0,
    categoryBudgets: List<BudgetCategoryBudget> = emptyList(),
): BudgetMonthly = BudgetMonthly(
    ledgerId = "owner",
    month = month,
    configured = configured,
    totalAmountCents = totalAmountCents,
    rolloverAmountCents = rolloverAmountCents,
    fixedAmountCents = 50000,
    nonMonthlyAmountCents = 10000,
    flexBudgetCents = 240000,
    spentAmountCents = 120000,
    excludedAmountCents = 0,
    remainingAmountCents = totalAmountCents + rolloverAmountCents - 120000,
    overspentAmountCents = 0,
    excludedCategories = emptyList(),
    excludedBreakdown = emptyList(),
    categoryBudgets = categoryBudgets,
    updatedAt = "2026-05-13T00:00:00Z",
)

private fun categoryBudget(category: String, amountCents: Long): BudgetCategoryBudget = BudgetCategoryBudget(
    category = category,
    amountCents = amountCents,
    spentAmountCents = 30000,
    remainingAmountCents = amountCents - 30000,
    overspentAmountCents = 0,
)
