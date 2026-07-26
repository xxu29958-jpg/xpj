package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.BudgetActions
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.BudgetAdviceResult
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
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
)

class BudgetAdviceViewModel(
    private val repository: BudgetActions,
    initialMonth: String = YearMonth.now().toString(),
) : ViewModel() {
    private val _state = MutableStateFlow(
        BudgetAdviceUiState(
            month = initialMonth,
            canRequest = repository.canModifyLedger(),
        ),
    )
    val uiState: StateFlow<BudgetAdviceUiState> = _state.asStateFlow()
    private var requestGeneration = 0

    init {
        observeLedgerChanges()
        restoreCachedAdvice()
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
            repository.observeActiveLedgerId()
                .distinctUntilChanged()
                .drop(1)
                .collect {
                    requestGeneration += 1
                    _state.update { current ->
                        current.copy(
                            loadState = BudgetAdviceLoadState.Idle,
                            canRequest = repository.canModifyLedger(),
                            result = null,
                            error = null,
                        )
                    }
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
                )
            }
            return
        }
        val month = _state.value.month
        val generation = requestGeneration
        viewModelScope.launch {
            _state.update {
                it.copy(
                    loadState = BudgetAdviceLoadState.Loading,
                    canRequest = true,
                    error = null,
                )
            }
            repository.requestBudgetAdvice(month)
                .onSuccess { result ->
                    _state.update {
                        if (generation != requestGeneration || month != it.month) return@update it
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
        // Backend contract: advice == null carries a reason_code. Today
        // `ai_advisor_provider_empty` is the only genuinely-disabled code
        // (non-live provider — retrying cannot succeed until the server is
        // configured), so it alone maps to the terminal Unavailable state.
        val reasonCode = result.reasonCode?.trim()
        val providerUnavailable = result.advice == null && reasonCode == PROVIDER_DISABLED_REASON
        // Transient live-provider call/parse failures arrive as a 200 with
        // advice == null (last_error_code overrides the default reason), not as
        // an HTTP error — classify them as the retryable Failed state, not the
        // add-data Empty guidance.
        val transientCallFailure = result.advice == null && reasonCode in RETRYABLE_NULL_ADVICE_REASONS
        return copy(
            loadState = when {
                result.advice != null -> BudgetAdviceLoadState.Ready
                providerUnavailable -> BudgetAdviceLoadState.Unavailable
                transientCallFailure -> BudgetAdviceLoadState.Failed
                else -> BudgetAdviceLoadState.Empty
            },
            canRequest = repository.canModifyLedger(),
            result = result,
            error = when {
                providerUnavailable -> UiText.res(R.string.budget_advice_unavailable_body)
                transientCallFailure -> UiText.res(R.string.budget_advice_load_failed)
                else -> null
            },
        )
    }

    private fun BudgetAdviceUiState.adviceFailed(error: Throwable): BudgetAdviceUiState {
        // Live-advisor 403 gates (owner not confirmed / member is not the owner)
        // cannot be retried away on this device; the backend's registered copy
        // rides the failure through toUiText as-is.
        val terminal = (error as? RepositoryException)
            ?.errorCode?.trim() in TERMINAL_ADVISOR_ERROR_CODES
        return copy(
            loadState = if (terminal) {
                BudgetAdviceLoadState.Unavailable
            } else {
                BudgetAdviceLoadState.Failed
            },
            canRequest = repository.canModifyLedger(),
            error = error.toUiText(R.string.budget_advice_load_failed),
        )
    }

    private companion object {
        const val PROVIDER_DISABLED_REASON = "ai_advisor_provider_empty"

        /** Null-advice reason codes that mean a transient live-provider failure
         *  (retry may succeed): the `openai_compat` `last_error_code` values at
         *  backend/app/services/budget_advisor_service/_providers.py:161-180,
         *  plus `ai_advisor_payload_invalid` (the fail-closed outbound-schema
         *  guard, _runner.py:72). Keep in sync with the backend when new
         *  last_error_code values appear. */
        val RETRYABLE_NULL_ADVICE_REASONS = setOf(
            "ai_advisor_provider_call_failed",
            "ai_advisor_provider_unexpected_error",
            "ai_advisor_response_parse_failed",
            "ai_advisor_response_unexpected_error",
            "ai_advisor_payload_invalid",
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
    }
}
