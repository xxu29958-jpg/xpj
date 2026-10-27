package com.ticketbox.domain.model

data class RepaymentReviewInput(
    val ownerKey: String,
    val ledgerId: String,
    val draftPublicId: String,
    val serverUrl: String,
    val sessionGeneration: String,
    val bindingRevision: String,
    val originalKey: String,
    val currency: String,
    val amountText: String,
    val debtPublicId: String? = null,
    val debtLabel: String? = null,
    val debtHomeCurrency: String? = null,
    val debtRowVersion: Long? = null,
    val submittedAction: String? = null,
    val paymentDate: String? = null,
    val calendarRevision: Long? = null,
    val targetChoiceExplicit: Boolean = false,
)
