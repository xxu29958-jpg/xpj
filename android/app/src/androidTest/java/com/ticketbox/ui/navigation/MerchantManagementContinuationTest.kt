package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assert
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeRequest
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.ui.saveConsumerArtPreview
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response
import java.util.concurrent.CopyOnWriteArrayList

/** Original catalog and alias inputs survive unknown replies in the real library. */
class MerchantManagementContinuationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val catalogRequests = CopyOnWriteArrayList<MerchantCatalogCreateRequest>()
    private val aliasRequests = CopyOnWriteArrayList<MerchantAliasRequest>()
    private val updates = CopyOnWriteArrayList<MerchantCatalogUpdateRequest>()
    private val merges = CopyOnWriteArrayList<MerchantCatalogMergeRequest>()
    private val creationKeys = mutableListOf<String>()
    @Volatile private var reject = true
    @Volatile private var catalog: MerchantCatalogDto? = null
    @Volatile private var mergeTarget: MerchantCatalogDto? = null
    @Volatile private var alias: MerchantAliasDto? = null
    private var additionalAliases = emptyList<MerchantAliasDto>()
    @Volatile private var rejectAliasRead = false
    @Volatile private var rejectCatalogRead = false
    private val completedAliasReads = CopyOnWriteArrayList<MerchantAliasListDto>()
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun merchantCatalog(includeHidden: Boolean): MerchantCatalogListDto {
                if (rejectCatalogRead) throw unavailable()
                return MerchantCatalogListDto(listOfNotNull(catalog, mergeTarget))
            }
            override suspend fun merchantAliases(): MerchantAliasListDto {
                if (rejectAliasRead) throw unavailable()
                return MerchantAliasListDto(listOfNotNull(alias) + additionalAliases).also { completedAliasReads += it }
            }
            override suspend fun createMerchantCatalog(request: MerchantCatalogCreateRequest, idempotencyKey: String): MerchantCatalogDto {
                creationKeys += idempotencyKey
                catalogRequests += request
                if (reject) throw unavailable()
                return MerchantCatalogDto("travel-shop", request.displayName, request.displayName, "active",
                    usageCount = 0, createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 1)
                    .also { catalog = it }
            }

            override suspend fun createMerchantAlias(request: MerchantAliasRequest, idempotencyKey: String): MerchantAliasDto {
                creationKeys += idempotencyKey
                aliasRequests += request
                if (reject) throw unavailable()
                val canonical = requireNotNull(request.canonicalMerchant)
                val original = requireNotNull(request.alias)
                return MerchantAliasDto("travel-alias", canonical, canonical, original, original, true,
                    "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z", 1).also { alias = it }
            }

            override suspend fun updateMerchantCatalog(
                publicId: String,
                request: MerchantCatalogUpdateRequest,
                idempotencyKey: String?,
            ): MerchantCatalogDto {
                assertEquals(catalog?.publicId, publicId)
                updates += request
                if (reject) throw unavailable()
                val current = requireNotNull(catalog)
                if (mergeTarget != null && request.displayName == mergeTarget?.displayName) throw HttpException(Response.error<Any>(409,
                    """{"error":"state_conflict","conflict_merchant_public_id":"target","conflict_merchant_row_version":11,"conflict_merchant_display_name":"目标商家","conflict_merchant_status":"active","conflict_merchant_deleted":false}"""
                        .toResponseBody("application/json".toMediaType())))
                if (request.expectedRowVersion != current.rowVersion) throw HttpException(Response.error<Any>(409,
                    """{"error":"state_conflict","message":"商家已被其他设备修改。"}"""
                        .toResponseBody("application/json".toMediaType())))
                return current.copy(displayName = requireNotNull(request.displayName), rowVersion = current.rowVersion + 1)
                    .also { catalog = it }
            }

            override suspend fun mergeMerchantCatalog(sourcePublicId: String, request: MerchantCatalogMergeRequest): MerchantCatalogMergeDto {
                merges += request
                val source = requireNotNull(catalog)
                val target = requireNotNull(mergeTarget)
                assertEquals(source.publicId, sourcePublicId)
                assertEquals(target.publicId, request.targetPublicId)
                if (request.expectedRowVersion != source.rowVersion || request.targetRowVersion != target.rowVersion) {
                    throw HttpException(Response.error<Any>(409, """{"error":"state_conflict"}""".toResponseBody("application/json".toMediaType())))
                }
                catalog = source.copy(status = "merged", mergedIntoPublicId = target.publicId, rowVersion = source.rowVersion + 1)
                mergeTarget = target.copy(rowVersion = target.rowVersion + 1)
                return MerchantCatalogMergeDto(requireNotNull(catalog), requireNotNull(mergeTarget), null)
            }
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun unknownCatalogCreationKeepsItsNameAndKeyUntilAccepted() {
        showMerchants()
        clickText(R.string.merchant_management_tools_add_catalog)
        fill(R.string.merchant_catalog_name_label, "九月差旅商家")
        clickText(R.string.merchant_catalog_create_button)
        compose.waitUntil(5_000) { catalogRequests.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithText("九月差旅商家").assertIsDisplayed().assert(hasSetTextAction().not())
        reopenMerchantTask(aliasTask = false)
        compose.onNodeWithText("九月差旅商家").assertIsDisplayed().assert(hasSetTextAction().not())
        saveConsumerArtPreview("merchant-original-create", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        assertEquals(null, catalog)

        reject = false
        compose.onNodeWithText("核实原添加").performScrollTo().assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { compose.onAllNodesWithText("原添加已确认。").fetchSemanticsNodes().isNotEmpty() }
        assertEquals(creationKeys.first(), creationKeys.last())
        compose.onNodeWithText("九月差旅商家").assertIsDisplayed()
        assertEquals(listOf(MerchantCatalogCreateRequest("九月差旅商家"), MerchantCatalogCreateRequest("九月差旅商家")),
            catalogRequests)
    }

    @Test fun directoryOpensTheOriginalMerchantAndReturnsToItsAliasSearch() {
        catalog = MerchantCatalogDto("corner", "街角小馆", "街角小馆", "active", usageCount = 8,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        alias = MerchantAliasDto("corner-alias", "街角小馆", "街角小馆", "街角餐饮店", "街角餐饮店", true,
            "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z", 3)
        additionalAliases = listOf(requireNotNull(alias).copy(publicId = "independent", canonicalMerchant = "独立商家",
            canonicalKey = "独立商家", alias = "独立支付名称", aliasKey = "独立支付名称"))
        showMerchants()
        clickText(R.string.merchant_catalog_card_status_hidden)
        compose.onNodeWithText("街角小馆").assertDoesNotExist()
        clickText(R.string.merchant_catalog_card_status_visible)
        compose.onNodeWithText("街角小馆").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("merchant-directory", compose.onRoot().captureToImage().asAndroidBitmap())
        compose.onNodeWithText("搜索商家或别名").assertIsDisplayed()
        compose.onNode(hasSetTextAction()).performTextReplacement("街角餐饮店")
        closeSoftKeyboard()
        compose.onNodeWithText("街角小馆").performScrollTo().performTouchInput { click() }
        compose.onNodeWithText("街角餐饮店").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("独立支付名称").assertDoesNotExist()
        saveConsumerArtPreview("merchant-object-aliases", compose.onRoot().captureToImage().asAndroidBitmap())
        for (label in listOf("街角餐饮店", "归到 街角小馆")) {
            val layouts = mutableListOf<TextLayoutResult>()
            compose.onNodeWithText(label).performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            val layout = layouts.single()
            // Intrinsic paragraph width can exceed shrink-wrapped Text; check the actual glyph bounds.
            assertTrue("The complete identity must fit: $label, size=${layout.size}",
                !layout.didOverflowHeight && (0 until layout.lineCount).all { line ->
                    !layout.isLineEllipsized(line) && layout.getLineLeft(line) >= 0f &&
                        layout.getLineRight(line) <= layout.size.width
                })
        }

        compose.onNodeWithText("商家目录").performScrollTo().performTouchInput { click() }
        compose.onNode(hasSetTextAction() and hasText("街角餐饮店")).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_card_status_visible)).assertIsSelected()
        saveConsumerArtPreview("merchant-directory-search", compose.onRoot().captureToImage().asAndroidBitmap())
        compose.onNodeWithText("全部别名").performScrollTo().performTouchInput { click() }
        compose.onNodeWithText("独立支付名称").performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(emptyList<MerchantAliasRequest>(), aliasRequests)
        assertEquals(emptyList<MerchantCatalogUpdateRequest>(), updates)
        assertEquals("corner", catalog?.publicId)
    }

    @Test fun failedAliasReadCanRetryWithoutClearingAnUnsentCatalogForm() {
        alias = MerchantAliasDto("original-alias", "常用商家", "常用商家", "原始别名", "原始别名", true,
            "2026-09-30T00:00:00Z", "2026-09-30T00:00:00Z", 1)
        rejectAliasRead = true
        showMerchants()
        clickText(R.string.merchant_management_tools_add_catalog)
        fill(R.string.merchant_catalog_name_label, "尚未提交商家")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText("返回").performScrollTo().assertIsEnabled().performTouchInput { click() }
        clickText(R.string.merchant_directory_all_aliases)
        waitForText(R.string.merchant_aliases_reload_button)

        rejectAliasRead = false
        clickText(R.string.merchant_aliases_reload_button)
        compose.waitUntil(5_000) { completedAliasReads.isNotEmpty() }
        compose.waitUntil(5_000) { compose.onAllNodesWithText("原始别名").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("原始别名").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("merchants-reloaded-alias", compose.onRoot().captureToImage().asAndroidBitmap())
        clickText(R.string.merchant_catalog_section_list)
        clickText(R.string.merchant_management_tools_add_catalog)
        compose.onNode(hasSetTextAction() and hasText("尚未提交商家")).performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(emptyList<MerchantAliasRequest>(), aliasRequests)
    }

    @Test fun unknownAliasCreationKeepsBothNamesAndOriginalKeyUntilAccepted() {
        showMerchants()
        clickText(R.string.merchant_directory_all_aliases)
        clickText(R.string.merchant_management_tools_add_alias)
        fill(R.string.merchant_aliases_canonical_label, "差旅商家")
        fill(R.string.merchant_aliases_alias_label, "PAY-差旅原始商家", index = 1)
        clickText(R.string.merchant_aliases_create_button)
        compose.waitUntil(5_000) { aliasRequests.size == 1 }
        compose.waitForIdle()
        compose.onNodeWithText("差旅商家").assertIsDisplayed().assert(hasSetTextAction().not())
        compose.onNodeWithText("PAY-差旅原始商家").assertIsDisplayed().assert(hasSetTextAction().not())
        reopenMerchantTask(aliasTask = true)
        compose.onNodeWithText("差旅商家").assertIsDisplayed().assert(hasSetTextAction().not())
        compose.onNodeWithText("PAY-差旅原始商家").assertIsDisplayed().assert(hasSetTextAction().not())
        saveConsumerArtPreview("merchant-original-alias", requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        assertEquals(null, alias)

        reject = false
        compose.onNodeWithText("核实原添加").performScrollTo().assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { compose.onAllNodesWithText("原添加已确认。").fetchSemanticsNodes().isNotEmpty() }
        assertEquals(creationKeys.first(), creationKeys.last())
        compose.onNodeWithText("PAY-差旅原始商家").assertIsDisplayed()
        assertEquals(2, aliasRequests.size)
        assertEquals(aliasRequests[0], aliasRequests[1])
        assertEquals("差旅商家", alias?.canonicalMerchant)
        assertEquals("PAY-差旅原始商家", alias?.alias)
    }

    @Test fun acceptedRenamePreservesTheSeparateUnsentCatalogForm() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        showMerchants()
        clickText(R.string.merchant_management_tools_add_catalog)
        fill(R.string.merchant_catalog_name_label, "尚未提交的新商家")
        closeSoftKeyboard()
        compose.onNodeWithText("返回").performScrollTo().assertIsEnabled().performTouchInput { click() }
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_card_action_rename))
            .performScrollTo().assertIsDisplayed().performTouchInput { click() }
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("改名后的商家")
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .performTouchInput { click() }
        compose.waitUntil(5_000) { updates.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("改名后的商家")).assertIsDisplayed()
        assertEquals("原商家", catalog?.displayName)

        reject = false
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .performTouchInput { click() }
        compose.waitUntil(5_000) { catalog?.displayName == "改名后的商家" }
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_title)).assertDoesNotExist()
        clickText(R.string.merchant_catalog_section_list)
        clickText(R.string.merchant_management_tools_add_catalog)
        compose.onNode(hasSetTextAction() and hasText("尚未提交的新商家")).performScrollTo().assertIsDisplayed()
        assertEquals(emptyList<MerchantCatalogCreateRequest>(), catalogRequests)
        assertEquals(2, updates.size)
        assertEquals(updates[0], updates[1])
        assertEquals(7L, updates.first().expectedRowVersion)
    }

    @Test fun conflictedRenameReviewsTheSameMerchantAndKeepsTheOriginalInput() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        reject = false
        showMerchants()
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
        clickText(R.string.merchant_catalog_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("  我的原稿名称  ")
        closeSoftKeyboard()
        catalog = requireNotNull(catalog).copy(displayName = "另一台设备的名称", rowVersion = 8)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { updates.size == 1 }
        compose.waitForIdle()
        compose.onNode(hasSetTextAction() and hasText("  我的原稿名称  ")).assertIsDisplayed()
        compose.onNodeWithText("核对最新商家").performScrollTo().assertIsDisplayed()

        rejectCatalogRead = true
        compose.onNodeWithText("核对最新商家").performScrollTo().performTouchInput { click() }
        compose.waitForIdle()
        assertEquals(1, updates.size)
        compose.onNode(hasSetTextAction() and hasText("  我的原稿名称  ")).performScrollTo().assertIsDisplayed()
        rejectCatalogRead = false
        compose.onNodeWithText("核对最新商家").performScrollTo().performTouchInput { click() }
        compose.waitUntil(5_000) {
            compose.onAllNodesWithText("当前名称：另一台设备的名称").fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNode(hasSetTextAction() and hasText("  我的原稿名称  ")).performScrollTo().assertIsDisplayed()
        assertEquals(1, updates.size)
        assertEquals("另一台设备的名称", catalog?.displayName)
        saveConsumerArtPreview("merchant-rename-reviewed",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm))
            .assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { catalog?.displayName == "我的原稿名称" }
        assertEquals(listOf(7L, 8L), updates.map { it.expectedRowVersion })
        assertEquals("existing", catalog?.publicId)
        assertEquals(9L, catalog?.rowVersion)
        assertTrue(catalogRequests.isEmpty() && aliasRequests.isEmpty())
    }

    @Test fun missingMerchantKeepsTheRenameInputWithoutSubmittingToAnotherObject() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        showMerchants()
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
        clickText(R.string.merchant_catalog_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("仍需保留的原稿")
        closeSoftKeyboard()
        catalog = null
        compose.onNodeWithText("核对最新商家").performScrollTo().performTouchInput { click() }
        waitForText(R.string.merchant_rename_unavailable)
        compose.onNode(hasSetTextAction() and hasText("仍需保留的原稿")).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm)).assertIsNotEnabled()
        assertTrue(updates.isEmpty() && catalogRequests.isEmpty() && aliasRequests.isEmpty())
        saveConsumerArtPreview("merchant-rename-unavailable",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    @Test fun conflictedMergeReviewsBothOriginalMerchantsWithoutLosingTheAliasChoice() {
        prepareMerge()
        clickText(R.string.merchant_catalog_card_action_merge)
        if (InstrumentationRegistry.getArguments().getString("visualMode") == "large") {
            val titleLayouts = mutableListOf<TextLayoutResult>()
            compose.onNodeWithText(context.getString(R.string.merchant_catalog_merge_dialog_title))
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(titleLayouts) }
            assertEquals("The dialog must use the requested large font scale", 2f,
                titleLayouts.single().layoutInput.density.fontScale, 0.01f)
        }
        compose.onNodeWithText("目标商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_catalog_merge_alias_policy_none)
        catalog = requireNotNull(catalog).copy(displayName = "他端修改的原商家", rowVersion = 8)
        mergeTarget = requireNotNull(mergeTarget).copy(displayName = "他端修改的目标", rowVersion = 12)
        compose.onNode(hasText(context.getString(R.string.merchant_catalog_merge_dialog_confirm)) and hasAnyAncestor(isDialog())).performTouchInput { click() }
        waitForText(R.string.merchant_catalog_error_state_conflict)
        saveConsumerArtPreview("merchant-merge-conflict-before",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("核对双方商家").performScrollTo().assertIsDisplayed()
        assertEquals(1, merges.size)
        rejectCatalogRead = true
        compose.onNodeWithText("核对双方商家").performTouchInput { click() }
        compose.waitUntil(5_000) {
            compose.onAllNodesWithText("暂时无法保存，请保留当前填写后重试。").fetchSemanticsNodes().isNotEmpty()
        }
        assertEquals(1, merges.size)
        rejectCatalogRead = false
        compose.onNodeWithText("核对双方商家").performScrollTo().performTouchInput { click() }
        compose.waitUntil(5_000) { compose.onAllNodesWithText("他端修改的目标").fetchSemanticsNodes().isNotEmpty() }
        assertEquals(1, merges.size)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_merge_alias_policy_none)).performScrollTo().assertIsSelected()
        compose.onNode(hasText(context.getString(R.string.merchant_merge_reviewed, "他端修改的原商家", "他端修改的目标")) and hasAnyAncestor(isDialog()))
            .performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("merchant-merge-reviewed",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNode(hasText(context.getString(R.string.merchant_catalog_merge_dialog_confirm)) and hasAnyAncestor(isDialog())).assertIsEnabled().performTouchInput { click() }
        compose.waitUntil(5_000) { catalog?.status == "merged" }
        assertEquals(listOf(7L, 8L), merges.map { it.expectedRowVersion })
        assertEquals(listOf(11L, 12L), merges.map { it.targetRowVersion })
        assertTrue(merges.all { it.targetPublicId == "target" && it.aliasPolicy == "none" && !it.rewriteHistoricalExpenses })
        assertTrue(catalogRequests.isEmpty() && aliasRequests.isEmpty() && updates.isEmpty())
    }

    @Test fun suggestedMergeCanReturnToOriginalRenameAndCloseAfterAcceptance() {
        prepareMerge()
        clickText(R.string.merchant_catalog_card_action_rename)
        compose.onNode(hasSetTextAction() and hasText("原商家")).performTextReplacement("  目标商家  ")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm)).performTouchInput { click() }
        waitForText(R.string.merchant_catalog_merge_dialog_title)
        catalog = requireNotNull(catalog).copy(displayName = "另一端已改名", rowVersion = 8)
        clickText(R.string.merchant_merge_review)
        compose.waitUntil(5_000) {
            compose.onAllNodesWithText(context.getString(R.string.merchant_merge_reviewed, "另一端已改名", "目标商家"))
                .fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performTouchInput { click() }
        compose.onNodeWithText("当前名称：另一端已改名").performScrollTo().assertIsDisplayed()
        compose.onNode(hasSetTextAction() and hasText("  目标商家  ")).assertIsDisplayed()
        assertEquals(1, updates.size)
        assertTrue(merges.isEmpty() && catalogRequests.isEmpty())
        assertEquals("另一端已改名", catalog?.displayName)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_rename_dialog_confirm)).performTouchInput { click() }
        waitForText(R.string.merchant_catalog_merge_dialog_title)
        clickText(R.string.merchant_catalog_merge_alias_policy_none)
        compose.onNode(hasText(context.getString(R.string.merchant_catalog_merge_dialog_confirm)) and hasAnyAncestor(isDialog()))
            .performTouchInput { click() }
        compose.waitUntil(5_000) { catalog?.status == "merged" && compose.onAllNodes(isDialog()).fetchSemanticsNodes().isEmpty() }
        assertEquals(1, merges.size)
        assertEquals(2, updates.size)
        assertEquals(listOf(7L, 8L), updates.map { it.expectedRowVersion })
        assertEquals(8L, merges.single().expectedRowVersion)
    }

    @Test fun unavailableMergePairKeepsChoicesWithoutSubmittingToAReplacement() {
        prepareMerge()
        clickText(R.string.merchant_catalog_card_action_merge)
        compose.onNodeWithText("目标商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_catalog_merge_alias_policy_none)
        mergeTarget = requireNotNull(mergeTarget).copy(publicId = "replacement", rowVersion = 1)
        clickText(R.string.merchant_merge_review)
        waitForText(R.string.merchant_merge_target_unavailable)
        compose.onNodeWithText("已选目标：目标商家").performScrollTo().assertIsDisplayed()
        compose.onNode(hasText(context.getString(R.string.merchant_catalog_merge_dialog_confirm)) and hasAnyAncestor(isDialog()))
            .assertIsNotEnabled()
        compose.onNodeWithText("目标商家").performScrollTo().performTouchInput { click() }
        compose.onNode(hasText(context.getString(R.string.merchant_catalog_merge_dialog_confirm)) and hasAnyAncestor(isDialog()))
            .assertIsEnabled()
        catalog = null
        clickText(R.string.merchant_merge_review)
        waitForText(R.string.merchant_merge_source_unavailable)
        compose.onNodeWithText(context.getString(R.string.merchant_catalog_merge_alias_policy_none)).performScrollTo().assertIsSelected()
        compose.onNode(hasText(context.getString(R.string.merchant_catalog_merge_dialog_confirm)) and hasAnyAncestor(isDialog()))
            .assertIsNotEnabled()
        saveConsumerArtPreview("merchant-merge-unavailable",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        assertTrue(merges.isEmpty() && updates.isEmpty() && catalogRequests.isEmpty() && aliasRequests.isEmpty())
    }

    private fun prepareMerge() {
        catalog = MerchantCatalogDto("existing", "原商家", "原商家", "active", usageCount = 2,
            createdAt = "2026-09-30T00:00:00Z", updatedAt = "2026-09-30T00:00:00Z", rowVersion = 7)
        mergeTarget = requireNotNull(catalog).copy(publicId = "target", displayName = "目标商家", usageCount = 0, rowVersion = 11)
        reject = false
        showMerchants()
        compose.onNodeWithText("原商家").performScrollTo().performTouchInput { click() }
        clickText(R.string.merchant_detail_identity)
    }

    private fun reopenMerchantTask(aliasTask: Boolean) {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        compose.runOnIdle { harness.reopen(); mounted.value = true }
        waitForText(R.string.transactions_library_merchants_title)
        clickText(R.string.transactions_library_merchants_title)
        waitForText(R.string.merchant_management_tools_add_catalog)
        if (aliasTask) {
            clickText(R.string.merchant_directory_all_aliases)
            clickText(R.string.merchant_management_tools_add_alias)
        } else clickText(R.string.merchant_management_tools_add_catalog)
        compose.onNodeWithText("核实原添加").performScrollTo().assertIsEnabled()
        assertEquals(1, creationKeys.size)
    }

    private fun showMerchants() {
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                ReferenceLibraryTestTheme {
                    val outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            val navigation = rememberNavController()
                            NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                                transactionsLibraryGraph(navigation, harness.screenFactory, TransactionsLibraryWrites({}, {}, {}))
                            }
                        }
                    }
                }
            }
        }
        waitForText(R.string.transactions_library_merchants_title)
        clickText(R.string.transactions_library_merchants_title)
        waitForText(R.string.merchant_management_tools_add_catalog)
    }

    private fun clickText(label: Int) = compose.onNodeWithText(context.getString(label))
        .performScrollTo().assertIsEnabled().performTouchInput { click() }

    private fun fill(label: Int, value: String, index: Int = 0) {
        // AppTextInput exposes its label as a sibling, not as editable text.
        compose.onNodeWithText(context.getString(label)).performScrollTo().assertIsDisplayed()
        compose.onAllNodes(hasSetTextAction())[index].performTextReplacement(value)
    }

    private fun waitForText(label: Int) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(context.getString(label)).fetchSemanticsNodes().isNotEmpty()
    }

    private fun unavailable() = HttpException(Response.error<Any>(503,
        """{"error":"service_unavailable","message":"暂时无法保存，请保留当前填写后重试。"}"""
            .toResponseBody("application/json".toMediaType())))
}
