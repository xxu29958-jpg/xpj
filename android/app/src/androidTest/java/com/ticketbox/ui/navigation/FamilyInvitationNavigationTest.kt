package com.ticketbox.ui.navigation

import android.content.Context
import android.util.Log
import androidx.compose.ui.test.ComposeTimeoutException
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.printToLog
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.isDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onLast
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.InvitationCreateRequestDto
import com.ticketbox.data.remote.dto.InvitationCreateResponseDto
import com.ticketbox.data.remote.dto.InvitationListResponseDto
import com.ticketbox.data.remote.dto.InvitationSummaryDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.settings.FamilyMembersScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.FamilyMembersViewModel
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The real invitation task sends the chosen role, note and expiry, then reads the original revoke outcome. */
class FamilyInvitationNavigationTest {
    @get:Rule val compose = createComposeRule()
    @get:Rule val keyboard = RealKeyboard()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val requests = CopyOnWriteArrayList<InvitationCreateRequestDto>()
    private val revokes = CopyOnWriteArrayList<String>()
    @Volatile private var rejectCreate = true
    @Volatile private var rejectRead = true
    @Volatile private var invitation = InvitationSummaryDto("original-invitation", "correction-ledger", "viewer", "家人",
        createdAt = "2026-10-15T00:00:00Z", expiresAt = "2099-10-29T00:00:00Z")
    private val harness = FactEntryNavigationHarness(context) { delegate -> object : ApiService by delegate {
        override suspend fun ledgerMembers(ledgerId: String) = LedgerMemberListResponseDto(listOf(
            LedgerMemberDto(1, 1, "self", "自己", "owner", null, null, true)))
        override suspend fun ledgerAudit(ledgerId: String, limit: Int) = LedgerAuditListResponseDto(emptyList())
        override suspend fun createInvitation(ledgerId: String, request: InvitationCreateRequestDto): InvitationCreateResponseDto {
            assertEquals("correction-ledger", ledgerId)
            requests += request
            if (rejectCreate) throw IOException("controlled invitation failure")
            return InvitationCreateResponseDto("test-only-invitation", null, invitation)
        }
        override suspend fun listInvitations(ledgerId: String): InvitationListResponseDto {
            assertEquals("correction-ledger", ledgerId)
            if (rejectRead) throw IOException("controlled list failure")
            return InvitationListResponseDto(listOf(invitation))
        }
        override suspend fun revokeInvitation(ledgerId: String, publicId: String): InvitationSummaryDto {
            assertEquals("correction-ledger", ledgerId)
            revokes += publicId
            invitation = invitation.copy(revokedAt = "2026-10-15T01:00:00Z")
            throw IOException("controlled lost revoke response")
        }
    } }
    private val model = FamilyMembersViewModel(harness.screenFactory.ledgerRepository)

    @After fun close() {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun chosenInviteAndUnknownRevokeKeepTheirOriginalScope() {
        harness.fixture.role(LEDGER_ROLE_OWNER)
        compose.setContent { if (mounted.value) TicketboxTheme(skin = AppSkin.Paper) {
            FamilyMembersScreen(model, "correction-ledger", LEDGER_ROLE_OWNER, {})
        } }
        compose.waitUntil(5_000) { model.uiState.value.members.isNotEmpty() }
        captureReferenceLibraryStep(compose, context, "family-members")
        compose.onNodeWithText("邀请家人").performClick()
        compose.onNodeWithText("邀请为只读").performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("家人")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performClick().performTextReplacement("14")
        keyboard.assertActionAboveKeyboard(compose, "生成家庭邀请", "family-invite-keyboard")
        compose.onNodeWithText("生成家庭邀请").performClick()
        compose.waitUntil(5_000) { requests.size == 1 && !model.uiState.value.inviteCreating }
        compose.onAllNodes(hasSetTextAction())[0].assertTextContains("家人")
        compose.onAllNodes(hasSetTextAction())[1].assertTextContains("14")
        keyboard.dismissAndWait(compose)
        rejectCreate = false
        compose.onNodeWithText("生成家庭邀请").performClick()
        compose.waitUntil(5_000) { model.uiState.value.createdInvite != null }
        assertEquals(List(2) { InvitationCreateRequestDto("viewer", "家人", 14) }, requests.toList())
        val copy = compose.onNodeWithText("复制")
        // The created-invite content resizes the sheet after the model publishes its result.
        compose.waitUntil(5_000) { copy.isDisplayed() }
        copy.assertIsDisplayed()
        captureReferenceLibraryStep(compose, context, "family-invitation-created")
        compose.onNodeWithText("查看已发出的邀请与撤销").performScrollTo().performClick()
        compose.waitUntil(5_000) { model.uiState.value.invitationsError != null }
        assertEquals(false, model.uiState.value.invitationsFresh)
        rejectRead = false
        compose.onNodeWithText("重新读取已发邀请").performScrollTo().performClick()
        compose.waitUntil(5_000) { model.uiState.value.invitationsFresh }
        val original = compose.runOnIdle { model.uiState.value.invitations.single() }
        compose.runOnIdle { harness.fixture.renewBinding(); model.revokeInvitation(original) }
        compose.waitUntil(5_000) { model.uiState.value.invitationsError != null }
        assertEquals(emptyList<String>(), revokes.toList())
        compose.onNodeWithText("重新读取已发邀请").performScrollTo().performClick()
        compose.waitUntil(5_000) { model.uiState.value.invitationsFresh }
        compose.onNodeWithContentDescription("撤销邀请：家人").performScrollTo().performClick()
        compose.onAllNodesWithText("撤销邀请").onLast().performClick()
        compose.waitUntil(5_000) { revokes.size == 1 && model.uiState.value.revokingInvitationId == null }
        assertEquals(false, model.uiState.value.invitationsFresh)
        compose.onNodeWithText("重新读取已发邀请").performScrollTo().performClick()
        compose.waitUntil(5_000) { model.uiState.value.invitationsFresh && model.uiState.value.invitations.single().revokedAt != null }
        // Removing the one-time invite replaces the sheet body and resizes its native window.
        // Scroll only after that layout settles; waiting after an old-bounds scroll cannot reposition it.
        compose.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(500, 3_000)
        val revoked = compose.onNodeWithText("只读 · 已撤销")
        awaitRevokedVisible(revoked)
        revoked.assertIsDisplayed()
        compose.onNodeWithText("复制").assertDoesNotExist()
        assertEquals(listOf(original.publicId), revokes.toList())
        captureReferenceLibraryStep(compose, context, "family-invitation-revoked")
    }

    private fun awaitRevokedVisible(revoked: SemanticsNodeInteraction) {
        try {
            compose.waitUntil(5_000) { revoked.performScrollTo().isDisplayed() }
        } catch (failure: ComposeTimeoutException) {
            // Capture before teardown or another scroll changes the failed layout.
            try {
                val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
                saveConsumerArtPreview("family-revoked-timeout", requireNotNull(automation.takeScreenshot()))
                Log.e("FamilyRevokeLayout", "fresh=${model.uiState.value.invitationsFresh}; revoked=" +
                    model.uiState.value.invitations.singleOrNull()?.revokedAt)
                compose.onAllNodes(isRoot(), useUnmergedTree = true).printToLog("FamilyRevokeLayout")
            } catch (captureFailure: Exception) {
                failure.addSuppressed(captureFailure)
            }
            throw failure
        }
    }
}
