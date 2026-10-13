package com.ticketbox.data.repository

import android.os.Bundle
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.SAVED_STATE_REGISTRY_OWNER_KEY
import androidx.lifecycle.VIEW_MODEL_STORE_OWNER_KEY
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.MutableCreationExtras
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeProposalDto
import com.ticketbox.data.remote.dto.BillSplitSettlementPreviewDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.SplitAgreementSection
import com.ticketbox.ui.screens.SplitAgreementDetailPanel
import com.ticketbox.ui.screens.SplitAgreementPanel
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.viewmodel.SplitAgreementViewModel
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.splitAgreementViewModelFactory
import java.net.ConnectException
import kotlinx.coroutines.Job
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual form and saved-state factory with disk Room; only session and server transport are synthetic. */
class SplitAgreementDraftConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()
    private val network = DebtAdjustmentConnectedNetwork()
    private val original = network.current.copy(publicId = "agreement-original", counterpartyType = "member",
        sourceType = "bill_split", sourceId = "agreement-invitation", principalAmountCents = 4000,
        remainingAmountCents = 0, paidAmountCents = 3000, status = "cleared", rowVersion = 7)
    private val returned = original.copy(publicId = "agreement-return", sourceType = "bill_split_return",
        direction = "owed_to_me", principalAmountCents = 1000, remainingAmountCents = 1000,
        paidAmountCents = 0, status = "open", rowVersion = 8)
    private var failReads = false
    private var missingReturn = false
    private var pendingProposal: BillSplitChangeProposalDto? = null
    private val service = object : ApiService by network.service {
        override suspend fun splitAgreement(publicId: String, newShareAmountCents: Long?): BillSplitAgreementDto {
            check(publicId in setOf(original.publicId, returned.publicId))
            if (failReads) throw ConnectException("Synthetic disconnected agreement read")
            if (missingReturn && publicId == returned.publicId) {
                throw HttpException(Response.error<Any>(404, """{"error":"debt_not_found"}""".toResponseBody()))
            }
            return BillSplitAgreementDto("agreement-invitation", "CNY", 4000, 2000, original, returned, true,
                3000, 0, 1000, 0, -1000,
                pendingProposal = pendingProposal,
                preview = BillSplitSettlementPreviewDto(newShareAmountCents ?: 2000, -1000, -1000, true))
        }
    }
    private val fixture = DebtAdjustmentConnectedFixture(context, service)
    private val model = mutableStateOf<SplitAgreementViewModel?>(null)
    private var owner: IncomeDraftStateOwner? = null

    @After fun close() {
        if (model.value != null) stop()
        fixture.close()
    }

    @Test fun oldSystemSnapshotCannotDuplicateTheOriginalRoomSubmission() {
        install(null, original.publicId)
        showForm()
        edit("12.00", "-3.00", "双方明确返还三元")
        compose.onNodeWithText("12.00").performScrollTo()
        capture("split-agreement-edit")
        closeEditor()
        compose.onNodeWithText(context.getString(R.string.split_agreement_continue_draft)).performScrollTo().performClick()
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        val saved = stop()
        failReads = true
        install(saved, original.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.fromCache == true && model.value?.state?.value?.loading == false }
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_direction_return)).performScrollTo().assertIsSelected()
        assertEquals("-3.00", requireNotNull(model.value).state.value.settlementInput)
        compose.onNodeWithText("双方明确返还三元").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_propose)).assertIsNotEnabled()
        assertTrue(fixture.stored().isEmpty())
        failReads = false
        compose.onNodeWithText(context.getString(R.string.split_agreement_preview)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        assertFalse(requireNotNull(model.value).state.value.confirmed)
        compose.onNodeWithTag("split-agreement-preview").performScrollTo()
        capture("split-agreement-preview")
        compose.onNodeWithText(context.getString(R.string.split_agreement_confirmation)).performScrollTo().assertIsDisplayed()
        capture("split-agreement-confirm")
        compose.onNode(isToggleable()).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.split_agreement_propose)).performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && model.value?.state?.value?.submitting == false }
        capture("split-agreement-queued")
        val admitted = fixture.stored().single()
        val intent = requireNotNull(OutboxAdapterGraph().splitAgreementAdapter.fromJson(requireNotNull(admitted["payload"])))
        assertEquals(1200L, intent.create?.newShareAmountCents)
        assertEquals(-300L, intent.create?.settlementNetAmountCents)
        assertEquals(7L, intent.create?.expectedRowVersion)
        assertEquals(8L, intent.create?.expectedReturnRowVersion)
        stop()
        failReads = true
        install(saved, original.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.rows?.size == 1 && model.value?.state?.value?.fromCache == true }
        assertEquals(admitted, fixture.stored().single())
        compose.onNodeWithText(context.getString(R.string.split_agreement_continue_draft)).performScrollTo().performClick()
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_direction_return)).performScrollTo().assertIsSelected()
        assertFalse(requireNotNull(model.value).state.value.confirmed)
        compose.onNodeWithText(context.getString(R.string.split_agreement_propose)).assertIsNotEnabled()
        assertTrue(requireNotNull(model.value).state.value.busy)
        assertEquals(1, fixture.scheduleCalls)
    }

    @Test fun bothLegsKeepTheirOwnRawFormThroughAndroidRegistryRestore() {
        install(null, original.publicId)
        showForm()
        edit("12.00", "3.00", "原往来尚未发出")
        closeEditor()
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_return_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == returned.publicId &&
            model.value?.state?.value?.previewReady == true }
        edit("13.00", "-2.00", "返还入口尚未发出")
        val saved = stop()
        install(saved, returned.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        compose.onNodeWithText("13.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("2.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_direction_return)).performScrollTo().assertIsSelected()
        assertEquals("-2.00", requireNotNull(model.value).state.value.settlementInput)
        compose.onNodeWithText("返还入口尚未发出").performScrollTo().assertIsDisplayed()
        closeEditor()
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_original_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == original.publicId &&
            model.value?.state?.value?.previewReady == true }
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_direction_pay)).performScrollTo().assertIsSelected()
        assertEquals("3.00", requireNotNull(model.value).state.value.settlementInput)
        compose.onNodeWithText("原往来尚未发出").performScrollTo().assertIsDisplayed()
        assertTrue(fixture.stored().isEmpty())
        assertEquals(0, fixture.scheduleCalls)
        closeEditor()
        pendingProposal = BillSplitChangeProposalDto(publicId = "replacement-predecessor",
            originalDebtPublicId = original.publicId, returnDebtPublicId = returned.publicId,
            status = "pending", proposedByYou = false, shareBeforeAmountCents = 2000, newShareAmountCents = 1100,
            settlementBeforeNetAmountCents = -1000, settlementNetAmountCents = -400,
            originalPaidAmountCents = 3000, returnPaidAmountCents = 0, originalForgivenAmountCents = 1000,
            returnForgivenAmountCents = 0, originalDebtRowVersion = 7, returnDebtRowVersion = 8,
            reason = "对方的新提议", createdAt = original.createdAt, expiresAt = "2027-01-01T00:00:00Z")
        compose.onNodeWithText(context.getString(R.string.split_agreement_refresh)).performScrollTo().performClick()
        compose.waitUntil(10_000) {
            model.value?.state?.value?.agreement?.pendingProposal?.publicId == "replacement-predecessor"
        }
        compose.onNodeWithText(context.getString(R.string.split_agreement_replace)).performScrollTo().performClick()
        compose.onNodeWithText("原往来尚未发出").performScrollTo().assertIsDisplayed()
        closeEditor()
        compose.onNodeWithText(context.getString(R.string.split_agreement_cancel_replacement)).performScrollTo().performClick()
        assertEquals(null, requireNotNull(model.value).state.value.replacingProposalPublicId)
        assertTrue(fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.split_agreement_replace)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.split_agreement_preview)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        compose.onNode(isToggleable()).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.split_agreement_submit_replacement)).performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 }
        val replacement = requireNotNull(OutboxAdapterGraph().splitAgreementAdapter.fromJson(requireNotNull(fixture.stored().single()["payload"])))
        assertEquals("replacement-predecessor", replacement.create?.supersedesProposalPublicId)
        assertEquals(1200L, replacement.create?.newShareAmountCents)
        assertEquals(300L, replacement.create?.settlementNetAmountCents)
    }

    @Test fun viewerCannotEditAnAgreementThroughTheActualReadOnlyDetailPanel() {
        install(null, original.publicId)
        // The retained model saw writer access; the current detail now belongs to a viewer.
        fixture.session = fixture.session.copy(identity = fixture.session.identity.copy(role = "viewer"))
        showForm(readOnly = true)
        compose.waitUntil(10_000) { model.value?.state?.value?.agreement != null && model.value?.state?.value?.loading == false }
        compose.onNodeWithText(context.getString(R.string.split_agreement_share_facts, "¥40.00", "¥20.00"))
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_discussion_title))
            .performScrollTo().assertIsDisplayed().assertIsNotEnabled()
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(0)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun bothReadEntriesSurviveDiskReopenWithTheirTimeAndWithoutAnActionablePreview() {
        install(null, original.publicId)
        showForm()
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        val originalTime = requireNotNull(model.value).state.value.fetchedAt
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_return_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == returned.publicId &&
            model.value?.state?.value?.previewReady == true }
        val returnTime = requireNotNull(model.value).state.value.fetchedAt
        stop()
        failReads = true
        install(null, returned.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.fromCache == true }
        assertEquals(returnTime, requireNotNull(model.value).state.value.fetchedAt)
        assertFalse(requireNotNull(model.value).state.value.previewReady)
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_original_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == original.publicId &&
            model.value?.state?.value?.fromCache == true }
        val restored = requireNotNull(model.value).state.value
        assertEquals(originalTime, restored.fetchedAt)
        assertEquals(3000L, restored.agreement?.originalPaidAmountCents)
        assertEquals(1000L, restored.agreement?.originalForgivenAmountCents)
        assertEquals(-1000L, restored.agreement?.settlementNetAmountCents)
        assertFalse(restored.previewReady)
        assertFalse(restored.confirmed)
        assertFalse(restored.canPropose)
        assertTrue(fixture.stored().isEmpty())
    }

    @Test fun aMissingReturnDebtRetiresBothRoomSnapshotsWhileTheOriginalDraftSurvives() {
        install(null, original.publicId)
        showForm()
        edit("12.00", "-3.00", "尚未发出的原稿")
        closeEditor()
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_return_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == returned.publicId &&
            model.value?.state?.value?.previewReady == true }
        missingReturn = true
        compose.onNodeWithText(context.getString(R.string.split_agreement_refresh)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.agreement == null && model.value?.state?.value?.error != null }
        val saved = stop()
        failReads = true
        install(saved, original.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.loading == false && model.value?.state?.value?.error != null }
        assertEquals(null, requireNotNull(model.value).state.value.agreement)
        assertFalse(requireNotNull(model.value).state.value.previewReady)
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_direction_return)).performScrollTo().assertIsSelected()
        compose.onNodeWithText("尚未发出的原稿").performScrollTo().assertIsDisplayed()
        assertTrue(fixture.stored().isEmpty())
    }

    private fun showForm(readOnly: Boolean = false) = compose.setContent {
        val current = model.value ?: return@setContent
        val state by current.state.collectAsStateWithLifecycle()
        TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                if (readOnly) {
                    SplitAgreementDetailPanel(DebtDetailUiState(binding = state.task?.binding, debt = original.toDomain(),
                        canModify = false), MemberProposalUiState(), SplitAgreementPanel(current, {}), {})
                } else {
                    SplitAgreementSection(state, current) { id ->
                        current.load(requireNotNull(state.task).copy(debtPublicId = id), canModify = state.canModify)
                    }
                }
            }
        }
    }

    private fun edit(share: String, settlement: String, reason: String) {
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(0)
        compose.onNodeWithText(context.getString(R.string.split_agreement_discussion_title)).performScrollTo().performClick()
        val direction = if (settlement.startsWith("-")) R.string.split_agreement_direction_return else R.string.split_agreement_direction_pay
        compose.onNodeWithText(context.getString(direction)).performScrollTo().performClick()
        listOf(share, reason, settlement.removePrefix("-")).forEachIndexed { index, value ->
            compose.onAllNodes(hasSetTextAction())[index].performScrollTo().performTextReplacement(value)
            closeSoftKeyboard()
            compose.waitForIdle()
        }
    }

    private fun closeEditor() {
        compose.onNodeWithText(context.getString(R.string.debt_proposal_back_keep_draft)).performClick()
        compose.waitForIdle()
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val target = if (compose.onAllNodes(isDialog()).fetchSemanticsNodes().isNotEmpty()) {
            compose.onNode(isDialog())
        } else compose.onRoot()
        saveConsumerArtPreview(name, target.captureToImage().asAndroidBitmap())
    }

    private fun install(saved: Bundle?, publicId: String) {
        val actions = requireNotNull(fixture.reopen().debtRepository.splitAgreement)
        compose.runOnIdle {
            // Registry restoration consumes nested state; each recreation receives the same frozen snapshot.
            val restored = IncomeDraftStateOwner(saved?.deepCopy()).also { owner = it }
            val extras = MutableCreationExtras().apply {
                set(SAVED_STATE_REGISTRY_OWNER_KEY, restored)
                set(VIEW_MODEL_STORE_OWNER_KEY, restored)
            }
            val provider = ViewModelProvider(restored.viewModelStore, splitAgreementViewModelFactory(actions), extras)
            model.value = provider["split-agreement", SplitAgreementViewModel::class.java].also {
                    it.load(DebtTask(requireNotNull(fixture.session.toBoundSessionSnapshotOrNull()).logicalBinding, publicId),
                        canModify = com.ticketbox.domain.model.ledgerRoleCanModify(fixture.session.identity.role))
                }
        }
    }

    private fun stop(): Bundle {
        val (saved, completion) = compose.runOnIdle {
            val currentOwner = requireNotNull(owner)
            val current = requireNotNull(model.value)
            val completion = requireNotNull(current.viewModelScope.coroutineContext[Job])
            val saved = currentOwner.save()
            currentOwner.viewModelStore.clear()
            model.value = null
            saved to completion
        }
        // A process restart releases its old readers before opening the same disk database.
        // ViewModel.clear requests cancellation; wait for its Room work to actually finish.
        runBlocking { completion.join() }
        compose.waitForIdle()
        return saved
    }
}
