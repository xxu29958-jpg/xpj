package com.ticketbox.data.repository

import android.os.Bundle
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.SAVED_STATE_REGISTRY_OWNER_KEY
import androidx.lifecycle.VIEW_MODEL_STORE_OWNER_KEY
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.MutableCreationExtras
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitSettlementPreviewDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.SplitAgreementSection
import com.ticketbox.ui.screens.SplitAgreementDetailPanel
import com.ticketbox.ui.screens.SplitAgreementPanel
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SplitAgreementViewModel
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.splitAgreementViewModelFactory
import java.net.ConnectException
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
    private val service = object : ApiService by network.service {
        override suspend fun splitAgreement(publicId: String, newShareAmountCents: Long?): BillSplitAgreementDto {
            check(publicId in setOf(original.publicId, returned.publicId))
            if (failReads) throw ConnectException("Synthetic disconnected agreement read")
            if (missingReturn && publicId == returned.publicId) {
                throw HttpException(Response.error<Any>(404, """{"error":"debt_not_found"}""".toResponseBody()))
            }
            return BillSplitAgreementDto("agreement-invitation", "CNY", 4000, 2000, original, returned, true,
                3000, 0, 1000, 0, -1000,
                preview = BillSplitSettlementPreviewDto(newShareAmountCents ?: 2000, -1000, -1000, true))
        }
    }
    private val fixture = DebtAdjustmentConnectedFixture(context, service)
    private val model = mutableStateOf<SplitAgreementViewModel?>(null)
    private var owner: IncomeDraftStateOwner? = null

    @After fun close() {
        compose.runOnIdle { owner?.viewModelStore?.clear(); model.value = null }
        compose.waitForIdle()
        fixture.close()
    }

    @Test fun oldSystemSnapshotCannotDuplicateTheOriginalRoomSubmission() {
        install(null, original.publicId)
        showForm()
        edit("12.00", "-3.00", "双方明确返还三元")
        val saved = stop()
        failReads = true
        install(saved, original.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.fromCache == true && model.value?.state?.value?.loading == false }
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("-3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("双方明确返还三元").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_propose)).performScrollTo().assertIsNotEnabled()
        assertTrue(fixture.stored().isEmpty())
        failReads = false
        compose.onNodeWithText(context.getString(R.string.split_agreement_refresh)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        assertFalse(requireNotNull(model.value).state.value.confirmed)
        compose.onNode(isToggleable()).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.split_agreement_propose)).performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && model.value?.state?.value?.submitting == false }
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
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("-3.00").performScrollTo().assertIsDisplayed()
        assertFalse(requireNotNull(model.value).state.value.confirmed)
        compose.onNodeWithText(context.getString(R.string.split_agreement_propose)).performScrollTo().assertIsNotEnabled()
        assertTrue(requireNotNull(model.value).state.value.busy)
        assertEquals(1, fixture.scheduleCalls)
    }

    @Test fun bothLegsKeepTheirOwnRawFormThroughAndroidRegistryRestore() {
        install(null, original.publicId)
        showForm()
        edit("12.00", "-3.00", "原往来尚未发出")
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_return_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == returned.publicId &&
            model.value?.state?.value?.previewReady == true }
        edit("13.00", "-2.00", "返还入口尚未发出")
        val saved = stop()
        install(saved, returned.publicId)
        compose.waitUntil(10_000) { model.value?.state?.value?.previewReady == true }
        compose.onNodeWithText("13.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("-2.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("返还入口尚未发出").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.split_agreement_open_original_debt)).performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.state?.value?.task?.debtPublicId == original.publicId &&
            model.value?.state?.value?.previewReady == true }
        compose.onNodeWithText("12.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("-3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("原往来尚未发出").performScrollTo().assertIsDisplayed()
        assertTrue(fixture.stored().isEmpty())
        assertEquals(0, fixture.scheduleCalls)
    }

    @Test fun viewerCannotEditAnAgreementThroughTheActualReadOnlyDetailPanel() {
        install(null, original.publicId)
        // The retained model saw writer access; the current detail now belongs to a viewer.
        fixture.session = fixture.session.copy(identity = fixture.session.identity.copy(role = "viewer"))
        showForm(readOnly = true)
        compose.waitUntil(10_000) { model.value?.state?.value?.agreement != null && model.value?.state?.value?.loading == false }
        compose.onNodeWithText("20.00").performScrollTo().assertIsDisplayed().assertIsNotEnabled()
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
        compose.onNodeWithText("-3.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("尚未发出的原稿").performScrollTo().assertIsDisplayed()
        assertTrue(fixture.stored().isEmpty())
    }

    private fun showForm(readOnly: Boolean = false) = compose.setContent {
        val current = model.value ?: return@setContent
        val state by current.state.collectAsStateWithLifecycle()
        TicketboxTheme(skin = AppSkin.Paper) {
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
        listOf(share, settlement, reason).forEachIndexed { index, value ->
            compose.onAllNodes(hasSetTextAction())[index].performScrollTo().performTextReplacement(value)
            closeSoftKeyboard()
            compose.waitForIdle()
        }
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

    private fun stop(): Bundle = compose.runOnIdle {
        requireNotNull(owner).save().also { owner?.viewModelStore?.clear(); model.value = null }
    }
}
