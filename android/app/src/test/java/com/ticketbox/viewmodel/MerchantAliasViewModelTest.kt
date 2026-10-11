package com.ticketbox.viewmodel

import com.ticketbox.data.local.PersistedLedgerIdentity

import com.ticketbox.R
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeApiServiceFactory
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.ledgerSessionFixture
import com.ticketbox.data.repository.FakeTicketboxSettingsStore
import com.ticketbox.data.repository.MerchantConflictDetails
import com.ticketbox.data.repository.MerchantRepository
import com.ticketbox.data.repository.MerchantDraft
import com.ticketbox.data.repository.MerchantDraftKind
import com.ticketbox.domain.model.MerchantCatalog
import com.ticketbox.data.repository.RepositoryConflictDetails
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.testServerSessionBinding
import com.ticketbox.data.repository.TestSessionFixture
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.domain.model.MerchantCatalogAliasPolicy
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class MerchantAliasViewModelTest {
    private val activeViewModels = mutableListOf<MerchantAliasViewModel>()

    private fun merchantAlias(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            advanceUntilIdle()
            cancelMerchantAliasTestViewModels(activeViewModels)
            advanceUntilIdle()
            activeViewModels.clear()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun createMerchantCatalogAddsCreatedItemAndShowsSuccess() = merchantAlias {
        val harness = harness()
        harness.vm.uiState.first { it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" } }

        harness.vm.uiState.first { it.drafts.ready }
        harness.vm.createMerchantCatalog("  蓝瓶咖啡  ")
        val accepted = harness.vm.drafts.state.first { it.drafts.any { draft -> draft.phase == "accepted" } }.drafts.single()
        harness.vm.drafts.acknowledge(accepted.kind, accepted.key)
        val state = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-created" }
        }

        assertEquals("  蓝瓶咖啡  ", harness.api.merchantCatalogCreateRequests.single().displayName)
        assertTrue(state.merchantCatalog.any { it.publicId == "catalog-created" })
        assertEquals(UiText.res(R.string.merchant_creation_confirmed), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
        assertEquals(1, state.changedRevision)
    }

    @Test
    fun toggleMerchantCatalogUsesRowVersionAndReplacesState() = merchantAlias {
        val harness = harness()
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.toggleMerchantCatalog(item)
        val state = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" && catalog.status == "hidden" }
        }

        assertEquals(listOf("catalog-1"), harness.api.merchantCatalogPatchTargets)
        assertEquals(1L, harness.api.merchantCatalogUpdateRequests.single().expectedRowVersion)
        assertEquals("hidden", harness.api.merchantCatalogUpdateRequests.single().status)
        assertEquals("hidden", state.merchantCatalog.single().status)
        assertEquals(UiText.res(R.string.merchant_command_confirmed), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun deleteMerchantCatalogUsesRowVersionAndDropsItem() = merchantAlias {
        val harness = harness()
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.deleteMerchantCatalog(item)
        val state = harness.vm.uiState.first {
            it.message == UiText.res(R.string.merchant_command_confirmed) && it.merchantCatalog.none { row -> row.publicId == "catalog-1" }
        }

        assertEquals(listOf("catalog-1"), harness.api.merchantCatalogDeleteTargets)
        assertEquals(1L, harness.api.merchantCatalogDeleteRequests.single().expectedRowVersion)
        assertTrue(state.merchantCatalog.none { it.publicId == "catalog-1" })
        assertEquals(UiText.res(R.string.merchant_command_confirmed), state.message)
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun renameMerchantCatalogConflictSuggestsMergeWithFreshTargetToken() = merchantAlias {
        val harness = harness {
            merchantCatalogItems = listOf(
                merchantCatalogDto(publicId = "source", displayName = "星巴克", rowVersion = 2L),
                merchantCatalogDto(publicId = "target", displayName = "蓝瓶咖啡", rowVersion = 3L),
            )
            merchantCatalogUpdateFailure = RepositoryException(
                message = "商家名已被占用。",
                errorCode = "state_conflict",
                conflict = RepositoryConflictDetails(
                    merchant = MerchantConflictDetails(
                        publicId = "target",
                        rowVersion = 9L,
                        displayName = "蓝瓶咖啡",
                        status = "active",
                        deleted = false,
                    ),
                ),
            )
        }
        val initial = harness.vm.uiState.first { it.merchantCatalog.size == 2 }
        val source = initial.merchantCatalog.single { it.publicId == "source" }

        harness.vm.renameMerchantCatalog(source, "蓝瓶咖啡")
        val state = harness.vm.uiState.first { it.mergeSuggestion != null }

        assertEquals(UiText.res(R.string.merchant_catalog_rename_conflict_merge_prompt, "蓝瓶咖啡"), state.message)
        assertEquals(MessageTone.Info, state.messageTone)
        val suggestion = requireNotNull(state.mergeSuggestion)
        assertEquals("source", suggestion.source.publicId)
        assertEquals("target", suggestion.target.publicId)
        assertEquals(9L, suggestion.target.rowVersion)
        assertEquals(0, state.changedRevision)
    }

    @Test
    fun mergeMerchantCatalogSendsAliasPolicyAndMarksSourceMerged() = merchantAlias {
        val harness = harness {
            merchantCatalogItems = listOf(
                merchantCatalogDto(publicId = "catalog-1", displayName = "星巴克", rowVersion = 1L),
                merchantCatalogDto(publicId = "catalog-2", displayName = "蓝瓶咖啡", rowVersion = 4L),
            )
        }
        val initial = harness.vm.uiState.first { it.merchantCatalog.size == 2 }
        val source = initial.merchantCatalog.single { it.publicId == "catalog-1" }
        val target = initial.merchantCatalog.single { it.publicId == "catalog-2" }

        harness.vm.mergeMerchantCatalog(source, target, MerchantCatalogAliasPolicy.CreateSourceAlias)
        val state = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" && catalog.status == "merged" }
        }

        assertEquals(listOf("catalog-1"), harness.api.merchantCatalogMergeTargets)
        val request = harness.api.merchantCatalogMergeRequests.single()
        assertEquals(1L, request.expectedRowVersion)
        assertEquals("catalog-2", request.targetPublicId)
        assertEquals(4L, request.targetRowVersion)
        assertEquals("create_source_alias", request.aliasPolicy)
        assertEquals(
            UiText.res(R.string.merchant_command_confirmed),
            state.message,
        )
        assertEquals(MessageTone.Success, state.messageTone)
    }

    @Test
    fun viewerCannotMutateMerchantCatalog() = merchantAlias {
        val harness = harness(role = "viewer")
        val initial = harness.vm.uiState.first {
            it.merchantCatalog.any { catalog -> catalog.publicId == "catalog-1" }
        }
        val item = initial.merchantCatalog.single { it.publicId == "catalog-1" }

        harness.vm.createMerchantCatalog("蓝瓶咖啡")
        harness.vm.renameMerchantCatalog(item, "蓝瓶咖啡")
        harness.vm.toggleMerchantCatalog(item)
        harness.vm.mergeMerchantCatalog(item, item, MerchantCatalogAliasPolicy.None)
        harness.vm.deleteMerchantCatalog(item)

        assertTrue(harness.api.merchantCatalogCreateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogMergeRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogDeleteRequests.isEmpty())
        assertEquals(UiText.res(R.string.common_readonly_ledger), harness.vm.uiState.value.message)
        assertEquals(MessageTone.Danger, harness.vm.uiState.value.messageTone)
        assertEquals(0, harness.vm.uiState.value.changedRevision)
    }

    @Test
    fun acceptedMergeWithFailedAliasReadCanRecoverWithoutMergingAgain() = merchantAlias {
        val harness = harness {
            merchantCatalogItems = listOf(
                merchantCatalogDto(publicId = "catalog-1", displayName = "星巴克", rowVersion = 1L),
                merchantCatalogDto(publicId = "catalog-2", displayName = "蓝瓶咖啡", rowVersion = 4L),
            )
        }
        val initial = harness.vm.uiState.first { it.merchantCatalog.size == 2 && it.merchantAliases.isNotEmpty() }
        harness.api.merchantAliasesFailure = java.io.IOException("Read failed after accepted merge")
        harness.vm.mergeMerchantCatalog(initial.merchantCatalog[0], initial.merchantCatalog[1],
            MerchantCatalogAliasPolicy.CreateSourceAlias)
        val accepted = harness.vm.uiState.first { it.changedRevision == 1 && it.aliasesLoadFailed }
        assertTrue(accepted.merchantAliases.isEmpty(), "The incomplete alias query must not masquerade as the current list")
        assertTrue(accepted.aliasesLoadFailed)
        assertEquals(MessageTone.Success, accepted.messageTone)
        assertEquals(1, accepted.changedRevision)

        harness.api.merchantAliasesFailure = null
        harness.vm.loadMerchantAliases()
        val recovered = harness.vm.uiState.first { it.merchantAliases.any { alias -> alias.publicId == "alias-created-by-merge" } }
        assertEquals(false, recovered.aliasesLoadFailed)
        assertEquals(accepted.editorCompletion, recovered.editorCompletion)
        assertEquals(1, harness.api.merchantCatalogMergeRequests.size)
    }

    @Test fun explicitRenameReviewReadsTheOriginalObjectWithoutPublishing() = merchantAlias {
        val harness = harness()
        val original = harness.vm.uiState.first { it.merchantCatalog.isNotEmpty() }.merchantCatalog.single()
        harness.api.merchantCatalogItems = listOf(merchantCatalogDto(original.publicId, "他端改名", 9))
        val reviewed = harness.vm.reviewCatalog(MerchantDraftKind.Rename, original)
        assertEquals(original.publicId, reviewed?.source?.publicId)
        assertEquals(9L, reviewed?.source?.rowVersion)
        assertEquals("他端改名", reviewed?.source?.displayName)
        assertEquals(0, harness.vm.uiState.value.changedRevision)
        assertEquals(null, harness.vm.uiState.value.editorCompletion)
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
        harness.vm.renameMerchantCatalog(original, "原稿名称")
        harness.vm.uiState.first { it.changedRevision == 1 }
        assertEquals(listOf(original.publicId), harness.api.merchantCatalogPatchTargets)
        assertEquals(9L, harness.api.merchantCatalogUpdateRequests.single().expectedRowVersion)
    }

    @Test fun renameReviewDoesNotRetargetDeletedMergedOrReplacedMerchants() = merchantAlias {
        val harness = harness()
        val original = harness.vm.uiState.first { it.merchantCatalog.isNotEmpty() }.merchantCatalog.single()
        val current = merchantCatalogDto(original.publicId, original.displayName, 9)
        for (items in listOf(emptyList(), listOf(current.copy(deletedAt = "2026-10-08T00:00:00Z")),
            listOf(current.copy(status = "merged", mergedIntoPublicId = "target")), listOf(current.copy(publicId = "replacement")))) {
            harness.api.merchantCatalogItems = items
            val reviewed = requireNotNull(harness.vm.reviewCatalog(MerchantDraftKind.Rename, original))
            assertEquals(original, reviewed.source)
            assertTrue(reviewed.sourceUnavailable)
            harness.vm.drafts.submit(reviewed.kind, original.publicId)
            assertEquals(0, harness.vm.uiState.value.changedRevision)
        }
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
    }

    @Test fun mergeReviewDoesNotRetargetUnavailableOrReplacedMerchants() = merchantAlias {
        val harness = harness { merchantCatalogItems = listOf(
            merchantCatalogDto("source", "原商家", 7), merchantCatalogDto("target", "目标商家", 11)) }
        val original = harness.vm.uiState.first { it.merchantCatalog.size == 2 }.merchantCatalog
        val source = original.single { it.publicId == "source" }
        val target = original.single { it.publicId == "target" }
        val currentSource = merchantCatalogDto("source", "他端原商家", 8)
        val currentTarget = merchantCatalogDto("target", "目标商家", 12)
        for (unavailable in listOf(null, currentTarget.copy(status = "hidden"), currentTarget.copy(deletedAt = "2026-10-08T00:00:00Z"),
            currentTarget.copy(status = "merged", mergedIntoPublicId = "replacement"), currentTarget.copy(publicId = "same-name-replacement"))) {
            harness.api.merchantCatalogItems = listOfNotNull(currentSource, unavailable)
            val reviewed = requireNotNull(harness.vm.reviewCatalog(MerchantDraftKind.Merge, source, target))
            assertEquals(source.publicId, reviewed.source?.publicId)
            assertEquals(8L, reviewed.source?.rowVersion)
            assertEquals(target, reviewed.target)
            assertTrue(reviewed.targetUnavailable)
            harness.vm.drafts.submit(reviewed.kind, source.publicId)
        }
        harness.api.merchantCatalogItems = listOf(currentTarget)
        val missingSource = requireNotNull(harness.vm.reviewCatalog(MerchantDraftKind.Merge, source, target))
        assertTrue(missingSource.sourceUnavailable)
        assertEquals(12L, missingSource.target?.rowVersion)
        assertEquals(0, harness.vm.uiState.value.changedRevision)
        assertEquals(null, harness.vm.uiState.value.editorCompletion)
        assertTrue(harness.api.merchantCatalogMergeRequests.isEmpty())
    }

    @Test fun anotherLedgerCannotReviewOrSubmitTheOriginalCatalogEdits() = merchantAlias {
        val harness = harness()
        val original = harness.vm.uiState.first { it.merchantCatalog.isNotEmpty() }.merchantCatalog.single()
        harness.vm.reviewCatalog(MerchantDraftKind.Rename, original)
        harness.session.switchLedgerForFixture("another-ledger", "另一账本")
        harness.vm.drafts.state.first { !it.canModify }
        harness.api.merchantCatalogItems = listOf(merchantCatalogDto(original.publicId, "另一账本同名对象", 20))
        harness.vm.renameMerchantCatalog(original, "不能带入新账本的原稿")
        harness.vm.reviewCatalog(MerchantDraftKind.Merge, original, original.copy(publicId = "target"))
        harness.vm.mergeMerchantCatalog(original, original.copy(publicId = "target"), MerchantCatalogAliasPolicy.None)
        advanceUntilIdle()
        assertEquals(listOf(original), harness.vm.uiState.value.merchantCatalog)
        assertTrue(harness.vm.drafts.state.value.drafts.isEmpty())
        assertEquals(0, harness.vm.uiState.value.changedRevision)
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
        assertTrue(harness.api.merchantCatalogMergeRequests.isEmpty())
    }

    @Test fun acceptingDerivedMergeKeepsAnIndependentlyEditedParentAndAnotherMerchantDraft() = merchantAlias {
        val harness = harness { merchantCatalogItems = listOf(merchantCatalogDto("source", "原商家", 7), merchantCatalogDto("target", "目标商家", 11)) }
        val state = harness.vm.uiState.first { it.drafts.ready && it.merchantCatalog.size == 2 }
        val source = state.merchantCatalog.single { it.publicId == "source" }
        val target = state.merchantCatalog.single { it.publicId == "target" }
        val drafts = harness.vm.drafts
        drafts.begin(MerchantDraftKind.Rename, source)
        val parent = requireNotNull(drafts.state.value.draft(MerchantDraftKind.Rename, source.publicId))
        drafts.begin(MerchantDraftKind.Merge, source, target)
        drafts.begin(MerchantDraftKind.Rename, target)
        val other = requireNotNull(drafts.state.value.draft(MerchantDraftKind.Rename, target.publicId))
        drafts.change(other.copy(displayName = "  另一商家的未提交名字  "))
        drafts.change(parent.copy(displayName = "  返回后重新填写的名字  "))
        val independent = requireNotNull(drafts.state.value.draft(MerchantDraftKind.Rename, source.publicId))
        assertTrue(independent.key != parent.key)
        val merge = requireNotNull(drafts.state.value.draft(MerchantDraftKind.Merge, source.publicId))
        assertEquals(parent.key, merge.parentRenameKey)
        drafts.change(merge.copy(aliasPolicy = MerchantCatalogAliasPolicy.None))
        drafts.submit(MerchantDraftKind.Merge, source.publicId)
        val accepted = requireNotNull(drafts.state.first { !it.busy }.draft(MerchantDraftKind.Merge, source.publicId))
        assertEquals("accepted", accepted.phase)
        drafts.acknowledge(accepted.kind, accepted.key)
        val remaining = drafts.state.first { !it.busy }.drafts
        assertEquals(setOf(source.publicId, target.publicId), remaining.map { it.source?.publicId }.toSet())
        assertEquals("  返回后重新填写的名字  ", remaining.single { it.source?.publicId == source.publicId }.displayName)
        assertEquals("  另一商家的未提交名字  ", remaining.single { it.source?.publicId == target.publicId }.displayName)
        assertTrue(harness.api.merchantCatalogUpdateRequests.isEmpty())
        assertEquals(1, harness.api.merchantCatalogMergeRequests.size)
    }

    private suspend fun MerchantAliasViewModel.publishCatalog(kind: MerchantDraftKind, source: MerchantCatalog,
        change: (MerchantDraft) -> MerchantDraft = { it }) {
        drafts.state.first { it.ready }
        drafts.begin(kind, source)
        val original = drafts.state.value.draft(kind, source.publicId) ?: return
        drafts.change(change(original))
        drafts.submit(kind, source.publicId)
        val settled = drafts.state.first { !it.busy }.draft(kind, source.publicId)
        if (settled?.phase == "accepted") {
            drafts.acknowledge(kind, settled.key)
            drafts.state.first { !it.busy }
        }
    }

    private suspend fun MerchantAliasViewModel.renameMerchantCatalog(source: MerchantCatalog, name: String) =
        publishCatalog(MerchantDraftKind.Rename, source) { it.copy(displayName = name) }
    private suspend fun MerchantAliasViewModel.toggleMerchantCatalog(source: MerchantCatalog) = publishCatalog(MerchantDraftKind.Visibility, source)
    private suspend fun MerchantAliasViewModel.deleteMerchantCatalog(source: MerchantCatalog) = publishCatalog(MerchantDraftKind.Delete, source)
    private suspend fun MerchantAliasViewModel.mergeMerchantCatalog(source: MerchantCatalog, target: MerchantCatalog, policy: MerchantCatalogAliasPolicy) =
        publishCatalog(MerchantDraftKind.Merge, source) { it.copy(target = target, aliasPolicy = policy) }

    private suspend fun MerchantAliasViewModel.reviewCatalog(kind: MerchantDraftKind, source: MerchantCatalog, target: MerchantCatalog? = null): MerchantDraft? {
        drafts.state.first { it.ready }
        drafts.begin(kind, source)
        val original = drafts.state.value.draft(kind, source.publicId) ?: return null
        if (original.target == null && target != null) drafts.change(original.copy(target = target, aliasPolicy = MerchantCatalogAliasPolicy.None))
        drafts.review(kind, source.publicId)
        return drafts.state.first { !it.busy }.draft(kind, source.publicId)
    }

    private fun harness(
        role: String = "owner",
        configureApi: FakeApiService.() -> Unit = {},
    ): Harness {
        val settingsStore = FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                PersistedLedgerIdentity(
                    accountName = "我",
                    ledgerId = "owner",
                    ledgerName = "我的小票夹",
                    deviceName = "Pixel",
                    role = role,
                    boundAt = "2026-05-01T00:00:00Z",
                )
            )
        }
        val tokenStore = ledgerSessionFixture(
            ledgerId = "owner",
            ledgerName = "我的小票夹",
            role = role,
        )
        val api = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0).apply(configureApi)
        val apiFactory = FakeApiServiceFactory(api)
        val merchantRepository = MerchantRepository(
            draftStore = com.ticketbox.data.repository.fakeMerchantDraftStore(),
            binding = testServerSessionBinding(
                apiClient = apiFactory,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
        )
        val expenseRepository = com.ticketbox.data.repository.expenseRepositoryFixture(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = apiFactory,
                settingsStore = settingsStore,
                tokenStore = tokenStore,
            ),
        )
        val vm = MerchantAliasViewModel(
            merchantRepository = merchantRepository,
            repository = expenseRepository,
        )
        activeViewModels += vm
        return Harness(api = api, vm = vm, session = tokenStore)
    }

    private data class Harness(
        val api: FakeApiService,
        val vm: MerchantAliasViewModel,
        val session: TestSessionFixture,
    )

    private companion object {
        fun merchantCatalogDto(
            publicId: String,
            displayName: String,
            rowVersion: Long,
        ): MerchantCatalogDto = MerchantCatalogDto(
            publicId = publicId,
            displayName = displayName,
            merchantKey = displayName,
            status = "active",
            mergedIntoPublicId = null,
            usageCount = 0,
            createdAt = "2026-05-13T00:00:00Z",
            updatedAt = "2026-05-13T00:05:00Z",
            rowVersion = rowVersion,
            deletedAt = null,
        )
    }
}
