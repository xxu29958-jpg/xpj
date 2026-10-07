package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.fragment.app.FragmentActivity
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.TagDetailDto
import com.ticketbox.data.remote.dto.TagListItemDto
import com.ticketbox.data.remote.dto.TagManagementListDto
import com.ticketbox.data.remote.dto.TagMergeRequest
import com.ticketbox.data.remote.dto.TagMutationDto
import com.ticketbox.data.remote.dto.TagRenameRequest
import com.ticketbox.data.repository.ServerBindingRepository
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.viewmodel.AppViewModel
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.CopyOnWriteArrayList

/** Real App authentication gates, navigation, task drafts and repository admission; controlled remote IO. */
class AppTaskContinuationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val source = TagListItemDto("trip", "出差", 5, 3)
    private val target = TagListItemDto("monthly", "月度整理", 3, 7)
    private val renames = CopyOnWriteArrayList<TagRenameRequest>()
    private val merges = CopyOnWriteArrayList<TagMergeRequest>()
    @Volatile private var reject = true
    @Volatile private var collide = false
    @Volatile private var renamed = false
    @Volatile private var merged = false
    @Volatile private var rejectReadAfterRename = false
    private var unusedSource = false
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun debts(lens: String?) = com.ticketbox.data.remote.dto.DebtListResponseDto(emptyList(), "CNY")
            override suspend fun listManagedTags(): TagManagementListDto {
                if (renamed && rejectReadAfterRename) throw unavailable()
                return TagManagementListDto(
                    if (merged) listOf(target) else listOf(
                        if (renamed) source.copy(name = "九月出差", rowVersion = 4)
                        else source.copy(usageCount = if (unusedSource) 0 else source.usageCount),
                        target,
                    ),
                )
            }

            override suspend fun renameTag(publicId: String, request: TagRenameRequest): TagDetailDto {
                assertEquals(source.publicId, publicId)
                renames += request
                if (collide) throw HttpException(Response.error<Any>(409,
                    """{"error":"tag_conflict","message":"已有同名标签，可改为合并。","conflict_tag_public_id":"monthly","conflict_tag_row_version":9}"""
                        .toResponseBody("application/json".toMediaType())))
                if (reject) throw unavailable()
                renamed = true
                return TagDetailDto(publicId, request.name, 4)
            }

            override suspend fun mergeTag(publicId: String, request: TagMergeRequest): TagMutationDto {
                assertEquals(source.publicId, publicId)
                merges += request
                if (reject) throw unavailable()
                merged = true
                return TagMutationDto("merge-trip", "merge", publicId, 4, target.publicId, 8, 5)
            }
        }
    }
    private var sessionReady = true
    private var verification = CompletableDeferred<Result<Unit>?>()
    private val appViewModel by lazy {
        AppViewModel(
            object : ServerBindingRepository by harness.screenFactory.repositories.repository {
                override fun isBusinessSessionReady() = sessionReady
                override fun hasPendingBinding() = false
                override suspend fun reconcileActiveSession() = verification.await()
            },
            object : TicketboxSettingsStore by harness.fixture.settingsStore {
                override fun appThemeModeKey() = if (InstrumentationRegistry.getArguments().getString("visualMode") == "large")
                    AppThemeMode.Midnight.storageKey else AppThemeMode.Default.storageKey
                override fun currencyCodeKey() = CurrencyCode.Default.storageKey
                override fun observeCurrencyCodeKey() = flowOf(currencyCodeKey())
                override fun requiresUnlock() = false
            },
            requireLocalUnlock = false,
        )
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun failedRenameKeepsTheOriginalInputAndCanContinue() {
        val restoration = showTags()
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        compose.waitUntil(5_000) { renames.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()
        captureReferenceLibraryStep(compose, context, "rename-error")
        assertEquals(false, renamed)

        restoration.emulateSavedInstanceStateRestore()
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()

        reject = false
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_renamed, "九月出差"))
        compose.onNodeWithText(context.getString(R.string.tag_management_rename_dialog_title)).assertDoesNotExist()
        compose.onNodeWithText("九月出差").assertIsDisplayed()
        assertEquals(listOf(TagRenameRequest(3, "九月出差"), TagRenameRequest(3, "九月出差")), renames)
    }

    @Test fun failedMergeKeepsTheChosenTargetAndOriginalVersions() {
        val restoration = showTags()
        openSourceAction(R.string.tag_management_card_action_merge)
        val targetLabel = context.getString(R.string.tag_management_merge_dialog_target_with_count, target.name, 3)
        clickText(targetLabel)
        clickText(context.getString(R.string.tag_management_merge_dialog_confirm))
        compose.waitUntil(5_000) { merges.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.tag_management_merge_dialog_title)).assertIsDisplayed()
        compose.onNodeWithText(targetLabel).assertIsDisplayed()
        compose.onNodeWithText("暂时无法保存，请保留当前填写后重试。").assertIsDisplayed()
        captureReferenceLibraryStep(compose, context, "merge-error")
        assertEquals(false, merged)

        restoration.emulateSavedInstanceStateRestore()
        compose.onNodeWithText(targetLabel).assertIsSelected()

        reject = false
        clickText(context.getString(R.string.tag_management_merge_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_merged, source.name, target.name))
        compose.onNodeWithText(context.getString(R.string.tag_management_merge_dialog_title)).assertDoesNotExist()
        compose.onNodeWithText(source.name).assertDoesNotExist()
        assertEquals(listOf(TagMergeRequest(3, target.publicId, 7), TagMergeRequest(3, target.publicId, 7)), merges)
    }

    @Test fun renameCollisionOpensOnlyTheExplicitMergeWithFreshTargetVersion() {
        collide = true
        showTags()
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement(target.name)
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_merge_dialog_title))
        compose.onNodeWithText(context.getString(R.string.tag_management_rename_dialog_title)).assertDoesNotExist()
        assertEquals(emptyList<TagMergeRequest>(), merges)

        reject = false
        clickText(context.getString(R.string.tag_management_merge_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_merged, source.name, target.name))
        assertEquals(listOf(TagMergeRequest(3, target.publicId, 9)), merges)
    }

    @Test fun acceptedRenameCanRecoverItsReadWithoutRepeatingTheWrite() {
        showTags()
        reject = false
        rejectReadAfterRename = true
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_reload_button))
        compose.onNodeWithText(context.getString(R.string.tag_management_renamed, "九月出差")).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.tag_management_rename_dialog_title)).assertDoesNotExist()
        compose.onNodeWithText(source.name).assertDoesNotExist()
        compose.onAllNodesWithContentDescription(context.getString(R.string.tag_management_actions_content_description))
            .assertCountEquals(0)

        rejectReadAfterRename = false
        clickText(context.getString(R.string.tag_management_reload_button))
        waitForText("九月出差")
        compose.onNodeWithText("九月出差").assertIsDisplayed()
        assertEquals(listOf(TagRenameRequest(3, "九月出差")), renames)
    }

    @Test fun unusedFilterKeepsUsedMergeTargetsAndReturnsToTheSameSelection() {
        unusedSource = true
        showTags()
        compose.onNode(hasText("未使用") and hasClickAction()).performTouchInput { click() }
        compose.onNodeWithText(target.name).assertDoesNotExist()
        openSourceAction(R.string.tag_management_card_action_merge)
        clickText(context.getString(R.string.tag_management_merge_dialog_target_with_count, target.name, 3))
        clickText(context.getString(R.string.tag_management_merge_dialog_confirm))
        compose.waitUntil(5_000) { merges.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.tag_management_merge_dialog_title)).assertIsDisplayed()
        reject = false
        clickText(context.getString(R.string.tag_management_merge_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_merged, source.name, target.name))
        compose.onNode(hasText("未使用") and hasClickAction()).assertIsSelected()
        compose.onNodeWithText(source.name).assertDoesNotExist()
        compose.onNodeWithText(target.name).assertDoesNotExist()
        assertEquals(listOf(true, true), merges.map { it.requireOrphan })
    }

    @Test fun roleLossKeepsTheDraftAndRoleRecoveryResumesTheOriginalRename() {
        showTags()
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        compose.runOnIdle { harness.fixture.role("viewer") }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.tag_management_rename_dialog_confirm)).assertIsNotEnabled()
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()
        captureReferenceLibraryStep(compose, context, "rename-readonly")
        assertEquals(emptyList<TagRenameRequest>(), renames)

        compose.runOnIdle { harness.fixture.role("owner") }
        reject = false
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_renamed, "九月出差"))
        assertEquals(listOf(TagRenameRequest(3, "九月出差")), renames)
    }

    @Test fun changedBindingCannotSubmitTheOriginalDraftAsTheNewSession() {
        val restoration = showTags()
        val repository = harness.screenFactory.tagRepository
        val originalBinding = requireNotNull(repository.captureBinding())
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        compose.runOnIdle { harness.fixture.renewBinding() }
        restoration.emulateSavedInstanceStateRestore()
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.tag_management_rename_dialog_confirm)).assertIsNotEnabled()
        val bypassingUi = runBlocking {
            repository.renameTag(originalBinding, ManagedTag(source.publicId, source.name, source.usageCount, source.rowVersion), "九月出差")
        }
        assertEquals(true, bypassingUi.isFailure)
        assertEquals(emptyList<TagRenameRequest>(), renames)
    }

    @Test fun sessionVerificationFailureAndRetryReturnToTheOriginalTagTask() {
        val restoration = showTags()
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        compose.runOnIdle { sessionReady = false; appViewModel.refreshBindingState() }
        waitForText(context.getString(R.string.app_session_verification_title))
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertDoesNotExist()
        compose.runOnIdle { verification.complete(Result.failure(unavailable())) }
        waitForText(context.getString(R.string.app_session_verification_retry))
        captureReferenceLibraryStep(compose, context, "session-verification-failed")
        restoration.emulateSavedInstanceStateRestore()
        compose.runOnIdle { verification = CompletableDeferred() }
        clickText(context.getString(R.string.app_session_verification_retry))
        compose.runOnIdle { sessionReady = true; verification.complete(Result.success(Unit)) }
        captureReferenceLibraryStep(compose, context, "session-verification-returned")
        waitForText("九月出差")
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()
        assertEquals(emptyList<TagRenameRequest>(), renames)
        captureReferenceLibraryStep(compose, context, "session-verification-resumed")
        reject = false
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_renamed, "九月出差"))
        assertEquals(listOf(TagRenameRequest(3, "九月出差")), renames)
    }

    @Test fun verificationForAnotherAccountCannotExposeOrConsumeTheOriginalTask() {
        showTags()
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        compose.runOnIdle { sessionReady = false; appViewModel.refreshBindingState() }
        waitForText(context.getString(R.string.app_session_verification_title))
        compose.runOnIdle {
            harness.fixture.switchAccount()
            sessionReady = true
            verification.complete(Result.success(Unit))
        }
        waitForText(context.getString(R.string.nav_domain_inbox))
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertDoesNotExist()
        assertEquals(emptyList<TagRenameRequest>(), renames)
        compose.runOnIdle { harness.fixture.restoreOriginalSession() }
        waitForText("九月出差")
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()
        reject = false
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_renamed, "九月出差"))
        assertEquals(listOf(TagRenameRequest(3, "九月出差")), renames)
    }

    @Test fun manualEntryKeepsItsInputAcrossTheSameVerificationGate() {
        val restoration = showApp()
        waitForText(context.getString(R.string.nav_domain_transactions))
        clickText(context.getString(R.string.nav_domain_transactions))
        waitForText(context.getString(R.string.ledger_header_add_button))
        clickText(context.getString(R.string.ledger_header_add_button))
        waitForText(context.getString(R.string.ledger_manual_sheet_title))
        waitForText(context.getString(R.string.ledger_manual_merchant_label))
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.expense_edit_amount_field_label)))
            .performScrollTo().performTextReplacement("123.45")
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.ledger_manual_merchant_label)))
            .performScrollTo().performTextReplacement("会话恢复后的原商家")
        captureReferenceLibraryStep(compose, context, "manual-entry-before-verification")
        compose.runOnIdle { sessionReady = false; appViewModel.refreshBindingState() }
        waitForText(context.getString(R.string.app_session_verification_title))
        restoration.emulateSavedInstanceStateRestore()
        compose.runOnIdle { sessionReady = true; verification.complete(Result.success(Unit)) }
        waitForText(context.getString(R.string.ledger_manual_sheet_title))
        waitForText(context.getString(R.string.ledger_manual_merchant_label))
        captureReferenceLibraryStep(compose, context, "manual-entry-returned")
        compose.onNode(hasSetTextAction() and hasText("123.45")).performScrollTo().assertIsDisplayed()
        compose.onNode(hasSetTextAction() and hasText("会话恢复后的原商家")).performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<Map<String, String?>>(), harness.fixture.stored())
        captureReferenceLibraryStep(compose, context, "manual-entry-resumed")
        clickText(context.getString(R.string.ledger_manual_save_button))
        compose.waitUntil(5_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        val payload = org.json.JSONObject(requireNotNull(original["payload"]))
        assertEquals("123.45", payload.getString("original_amount"))
        assertEquals("CNY", payload.getString("original_currency"))
        assertEquals("会话恢复后的原商家", payload.getString("merchant"))
        assertEquals("pending", original["status"])
        assertEquals(emptyList<TagRenameRequest>(), renames)
    }

    private fun showApp(): StateRestorationTester {
        val restoration = StateRestorationTester(compose)
        val dependencies = compose.runOnIdle { TicketboxAppDependencies(
            repositories = harness.screenFactory.repositories,
            viewModelFactories = TicketboxAppViewModelFactories(
                appViewModelFactory = viewModelFactory { initializer { appViewModel } },
                mainScreenFactories = harness.screenFactory.viewModelFactories,
            ),
            // This journey starts unlocked and does not invoke biometric APIs.
            biometricAuthManager = BiometricAuthManager(FragmentActivity()),
        ) }
        restoration.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                ReferenceLibraryTestTheme { TicketboxApp(dependencies) }
            }
        }
        return restoration
    }

    private fun showTags(): StateRestorationTester {
        val restoration = showApp()
        waitForText(context.getString(R.string.nav_domain_transactions))
        clickText(context.getString(R.string.nav_domain_transactions))
        waitForText(context.getString(R.string.ledger_inline_filter))
        clickText(context.getString(R.string.ledger_inline_filter))
        compose.onNodeWithText(context.getString(R.string.transactions_library_title))
            .performScrollTo().performTouchInput { click() }
        waitForText(context.getString(R.string.transactions_library_tags_title))
        compose.onNodeWithText(context.getString(R.string.transactions_library_tags_title))
            .performScrollTo().performTouchInput { click() }
        waitForText(source.name)
        captureReferenceLibraryStep(compose, context, "tags")
        return restoration
    }

    private fun openSourceAction(label: Int) {
        compose.onAllNodesWithContentDescription(context.getString(R.string.tag_management_actions_content_description))
            .onFirst().performScrollTo().performTouchInput { click() }
        clickText(context.getString(label))
    }

    private fun clickText(text: String) = compose.onNodeWithText(text).performTouchInput { click() }

    private fun waitForText(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }

    private fun unavailable() = HttpException(Response.error<Any>(503,
        """{"error":"service_unavailable","message":"暂时无法保存，请保留当前填写后重试。"}"""
            .toResponseBody("application/json".toMediaType())))
}
