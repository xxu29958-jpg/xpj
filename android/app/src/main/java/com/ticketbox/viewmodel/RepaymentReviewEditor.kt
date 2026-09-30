package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepaymentReviewActions
import com.ticketbox.data.repository.RepaymentReviewState
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.UiText
import androidx.lifecycle.SavedStateHandle
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal data class RepaymentReviewEditorContext(
    val state: MutableStateFlow<RepaymentDraftInboxUiState>,
    val binding: () -> LogicalSessionBinding?,
    val owns: (LogicalSessionBinding) -> Boolean,
    val refresh: () -> Unit,
    val confirm: (String, Debt) -> Unit,
)

/** Editor lifetime follows its inbox; durable input and commands belong to the repository. */
internal class RepaymentReviewEditor(private val reviews: RepaymentReviewActions, private val scope: CoroutineScope,
    private val context: RepaymentReviewEditorContext, private val saved: SavedStateHandle) {
    private var reviewJob: kotlinx.coroutines.Job? = null
    private val bindingAdapter = Moshi.Builder().build().adapter(LogicalSessionBinding::class.java)
    private fun focusKey(binding: LogicalSessionBinding) = "repayment.review.focus:" + bindingAdapter.toJson(binding)

    fun restoreIfNeeded() {
        if (context.state.value.reviewId != null) return
        val binding = context.binding() ?: return
        saved.get<String>(focusKey(binding))?.let(::openReview)
    }

    fun openReview(publicId: String) {
        val binding = context.binding() ?: return
        val capture = context.state.value.drafts.singleOrNull { it.publicId == publicId } ?: return
        saved[focusKey(binding)] = publicId
        reviewJob?.cancel()
        context.state.update { it.copy(reviewId = publicId, review = RepaymentReviewState(null), error = null) }
        reviewJob = scope.launch {
            val opened = reviews.open(binding, capture, context.state.value.suggestedDebtByDraftId[publicId])
            if (!context.owns(binding)) return@launch
            if (opened.isFailure) {
                context.state.update { it.copy(error = opened.exceptionOrNull()?.toUiText(R.string.repayment_draft_load_failed)) }
                return@launch
            }
            var seenReceipt: Long? = null
            reviews.observe(binding, publicId).collect { review ->
                if (!context.owns(binding)) return@collect
                context.state.update { it.copy(review = review) }
                val completed = review.original?.takeIf { it.status == com.ticketbox.data.local.PendingMutationStatus.Done }
                if (completed != null && completed.id != seenReceipt) { seenReceipt = completed.id; context.refresh() }
            }
        }
    }

    fun closeReview() {
        reviewJob?.cancel()
        context.binding()?.let { saved.remove<String>(focusKey(it)) }
        context.state.update { it.copy(reviewId = null, review = RepaymentReviewState(null)) }
    }

    fun updateReviewMoney(currency: String, amount: String) {
        val input = context.state.value.review.input ?: return
        context.state.update { it.copy(review = it.review.copy(input = input.copy(currency = currency, amountText = amount))) }
        reviewAction { binding, publicId -> reviews.money(binding, publicId, currency, amount) }
    }

    fun selectReviewDebt(debt: Debt) = reviewAction { binding, publicId -> reviews.select(binding, publicId, debt) }

    fun submitReview() {
        val input = context.state.value.review.input ?: return
        val selected = context.state.value.targetDebts.singleOrNull { it.publicId == input.debtPublicId }
        if (selected == null || selected.rowVersion != input.debtRowVersion) {
            context.state.update { it.copy(error = UiText.res(R.string.repayment_draft_target_changed)) }
            return
        }
        context.confirm(input.draftPublicId, selected)
    }

    fun recoverReview(stop: Boolean) = reviewAction { binding, publicId -> reviews.recover(binding, publicId, stop) }

    fun reviewAgain() = reviewAction { binding, publicId -> reviews.reviewAgain(binding, publicId) }

    private fun reviewAction(action: suspend (LogicalSessionBinding, String) -> Result<Unit>) {
        val binding = context.binding() ?: return
        val publicId = context.state.value.reviewId ?: return
        scope.launch(start = kotlinx.coroutines.CoroutineStart.UNDISPATCHED) {
            val result = action(binding, publicId)
            if (!context.owns(binding)) return@launch
            context.state.update { it.copy(error = result.exceptionOrNull()?.toUiText(R.string.repayment_draft_confirm_failed)) }
        }
    }

}
