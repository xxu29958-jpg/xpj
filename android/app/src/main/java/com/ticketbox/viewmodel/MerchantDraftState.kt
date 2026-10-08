package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.MerchantDraft
import com.ticketbox.data.repository.MerchantDraftKind
import com.ticketbox.domain.model.UiText

data class MerchantDraftState(
    val drafts: List<MerchantDraft> = emptyList(),
    val binding: LogicalSessionBinding? = null,
    val ready: Boolean = false,
    val canModify: Boolean = false,
    val busy: Boolean = false,
    val error: UiText? = null,
) {
    fun draft(kind: MerchantDraftKind, sourceId: String? = null) = drafts.firstOrNull {
        it.kind == kind && (kind.isCreation || it.source?.publicId == sourceId)
    }

    fun canEdit(kind: MerchantDraftKind): Boolean = ready && canModify && !busy &&
        (draft(kind) == null || draft(kind)?.let(::canEdit) == true)

    fun canEdit(draft: MerchantDraft): Boolean = ready && canModify && !busy &&
        draft.binding == binding && draft.phase == "editing"

    fun canSubmit(kind: MerchantDraftKind): Boolean = draft(kind)?.let(::canSubmit) == true

    fun canSubmit(draft: MerchantDraft): Boolean {
        return ready && canModify && !busy && draft.binding == binding && draft.hasRequiredInput() &&
            !draft.sourceUnavailable && !draft.targetUnavailable && draft.phase in setOf("editing", "unconfirmed")
    }

    fun canReview(draft: MerchantDraft): Boolean = ready && canModify && !busy &&
        (draft.binding != binding || draft.phase in setOf("editing", "rejected"))
}

private fun MerchantDraft.hasRequiredInput(): Boolean = when (kind) {
    MerchantDraftKind.Catalog, MerchantDraftKind.Rename -> displayName.isNotBlank()
    MerchantDraftKind.Alias -> canonicalMerchant.isNotBlank() && alias.isNotBlank()
    MerchantDraftKind.Merge -> target?.let { it.publicId != source?.publicId && it.isActive && it.deletedAt == null } == true &&
        aliasPolicy != null
    MerchantDraftKind.Visibility -> nextStatus in setOf("active", "hidden")
    MerchantDraftKind.Delete -> true
}
