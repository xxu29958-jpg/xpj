package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantCatalogDeleteRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeRequest
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy

/** Called only inside MerchantRepository's exact logical-session guard; never updates the current query. */
internal suspend fun ApiService.submitCatalogDraft(draft: MerchantDraft): MerchantDraft {
    val source = requireNotNull(draft.source)
    if (draft.kind == MerchantDraftKind.Merge) {
        val target = requireNotNull(draft.target)
        val policy = requireNotNull(draft.aliasPolicy)
        val receipt = mergeMerchantCatalog(source.publicId, MerchantCatalogMergeRequest(
            source.rowVersion, target.publicId, target.rowVersion, policy.apiValue, false), draft.key)
        requireCatalogSnapshot(receipt.source, source)
        requireCatalogSnapshot(receipt.target, target)
        check(receipt.source.status == "merged" && receipt.source.mergedIntoPublicId == target.publicId &&
            (receipt.createdAliasPublicId != null) == (policy == MerchantCatalogAliasPolicy.CreateSourceAlias)) {
            "返回的原商家合并回执无法核对。"
        }
        return draft.copy(phase = "accepted", mergeReceipt = receipt, error = null)
    }
    val receipt = when (draft.kind) {
        MerchantDraftKind.Rename -> updateMerchantCatalog(source.publicId,
            MerchantCatalogUpdateRequest(source.rowVersion, displayName = draft.displayName), draft.key)
        MerchantDraftKind.Visibility -> updateMerchantCatalog(source.publicId,
            MerchantCatalogUpdateRequest(source.rowVersion, status = draft.nextStatus), draft.key)
        MerchantDraftKind.Delete -> deleteMerchantCatalog(source.publicId, MerchantCatalogDeleteRequest(source.rowVersion), draft.key)
        else -> error("Expected an original catalog command")
    }
    requireCatalogSnapshot(receipt, source)
    check(draft.kind != MerchantDraftKind.Delete || receipt.deletedAt != null) { "返回的原删除回执无法核对。" }
    check(draft.kind != MerchantDraftKind.Visibility || receipt.status == draft.nextStatus) { "返回的原显示设置无法核对。" }
    return draft.copy(phase = "accepted", catalogReceipt = receipt, error = null)
}

private fun requireCatalogSnapshot(receipt: MerchantCatalogDto, original: MerchantCatalog) {
    check(receipt.publicId == original.publicId && receipt.rowVersion == original.rowVersion + 1) {
        "返回的原商家操作回执无法核对。"
    }
}
