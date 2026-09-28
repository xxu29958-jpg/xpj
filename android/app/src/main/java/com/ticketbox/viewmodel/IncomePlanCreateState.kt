package com.ticketbox.viewmodel

import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.data.repository.canonicalServerOriginOrNull
import com.ticketbox.domain.model.UiText

/** An unsubmitted creation belongs to its original complete identity and stable command key. */
@JsonClass(generateAdapter = true)
data class IncomePlanCreateSession(
    val binding: LogicalSessionBinding,
    val creationKey: String,
    val draft: IncomePlanDraftUi,
    val phase: IncomePlanCreationPhase = IncomePlanCreationPhase.Draft,
) {
    fun matchesSubmission(pending: PendingIncomePlanSubmission): Boolean {
        val intent = pending.intent ?: return false
        return pending.hasSupportedIntent && pending.row.type == PendingMutationType.CreateIncomePlan &&
            pending.row.idempotencyKey == creationKey && pending.row.ownerKey == binding.ownerKey &&
            pending.row.ledgerId == binding.ledgerId &&
            canonicalServerOriginOrNull(pending.row.serverUrl) == canonicalServerOriginOrNull(binding.serverUrl) &&
            intent.originSessionGeneration == binding.sessionGeneration &&
            intent.originBindingRevision == binding.bindingRevision
    }
}

enum class IncomePlanCreationPhase { Draft, Publishing, NeedsRecovery }

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
