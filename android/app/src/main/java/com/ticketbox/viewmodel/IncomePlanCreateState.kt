package com.ticketbox.viewmodel

import com.squareup.moshi.JsonClass
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.LocalRepositoryFailure
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.canonicalServerOriginOrNull
import com.ticketbox.domain.model.UiText

/** An unsubmitted creation belongs to its original complete identity and stable command key. */
@JsonClass(generateAdapter = true)
data class IncomePlanCreateSession(
    val binding: LogicalSessionBinding,
    val creationKey: String,
    val draft: IncomePlanDraftUi,
    val phase: IncomePlanCreationPhase = IncomePlanCreationPhase.Draft,
    val admissionFailure: IncomePlanAdmissionFailure? = null,
) {
    fun matchesSubmission(pending: PendingIncomePlanSubmission): Boolean {
        val intent = pending.intent ?: return false
        return pending.hasSupportedIntent && pending.row.status in IncomeCreationVisibleStatuses &&
            pending.row.type == PendingMutationType.CreateIncomePlan &&
            pending.row.idempotencyKey == creationKey && pending.row.ownerKey == binding.ownerKey &&
            pending.row.ledgerId == binding.ledgerId &&
            canonicalServerOriginOrNull(pending.row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl) &&
            intent.originSessionGeneration == binding.sessionGeneration &&
            intent.originBindingRevision == binding.bindingRevision
    }
}

/** Only statuses delivered by IncomePlanRepository.observeSubmissions can receive the draft. */
private val IncomeCreationVisibleStatuses = setOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight,
    PendingMutationStatus.Conflict, PendingMutationStatus.Failed, PendingMutationStatus.Done)

/** Retains the already displayable admission failure, not unstable Android resource IDs. */
@JsonClass(generateAdapter = true)
data class IncomePlanAdmissionFailure(val message: String, val errorCode: String?, val localFailure: String?) {
    fun asUiText(): UiText = RepositoryException(message, errorCode = errorCode,
        localFailure = LocalRepositoryFailure.entries.firstOrNull { it.name == localFailure })
        .toUiText(R.string.income_plan_add_failed)

    companion object {
        fun from(error: Throwable) = IncomePlanAdmissionFailure(error.message.orEmpty(),
            (error as? RepositoryException)?.errorCode, (error as? RepositoryException)?.localFailure?.name)
    }
}

enum class IncomePlanCreationPhase { Draft, DraftNeedsRecovery, Publishing, NeedsRecovery }

data class IncomePlanCreateUiState(
    val session: IncomePlanCreateSession? = null,
    val binding: LogicalSessionBinding? = null,
    val canModify: Boolean = false,
    val isSubmitting: Boolean = false,
    val isRestoring: Boolean = false,
    /** Room acceptance only; it does not imply that a financial plan has been confirmed. */
    val publishedRowId: Long? = null,
    val flashMessage: UiText? = null,
)
