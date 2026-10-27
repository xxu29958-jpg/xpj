package com.ticketbox.data.repository

/** Read-only originals; dispatch continues to decode the retained wire payload. */
sealed interface DebtWriteSubmission {
    val subject: DebtWriteSubject
    val originSessionGeneration: String
    val originBindingRevision: String
    val expectedRowVersion: Long
}
sealed interface DebtAmountSubmission : DebtWriteSubmission { val amountCents: Long }

data class DebtRepaymentSubmission(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: com.ticketbox.domain.model.RepaymentCreateRequest,
) : DebtAmountSubmission {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
    override val amountCents: Long get() = request.amountCents
}

data class DebtAdjustmentSubmission(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: com.ticketbox.domain.model.DebtAdjustmentCreateRequest,
) : DebtAmountSubmission {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
    override val amountCents: Long get() = request.amountCents
}

data class DebtVoidSubmission(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: com.ticketbox.domain.model.DebtVoidCreateRequest,
) : DebtWriteSubmission {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

data class DebtRepaymentVoidSubmission(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: com.ticketbox.domain.model.RepaymentVoidCreateRequest,
) : DebtWriteSubmission {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

data class DebtKindSubmission(
    val revision: Int,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: com.ticketbox.domain.model.DebtKindSetRequest,
) : DebtWriteSubmission {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

data class RepaymentReviewSubmission(
    val revision: Int,
    val draftPublicId: String,
    override val subject: DebtWriteSubject,
    override val originSessionGeneration: String,
    override val originBindingRevision: String,
    val request: com.ticketbox.domain.model.RepaymentDraftConfirmRequest,
    val reviewedCurrency: String,
    val reviewedAmount: String,
) : DebtWriteSubmission {
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

internal fun DebtRepaymentPayload.toView() = DebtRepaymentSubmission(
    revision = revision,
    subject = subject,
    originSessionGeneration = originSessionGeneration,
    originBindingRevision = originBindingRevision,
    request = request.toDomain(),
)

internal fun DebtAdjustmentPayload.toView() = DebtAdjustmentSubmission(
    revision = revision,
    subject = subject,
    originSessionGeneration = originSessionGeneration,
    originBindingRevision = originBindingRevision,
    request = request,
)

internal fun DebtVoidPayload.toView() = DebtVoidSubmission(
    revision = revision,
    subject = subject,
    originSessionGeneration = originSessionGeneration,
    originBindingRevision = originBindingRevision,
    request = request,
)

internal fun DebtRepaymentVoidPayload.toView() = DebtRepaymentVoidSubmission(
    revision = revision,
    subject = subject,
    originSessionGeneration = originSessionGeneration,
    originBindingRevision = originBindingRevision,
    request = request,
)

internal fun DebtKindPayload.toView() = DebtKindSubmission(
    revision = revision,
    subject = subject,
    originSessionGeneration = originSessionGeneration,
    originBindingRevision = originBindingRevision,
    request = request,
)

internal fun RepaymentReviewPayload.toView() = RepaymentReviewSubmission(
    revision = revision,
    draftPublicId = draftPublicId,
    subject = subject,
    originSessionGeneration = originSessionGeneration,
    originBindingRevision = originBindingRevision,
    request = request.toDomain(),
    reviewedCurrency = reviewedCurrency,
    reviewedAmount = reviewedAmount,
)
internal fun DebtWriteIntent.toView(): DebtWriteSubmission = when (this) {
    is DebtRepaymentPayload -> toView()
    is DebtAdjustmentPayload -> toView()
    is DebtVoidPayload -> toView()
    is DebtRepaymentVoidPayload -> toView()
    is DebtKindPayload -> toView()
    is RepaymentReviewPayload -> toView()
}

internal fun DebtWriteSubmission.matchesOriginalBinding(binding: LogicalSessionBinding): Boolean =
    originSessionGeneration == binding.sessionGeneration && originBindingRevision == binding.bindingRevision
