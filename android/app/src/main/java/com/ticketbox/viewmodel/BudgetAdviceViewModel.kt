package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.YearMonth

enum class BudgetAdviceLoadState {
    Idle,
    Loading,
    Empty,
    Ready,
    Failed,

    /** Terminal state with no retry affordance: retrying cannot succeed until
     *  something outside this screen changes (advisor provider not configured
     *  server-side, or a 403 advisor-permission gate). */
    Unavailable,
}

data class BudgetAdviceUiState(
    val month: String = YearMonth.now().toString(),
    val loadState: BudgetAdviceLoadState = BudgetAdviceLoadState.Idle,
    val canRequest: Boolean = true,
    val result: BudgetAdviceResult? = null,
    val error: UiText? = null,

    /** Backend error code that produced a terminal [BudgetAdviceLoadState.Unavailable]
     *  from a failed request, so a later capability increase (member→owner)
     *  can tell a role-gated terminal apart from a config/data one. */
    val terminalErrorCode: String? = null,
)

class BudgetAdviceViewModel(
    private val repository: BudgetActions,
    initialMonth: String = YearMonth.now().toString(),
    /** Resolves the request target month (backend `YYYY-MM`) at request time:
     *  a back-stack-restored page can outlive a month rollover, and the screen
     *  has no month selector, so generating must always target the CURRENT
     *  month. Injectable for rollover tests. */
    private val monthProvider: () -> String = { YearMonth.now().toString() },
) : ViewModel() {
    private val _state = MutableStateFlow(
        BudgetAdviceUiState(
            month = initialMonth,
            canRequest = repository.canModifyLedger(),
        ),
    )
    val uiState: StateFlow<BudgetAdviceUiState> = _state.asStateFlow()
    private var requestGeneration = 0

    /** Advice data generation the displayed Ready result was produced under
     *  (null while nothing advice-bearing is shown). Compared against
     *  [BudgetActions.adviceInvalidations] emissions. */
    private var displayedResultGeneration: Int? = null

    init {
        observeLedgerChanges()
        restoreCachedAdvice()
        observeAdviceInvalidations()
    }

    private fun observeAdviceInvalidations() {
        // The Plan back stack preserves this VM across domain switches, so a
        // write that invalidated the advice cache elsewhere must also drop the
        // still-displayed result it was computed from. Only a Ready result is
        // affected: terminal states are config truth (invalidation changes no
        // config), in-flight requests are Loading (round-8 generation owns
        // their lifecycle), and no refetch is fired — the user taps 生成 again.
        viewModelScope.launch {
            repository.adviceInvalidations.collect { generation ->
                val displayedAt = displayedResultGeneration
                displayedResultGeneration = generation
                if (displayedAt != null && generation > displayedAt) {
                    _state.update { current ->
                        if (current.loadState != BudgetAdviceLoadState.Ready) {
                            return@update current
                        }
                        current.copy(
                            loadState = BudgetAdviceLoadState.Idle,
                            result = null,
                        )
                    }
                }
            }
        }
    }

    private fun restoreCachedAdvice() {
        // The page-scoped VM is destroyed on route exit; the repository keeps a
        // process-lifetime last-success cache keyed by (ledger, month), so a
        // reopen after an already quota-counted call renders that result
        // instead of firing a second counted request. Only applies while the
        // screen is still Idle (a concurrent request/ledger switch wins).
        viewModelScope.launch {
            val cached = repository.cachedBudgetAdvice(_state.value.month) ?: return@launch
            _state.update { current ->
                if (current.loadState != BudgetAdviceLoadState.Idle) return@update current
                current.adviceLoaded(cached)
            }
        }
    }

    private fun observeLedgerChanges() {
        viewModelScope.launch {
            var observedLedgerId: String? = null
            var observedRole: String? = null
            var firstEmission = true
            repository.observeLedgerAccessState()
                .distinctUntilChanged()
                .collect { access ->
                    val ledgerId = access?.ledgerId
                    val role = access?.role
                    if (firstEmission) {
                        // Baseline (the ledger the VM was created under), mirroring
                        // the previous drop(1) semantics.
                        firstEmission = false
                        observedLedgerId = ledgerId
                        observedRole = role
                        return@collect
                    }
                    if (ledgerId != observedLedgerId) {
                        observedLedgerId = ledgerId
                        observedRole = role
                        requestGeneration += 1
                        _state.update { current ->
                            current.copy(
                                loadState = BudgetAdviceLoadState.Idle,
                                canRequest = repository.canModifyLedger(),
                                result = null,
                                error = null,
                                terminalErrorCode = null,
                            )
                        }
                        restoreCachedAdvice()
                    } else if (role != observedRole) {
                        val previousRole = observedRole
                        observedRole = role
                        onRoleReprojection(previousRole, role)
                    }
                }
        }
    }

    private fun onRoleReprojection(previousRole: String?, newRole: String?) {
        // viewer→member/owner opens modification; member→owner additionally
        // opens the live advisor (owner-gated server-side). Demotion re-gates
        // in place (round-5 semantics); a capability INCREASE re-offers
        // generation only when the terminal state came from a role/config 403 —
        // never auto-requesting, never wiping rendered content.
        val capabilityIncreased =
            (!ledgerRoleCanModify(previousRole) && ledgerRoleCanModify(newRole)) ||
                (newRole == LEDGER_ROLE_OWNER && previousRole != LEDGER_ROLE_OWNER)
        _state.update { current ->
            val regated = current.copy(canRequest = repository.canModifyLedger())
            if (capabilityIncreased &&
                regated.loadState == BudgetAdviceLoadState.Unavailable &&
                regated.terminalErrorCode in ROLE_GATED_ADVISOR_ERROR_CODES
            ) {
                regated.copy(
                    loadState = BudgetAdviceLoadState.Idle,
                    error = null,
                    terminalErrorCode = null,
                )
            } else {
                regated
            }
        }
    }

    fun requestAdvice() {
        if (_state.value.loadState == BudgetAdviceLoadState.Loading) return
        if (!repository.canModifyLedger()) {
            _state.update {
                it.copy(
                    canRequest = false,
                    loadState = BudgetAdviceLoadState.Idle,
                    result = null,
                    error = UiText.res(R.string.common_readonly_ledger),
                    terminalErrorCode = null,
                )
            }
            return
        }
        // Resolve the target month now — not at construction: the subtitle and
        // the request (and thereby the cache key) all track this value, so a
        // page kept open across a month rollover generates for the NEW month.
        val month = monthProvider()
        val generation = requestGeneration
        val invalidationGenerationAtStart = repository.adviceInvalidations.value
        viewModelScope.launch {
            _state.update {
                it.copy(
                    month = month,
                    loadState = BudgetAdviceLoadState.Loading,
                    canRequest = true,
                    error = null,
                    terminalErrorCode = null,
                )
            }
            repository.requestBudgetAdvice(month)
                .onSuccess { result ->
                    _state.update {
                        if (generation != requestGeneration || month != it.month) return@update it
                        if (repository.adviceInvalidations.value != invalidationGenerationAtStart) {
                            // An advice-input write landed mid-flight (domain
                            // switch during a slow live call): the store already
                            // refused to cache/restore this result — mirror that
                            // stale-write guard at the display layer and drop to
                            // Idle rather than show pre-write advice. No retry is
                            // fired; the user taps 生成 again for fresh advice.
                            return@update it.copy(
                                loadState = BudgetAdviceLoadState.Idle,
                                result = null,
                            )
                        }
                        it.adviceLoaded(result)
                    }
                }
                .onFailure { error ->
                    _state.update {
                        if (generation != requestGeneration || month != it.month) return@update it
                        it.adviceFailed(error)
                    }
                }
        }
    }

    private fun BudgetAdviceUiState.adviceLoaded(result: BudgetAdviceResult): BudgetAdviceUiState {
        // Backend contract: advice == null carries a reason_code. Terminal
        // (retry cannot succeed right now): `ai_advisor_provider_empty` (the
        // only genuinely-disabled code — non-live provider) and
        // `ai_advisor_payload_invalid` (deterministic fail-closed guard — same
        // month + unchanged data rejects again). Everything else retryable or
        // Empty per below.
        val reasonCode = result.reasonCode?.trim()
        val terminalBody = when (reasonCode) {
            PROVIDER_DISABLED_REASON -> UiText.res(R.string.budget_advice_unavailable_body)
            PAYLOAD_INVALID_REASON -> UiText.res(R.string.budget_advice_payload_invalid_body)
            else -> null
        }
        val terminal = result.advice == null && terminalBody != null
        // Transient live-provider call/parse failures arrive as a 200 with
        // advice == null (last_error_code overrides the default reason), not as
        // an HTTP error — classify them as the retryable Failed state, not the
        // add-data Empty guidance.
        val transientCallFailure = result.advice == null && reasonCode in RETRYABLE_NULL_ADVICE_REASONS
        if (result.advice != null) {
            // Stamp the Ready result with the CURRENT invalidation generation
            // (read synchronously, not via the collector) so an invalidation
            // that already landed before this apply can't be mistaken for a
            // newer one later — the no-self-clearing guarantee.
            displayedResultGeneration = repository.adviceInvalidations.value
        }
        return copy(
            loadState = when {
                result.advice != null -> BudgetAdviceLoadState.Ready
                terminal -> BudgetAdviceLoadState.Unavailable
                transientCallFailure -> BudgetAdviceLoadState.Failed
                else -> BudgetAdviceLoadState.Empty
            },
            canRequest = repository.canModifyLedger(),
            result = result,
            error = when {
                terminal -> terminalBody
                transientCallFailure -> UiText.res(R.string.budget_advice_load_failed)
                else -> null
            },
            terminalErrorCode = null,
        )
    }

    private fun BudgetAdviceUiState.adviceFailed(error: Throwable): BudgetAdviceUiState {
        // Live-advisor 403 gates (owner not confirmed / member is not the owner)
        // cannot be retried away on this device; the backend's registered copy
        // rides the failure through toUiText as-is.
        val terminalCode = (error as? RepositoryException)?.errorCode?.trim()
        val terminal = terminalCode in TERMINAL_ADVISOR_ERROR_CODES
        return copy(
            loadState = if (terminal) {
                BudgetAdviceLoadState.Unavailable
            } else {
                BudgetAdviceLoadState.Failed
            },
            canRequest = repository.canModifyLedger(),
            error = error.toUiText(R.string.budget_advice_load_failed),
            terminalErrorCode = if (terminal) terminalCode else null,
        )
    }

    private companion object {
        const val PROVIDER_DISABLED_REASON = "ai_advisor_provider_empty"

        /** The fail-closed outbound-schema guard (_runner.py:72) rejects the
         *  locally built payload BEFORE the provider call, so the same month
         *  with unchanged data fails deterministically — terminal, never
         *  retryable. */
        const val PAYLOAD_INVALID_REASON = "ai_advisor_payload_invalid"

        /** Null-advice reason codes that mean a transient live-provider failure
         *  (retry may succeed): the `openai_compat` `last_error_code` values at
         *  backend/app/services/budget_advisor_service/_providers.py:161-180.
         *  Keep in sync with the backend when new last_error_code values appear. */
        val RETRYABLE_NULL_ADVICE_REASONS = setOf(
            "ai_advisor_provider_call_failed",
            "ai_advisor_provider_unexpected_error",
            "ai_advisor_response_parse_failed",
            "ai_advisor_response_unexpected_error",
        )

        val TERMINAL_ADVISOR_ERROR_CODES = setOf(
            "ai_advisor_owner_required",
            "ai_advisor_not_confirmed",
            // 24h-window quota cap (_audit.py:131-138): every attempt 429s until
            // the window slides, so retrying today can never succeed — terminal.
            // Deliberately excludes ai_advisor_rate_limited (short-window 429,
            // errors.py:147): there a later retry IS meaningful, stays Failed.
            "ai_advisor_daily_limit_exceeded",
        )

        /** Terminal codes a capability increase (member→owner promotion) can
         *  plausibly clear — re-offered as Idle on role increase. Only
         *  owner_required qualifies: _runner.py checks not_confirmed BEFORE
         *  owner_required, so promotion never clears an unconfirmed advisor
         *  (that gate lifts only when the owner confirms server-side, which
         *  produces no client signal — the page-scoped VM re-offers on its
         *  next recreation). Also excludes the daily quota cap: a role change
         *  does not reset the 24h window. */
        val ROLE_GATED_ADVISOR_ERROR_CODES = setOf(
            "ai_advisor_owner_required",
        )
    }
}
