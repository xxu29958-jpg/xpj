package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.SavedViewDeleteRequestDto
import com.ticketbox.data.remote.dto.SavedViewUpdateRequestDto

/** Native consumer of the shared saved-query owner; it never publishes a local result cache. */
class SavedQueryRepository(
    private val apiProvider: ApiServiceProvider,
    private val drafts: SavedQueryDraftStore,
) {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl }, context = "SavedQuery",
    )

    fun captureBinding() = guard.captureLogicalBinding()
    fun observeAccess() = apiProvider.observeActiveLedgerAccess()
    suspend fun catalog(binding: LogicalSessionBinding) = errors.safeCall {
        guard.bindExact(binding).call { it.savedViews().items }
    }
    suspend fun read(binding: LogicalSessionBinding, publicId: String) = errors.safeCall {
        guard.bindExact(binding).call { it.savedView(publicId) }
    }
    suspend fun results(binding: LogicalSessionBinding, publicId: String, page: Int) = errors.safeCall {
        guard.bindExact(binding).call { api ->
            api.savedViewResults(publicId, page).also { result ->
                require(result.conditions["ledger_id"] == binding.ledgerId)
                result.items.forEach { it.entry.toConfirmedStreamCacheItem(binding.ledgerId) }
            }
        }
    }
    suspend fun readDrafts(binding: LogicalSessionBinding) = errors.safeCall { drafts.read(binding) }
    suspend fun saveDraft(draft: SavedQueryDraft) = errors.safeCall { drafts.write(draft) }
    suspend fun acknowledge(draft: SavedQueryDraft) = errors.safeCall { drafts.consume(draft) }

    suspend fun submit(draft: SavedQueryDraft) = errors.safeCall {
        guard.bindExact(draft.binding).call { api ->
            val definition = draft.definition
            when (draft.command) {
                SavedQueryCommand.Create -> draft.copy(phase = "accepted", error = null,
                    receipt = api.createSavedView(definition, draft.key))
                SavedQueryCommand.Edit -> {
                    val original = requireNotNull(draft.baseline)
                    val request = with(definition) { SavedViewUpdateRequestDto(original.rowVersion,
                        name, monthMode, month, filter, tagPublicId, homeCurrencyCode, queryText, category) }
                    draft.copy(phase = "accepted", error = null,
                        receipt = api.updateSavedView(original.publicId, request, draft.key))
                }
                SavedQueryCommand.Delete -> {
                    val original = requireNotNull(draft.baseline)
                    draft.copy(phase = "accepted", error = null, deletionReceipt = api.deleteSavedView(
                        original.publicId, SavedViewDeleteRequestDto(original.rowVersion), draft.key))
                }
            }
        }
    }
}
