package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.data.repository.toDomain

/** Identity and editor generation accepted before asynchronous image preparation. */
class DebtBillParseAttempt internal constructor(
    val binding: LogicalSessionBinding,
    val homeCurrency: CurrencyCode,
    internal val generation: Long,
)

enum class DebtDraftField {
    Direction,
    Counterparty,
    Note,
    Amount,
    Kind,
    InstallmentCount,
    InstallmentPeriod,
    PrincipalDate,
}

enum class DebtBillTaskAction { Resume, Parse, RetryCapture, Discard, Preview }

fun DebtListViewModel.updateDraftDirection(value: String) =
    updateDraftField(DebtDraftField.Direction, value)

fun DebtListViewModel.updateDraftCounterparty(value: String) =
    updateDraftField(DebtDraftField.Counterparty, value)

fun DebtListViewModel.updateDraftNote(value: String) =
    updateDraftField(DebtDraftField.Note, value)

fun DebtListViewModel.updateDraftAmount(value: String) =
    updateDraftField(DebtDraftField.Amount, value)

fun DebtListViewModel.updateDraftKind(value: String) =
    updateDraftField(DebtDraftField.Kind, value)

fun DebtListViewModel.updateDraftInstallmentCount(value: String) =
    updateDraftField(DebtDraftField.InstallmentCount, value)

fun DebtListViewModel.updateDraftInstallmentPeriod(value: String) =
    updateDraftField(DebtDraftField.InstallmentPeriod, value)

fun DebtListViewModel.updateDraftPrincipalDate(value: String) =
    updateDraftField(DebtDraftField.PrincipalDate, value)

internal fun DebtListUiState.acceptsBillTask(action: DebtBillTaskAction): Boolean =
    !isSubmitting &&
        (canModify || action in setOf(DebtBillTaskAction.Resume, DebtBillTaskAction.Preview)) &&
        (!publicationUnverified || action in setOf(DebtBillTaskAction.Resume, DebtBillTaskAction.Preview))

internal fun DebtCreationDraft.sourceReference(state: DebtListUiState) = frozenBillSource ?: state.activeBill?.source?.let {
    com.ticketbox.data.remote.dto.DebtBillSourceReferenceDto(it.publicId, it.rowVersion)
}

internal data class DebtBillTaskResult(
    val source: com.ticketbox.data.remote.dto.DebtBillCaptureDto? = null,
    val outcome: com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto? = null,
    val preview: ByteArray? = null,
    val ended: Boolean = false,
) {
    fun ends(original: DebtCreationDraft?, captureKey: String): Boolean = ended && original?.billCaptureKey == captureKey

    fun prefill(state: DebtListUiState): DebtDraftUi? =
        outcome?.suggestion?.toDomain()?.let { state.addDraft.prefillFrom(it).withInheritedModelFrom(state.debts) }
}

/** Network work returns to the original editor's binding/generation guard before any UI update. */
internal suspend fun runDebtBillTask(sources: com.ticketbox.data.repository.DebtBillActions,
    input: com.ticketbox.data.repository.DebtBillInput?, action: DebtBillTaskAction): Result<DebtBillTaskResult> = try {
    // A successful local lookup, not a failed capture reply, proves no input was admitted.
    require(input != null || action == DebtBillTaskAction.Discard) { "Debt bill input is missing" }
    Result.success(when (action) {
        DebtBillTaskAction.Preview -> DebtBillTaskResult(preview = sources.original(requireNotNull(input)).getOrThrow())
        DebtBillTaskAction.RetryCapture -> { sources.recover(requireNotNull(input), discard = false).getOrThrow(); DebtBillTaskResult() }
        DebtBillTaskAction.Discard -> { input?.let { sources.recover(it, discard = true).getOrThrow() }; DebtBillTaskResult(ended = true) }
        else -> {
            val refreshed = sources.refresh(requireNotNull(input)).getOrThrow()
            val ended = refreshed.source?.status in setOf("confirmed", "rejected")
            val outcome = if (!ended && action == DebtBillTaskAction.Parse) {
                sources.suggest(refreshed, retry = refreshed.source?.parseOutcome != null).getOrThrow()
            } else null
            DebtBillTaskResult(source = refreshed.source, outcome = outcome, ended = ended)
        }
    })
} catch (cancelled: kotlinx.coroutines.CancellationException) {
    throw cancelled
} catch (error: Exception) {
    Result.failure(error)
}
