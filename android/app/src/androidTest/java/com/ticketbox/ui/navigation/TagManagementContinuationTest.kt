package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onFirst
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.TagDetailDto
import com.ticketbox.data.remote.dto.TagListItemDto
import com.ticketbox.data.remote.dto.TagManagementListDto
import com.ticketbox.data.remote.dto.TagMergeRequest
import com.ticketbox.data.remote.dto.TagMutationDto
import com.ticketbox.data.remote.dto.TagRenameRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.CopyOnWriteArrayList

/** Exercises the shipped library route, ViewModel and repository error decoding. */
class TagManagementContinuationTest {
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
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun listManagedTags(): TagManagementListDto {
                if (renamed && rejectReadAfterRename) throw unavailable()
                return TagManagementListDto(
                    if (merged) listOf(target) else listOf(
                        if (renamed) source.copy(name = "九月出差", rowVersion = 4) else source,
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

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun failedRenameKeepsTheOriginalInputAndCanContinue() {
        showTags()
        openSourceAction(R.string.tag_management_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText(source.name)).performTextReplacement("九月出差")
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        compose.waitUntil(5_000) { renames.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("九月出差")).assertIsDisplayed()
        assertEquals(false, renamed)

        reject = false
        clickText(context.getString(R.string.tag_management_rename_dialog_confirm))
        waitForText(context.getString(R.string.tag_management_renamed, "九月出差"))
        compose.onNodeWithText(context.getString(R.string.tag_management_rename_dialog_title)).assertDoesNotExist()
        compose.onNodeWithText("九月出差").assertIsDisplayed()
        assertEquals(listOf(TagRenameRequest(3, "九月出差"), TagRenameRequest(3, "九月出差")), renames)
    }

    @Test fun failedMergeKeepsTheChosenTargetAndOriginalVersions() {
        showTags()
        openSourceAction(R.string.tag_management_card_action_merge)
        val targetLabel = context.getString(R.string.tag_management_merge_dialog_target_with_count, target.name, 3)
        clickText(targetLabel)
        clickText(context.getString(R.string.tag_management_merge_dialog_confirm))
        compose.waitUntil(5_000) { merges.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.tag_management_merge_dialog_title)).assertIsDisplayed()
        compose.onNodeWithText(targetLabel).assertIsDisplayed()
        assertEquals(false, merged)

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

    private fun showTags() {
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    val outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            val navigation = rememberNavController()
                            NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                                transactionsLibraryGraph(navigation, harness.screenFactory, {}, {}, {})
                            }
                        }
                    }
                }
            }
        }
        waitForText(context.getString(R.string.transactions_library_tags_title))
        clickText(context.getString(R.string.transactions_library_tags_title))
        waitForText(source.name)
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
