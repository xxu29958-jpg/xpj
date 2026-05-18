package com.ticketbox.data.repository

import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptRequestDto
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.InvitationPreviewRequestDto
import com.ticketbox.data.remote.dto.InvitationPreviewResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.TagsDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.data.remote.dto.UserUiPreferencesDto
import com.ticketbox.data.remote.dto.UserUiPreferencesUpdateRequestDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LedgerRepositoryTest {

    @Test
    fun refreshLedgersPersistsJsonAndExposesSummaries() = runTest {
        val ledgers = listOf(
            ledgerDto("L_owner", "我的小票夹", role = "owner", isDefault = true),
            ledgerDto("L_house", "家庭账本", role = "viewer", isDefault = false),
        )
        val api = StubApi(listLedgersResult = LedgerListResponseDto(ledgers))
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val dao = LedgerFakeDao()
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val refreshed = repo.refreshLedgers().getOrThrow()
        assertEquals(listOf("L_owner", "L_house"), refreshed.map { it.ledgerId })
        // Cached read returns the same list without hitting the network.
        api.listLedgersResult = null
        val cached = repo.cachedLedgers()
        assertEquals(listOf("L_owner", "L_house"), cached.map { it.ledgerId })
    }

    @Test
    fun refreshLedgersPersistsActiveLedgerRoleChange() = runTest {
        val api = StubApi(
            listLedgersResult = LedgerListResponseDto(
                ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "viewer", isDefault = true)),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val ledgers = repo.refreshLedgers().getOrThrow()

        assertEquals("viewer", ledgers.single().role)
        assertEquals("viewer", store.role())
        assertEquals("L_family", store.activeLedgerId())
    }

    @Test
    fun refreshLedgersWrapsRuntimeExceptions() = runTest {
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(StubApi(listLedgersError = RuntimeException("json bad"))),
            settingsStore = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") },
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.refreshLedgers().exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("json bad"))
    }

    @Test
    fun createLedgerRejectsBlankNameWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.createLedger("   ").exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("请填写账本名称"))
    }

    @Test
    fun createLedgerRejectsOversizeNameWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.createLedger("帐".repeat(61)).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("最多 60 个字"))
    }

    @Test
    fun switchLedgerRotatesTokenAndClearsTargetCacheFirst() = runTest {
        val newToken = "session-token-new"
        val api = StubApi(
            switchResult = LedgerSwitchResponseDto(
                sessionToken = newToken,
                ledger = ledgerDto("L_house", "家庭账本", role = "viewer"),
                accountName = "我",
                deviceName = "Pixel",
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val dao = LedgerFakeDao().apply {
            // Pre-seed the cache for both ledgers.
            insertEntity(ledgerEntity(id = 1, ledgerId = "L_owner", serverId = 100))
            insertEntity(ledgerEntity(id = 2, ledgerId = "L_house", serverId = 200))
        }
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val summary = repo.switchLedger("L_house").getOrThrow()
        assertEquals("L_house", summary.ledgerId)
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_house", store.activeLedgerId())
        assertEquals("viewer", store.capturedRole)
        // Only the target ledger's rows are wiped; the other ledger keeps its cache.
        assertNull(dao.find(2))
        assertNotNull(dao.find(1))
    }

    @Test
    fun switchLedgerFailurePreservesOldToken() = runTest {
        val errorJson = "{\"error\":\"forbidden\",\"message\":\"无权访问该账本\"}"
        val api = StubApi(
            switchError = HttpException(
                Response.error<Any>(403, errorJson.toResponseBody("application/json".toMediaType())),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.switchLedger("L_house").exceptionOrNull()
        assertNotNull(failure)
        assertEquals("old-token", tokenStore.getToken())
        assertNull(store.activeLedgerId())
        assertFalse(failure.message.isNullOrBlank())
    }

    @Test
    fun concurrentSwitchLedgerRequestsAreSerializedSoLatestCallWins() = runTest {
        val firstStarted = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val api = StubApi(
            switchHandler = { ledgerId ->
                if (ledgerId == "L_first") {
                    firstStarted.complete(Unit)
                    releaseFirst.await()
                }
                LedgerSwitchResponseDto(
                    sessionToken = "token-$ledgerId",
                    ledger = ledgerDto(ledgerId, ledgerId, role = "owner"),
                    accountName = "我",
                    deviceName = "Pixel",
                )
            },
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val first = async { repo.switchLedger("L_first") }
        firstStarted.await()
        val second = async { repo.switchLedger("L_second") }
        yield()

        assertEquals(listOf("L_first"), api.switchRequests)
        releaseFirst.complete(Unit)

        assertEquals("L_first", first.await().getOrThrow().ledgerId)
        assertEquals("L_second", second.await().getOrThrow().ledgerId)
        assertEquals(listOf("L_first", "L_second"), api.switchRequests)
        assertEquals("token-L_second", tokenStore.getToken())
        assertEquals("L_second", store.activeLedgerId())
    }

    @Test
    fun acceptInvitationPersistsTokenIdentityAndWipesTargetCache() = runTest {
        val newToken = "session-token-fresh"
        val api = StubApi(
            acceptResult = InvitationAcceptResponseDto(
                sessionToken = newToken,
                accountName = "二号",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel 8",
                role = "member",
            ),
            // refreshLedgers is called after accept; let it succeed with a tiny list.
            listLedgersResult = LedgerListResponseDto(
                ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val dao = LedgerFakeDao().apply {
            // Pre-seed cache for the target ledger so we can prove it gets wiped.
            insertEntity(ledgerEntity(id = 1, ledgerId = "L_family", serverId = 100))
            insertEntity(ledgerEntity(id = 2, ledgerId = "L_other", serverId = 200))
        }
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = dao,
        )

        val summary = repo.acceptInvitation(
            inviteToken = "  inv_PLAINTOKEN  ",
            accountName = "二号",
            deviceName = "Pixel 8",
        ).getOrThrow()

        assertEquals("L_family", summary.ledgerId)
        assertEquals("member", summary.role)
        // The plain token is trimmed before being sent to the server.
        assertEquals("inv_PLAINTOKEN", api.acceptRequests.single().inviteToken)
        assertEquals("android", api.acceptRequests.single().platform)
        // Invitation accept is a public endpoint; do not leak the previous session token.
        assertNull(apiFactory.tokenProviders.first().invoke())
        // Token rotated; identity captured; active ledger switched.
        assertEquals(newToken, tokenStore.getToken())
        assertEquals("L_family", store.activeLedgerId())
        assertEquals("二号", store.capturedAccountName)
        assertEquals("Pixel 8", store.capturedDeviceName)
        assertEquals("member", store.capturedRole)
        assertFalse(store.capturedBoundAt.isNullOrBlank())
        // Target-ledger cache wiped; unrelated ledger preserved.
        assertNull(dao.find(1))
        assertNotNull(dao.find(2))
    }

    @Test
    fun previewInvitationReturnsTargetWithoutReplacingExistingBinding() = runTest {
        val ledgerName = "家庭共同账本" + "很长".repeat(20)
        val api = StubApi(
            previewResult = InvitationPreviewResponseDto(
                ledgerId = "L_family",
                ledgerName = ledgerName,
                role = "viewer",
                expiresAt = "2026-05-20T00:00:00Z",
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "旧账号",
                ledgerId = "L_old",
                ledgerName = "旧账本",
                deviceName = "Old Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val apiFactory = LedgerStubApiFactory(api)
        val repo = LedgerRepository(
            apiClient = apiFactory,
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val preview = repo.previewInvitation("  inv_PREVIEW  ").getOrThrow()

        assertEquals("L_family", preview.ledgerId)
        assertEquals(ledgerName, preview.ledgerName)
        assertEquals("viewer", preview.role)
        assertEquals("2026-05-20T00:00:00Z", preview.expiresAt)
        assertEquals("inv_PREVIEW", api.previewRequests.single().inviteToken)
        // Invitation preview is a public endpoint; it must not attach the existing token.
        assertNull(apiFactory.tokenProviders.single().invoke())
        assertEquals("old-token", tokenStore.getToken())
        assertEquals("L_old", store.activeLedgerId())
        assertEquals("旧账号", store.accountName())
        assertEquals("owner", store.role())
    }

    @Test
    fun previewInvitationRejectsBlankTokenWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.previewInvitation("   ").exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("邀请明文"))
    }

    @Test
    fun previewInvitationNetworkFailurePreservesExistingBinding() = runTest {
        val api = StubApi(previewError = IOException("timeout"))
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "旧账号",
                ledgerId = "L_old",
                ledgerName = "旧账本",
                deviceName = "Old Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.previewInvitation("inv_TIMEOUT").exceptionOrNull()

        assertNotNull(failure)
        assertEquals("网络连接失败，请检查电脑端服务。", failure.message)
        assertEquals("old-token", tokenStore.getToken())
        assertEquals("L_old", store.activeLedgerId())
        assertEquals("旧账号", store.accountName())
    }

    @Test
    fun acceptInvitationRejectsBlankTokenWithChineseMessage() = runTest {
        val repo = makeRepo()
        val failure = repo.acceptInvitation(
            inviteToken = "   ",
            accountName = "二号",
            deviceName = "Pixel",
        ).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("邀请明文"))
    }

    @Test
    fun acceptInvitationServerErrorPreservesOldTokenAndBinding() = runTest {
        val errorJson = "{\"error\":\"invalid_invite_token\",\"message\":\"邀请已过期或不存在\"}"
        val api = StubApi(
            acceptError = HttpException(
                Response.error<Any>(400, errorJson.toResponseBody("application/json".toMediaType())),
            ),
        )
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("old-token") }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )

        val failure = repo.acceptInvitation(
            inviteToken = "inv_BAD",
            accountName = "二号",
            deviceName = "Pixel",
        ).exceptionOrNull()
        assertNotNull(failure)
        // Old token must NOT be overwritten on failure; identity not touched.
        assertEquals("old-token", tokenStore.getToken())
        assertNull(store.activeLedgerId())
        assertNull(store.capturedAccountName)
    }

    @Test
    fun refreshFamilyMembersMapsServerFieldsToDomain() = runTest {
        val api = StubApi(
            membersResult = LedgerMemberListResponseDto(
                members = listOf(
                    LedgerMemberDto(
                        memberId = 1,
                        accountPublicId = "acc_owner",
                        accountName = "阿方",
                        role = "owner",
                        createdAt = "2026-05-01T00:00:00Z",
                        disabledAt = null,
                        isSelf = true,
                    ),
                    LedgerMemberDto(
                        memberId = 2,
                        accountPublicId = "acc_viewer",
                        accountName = "",
                        role = "viewer",
                        createdAt = null,
                        disabledAt = "2026-05-02T00:00:00Z",
                        isSelf = false,
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val members = repo.refreshFamilyMembers().getOrThrow()

        assertEquals("L_family", api.memberLedgerRequests.single())
        assertEquals(listOf("阿方", "未命名成员"), members.map { it.displayName })
        assertEquals(listOf("owner", "viewer"), members.map { it.role })
        assertTrue(members.first().isSelf)
        assertTrue(members.last().isDisabled)
    }

    @Test
    fun refreshFamilyMembersPersistsSelfRoleDowngrade() = runTest {
        val api = StubApi(
            membersResult = LedgerMemberListResponseDto(
                members = listOf(
                    LedgerMemberDto(
                        memberId = 1,
                        accountPublicId = "acc_self",
                        accountName = "我",
                        role = "viewer",
                        createdAt = "2026-05-01T00:00:00Z",
                        disabledAt = null,
                        isSelf = true,
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val members = repo.refreshFamilyMembers().getOrThrow()

        assertEquals("viewer", members.single().role)
        assertEquals("viewer", store.role())
        assertEquals("L_family", store.activeLedgerId())
    }

    @Test
    fun refreshFamilyMembersSlowResponseDoesNotPersistRoleAfterLedgerSwitch() = runTest {
        val api = StubApi(
            membersResult = LedgerMemberListResponseDto(
                members = listOf(
                    LedgerMemberDto(
                        memberId = 1,
                        accountPublicId = "acc_self",
                        accountName = "我",
                        role = "viewer",
                        createdAt = "2026-05-01T00:00:00Z",
                        disabledAt = null,
                        isSelf = true,
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        api.onLedgerMembers = {
            store.saveIdentity(
                accountName = "我",
                ledgerId = "L_other",
                ledgerName = "另一个账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:05:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val members = repo.refreshFamilyMembers().getOrThrow()

        assertEquals("viewer", members.single().role)
        assertEquals("L_other", store.activeLedgerId())
        assertEquals("owner", store.role())
    }

    @Test
    fun refreshFamilyMembersRejectsMissingActiveLedger() = runTest {
        val repo = makeRepo()
        val failure = repo.refreshFamilyMembers(null).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("当前账本"))
    }

    @Test
    fun refreshFamilyAuditMapsServerFieldsAndClampsLimit() = runTest {
        val api = StubApi(
            auditResult = LedgerAuditListResponseDto(
                items = listOf(
                    LedgerAuditDto(
                        publicId = "audit-1",
                        ledgerId = "L_family",
                        action = "member_role_changed",
                        actorAccountPublicId = "acc_owner",
                        actorAccountName = "阿方",
                        targetAccountPublicId = "acc_member",
                        targetAccountName = "",
                        targetMemberId = 2,
                        invitationPublicId = null,
                        previousRole = "member",
                        newRole = "viewer",
                        result = "success",
                        detail = "hidden-detail",
                        createdAt = "2026-05-13T00:00:00Z",
                    ),
                ),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val audit = repo.refreshFamilyAudit(limit = 500).getOrThrow()

        assertEquals(listOf("L_family" to 200), api.auditRequests)
        assertEquals("audit-1", audit.single().publicId)
        assertEquals("member_role_changed", audit.single().action)
        assertEquals("阿方", audit.single().actorName)
        assertNull(audit.single().targetName)
        assertEquals(2L, audit.single().targetMemberId)
        assertEquals("member", audit.single().previousRole)
        assertEquals("viewer", audit.single().newRole)
        assertEquals("success", audit.single().result)
    }

    @Test
    fun refreshFamilyAuditRejectsMissingActiveLedger() = runTest {
        val repo = makeRepo()
        val failure = repo.refreshFamilyAudit(null).exceptionOrNull()
        assertNotNull(failure)
        assertTrue(failure.message!!.contains("当前账本"))
    }

    @Test
    fun updateFamilyMemberRolePostsTrimmedRoleAndMapsResponse() = runTest {
        val api = StubApi(
            roleUpdateResult = LedgerMemberDto(
                memberId = 2,
                accountPublicId = "acc_member",
                accountName = "家人",
                role = "viewer",
                createdAt = "2026-05-01T00:00:00Z",
                disabledAt = null,
                isSelf = false,
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val updated = repo.updateFamilyMemberRole(2, " viewer ").getOrThrow()

        assertEquals("viewer", updated.role)
        assertEquals(listOf("L_family" to 2L), api.roleUpdateTargets)
        assertEquals("viewer", api.roleUpdateRequests.single().role)
    }

    @Test
    fun updateFamilyMemberRoleRejectsOwnerRoleLocally() = runTest {
        val repo = makeRepo()
        val failure = repo.updateFamilyMemberRole(2, "owner", ledgerId = "L_family").exceptionOrNull()

        assertNotNull(failure)
        assertTrue(failure.message!!.contains("成员角色只能是成员或只读"))
    }

    @Test
    fun disableFamilyMemberPostsTargetAndMapsResponse() = runTest {
        val api = StubApi(
            disableResult = LedgerMemberDto(
                memberId = 2,
                accountPublicId = "acc_member",
                accountName = "家人",
                role = "member",
                createdAt = "2026-05-01T00:00:00Z",
                disabledAt = "2026-05-13T00:00:00Z",
                isSelf = false,
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveActiveLedger("L_family", "家庭账本")
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val disabled = repo.disableFamilyMember(2).getOrThrow()

        assertTrue(disabled.isDisabled)
        assertEquals(listOf("L_family" to 2L), api.disableTargets)
    }

    @Test
    fun transferOwnerDemotesSelfRoleAndRefreshesLedgerCache() = runTest {
        val api = StubApi(
            transferResult = OwnerTransferResponseDto(
                ledgerId = "L_family",
                previousOwner = LedgerMemberDto(
                    memberId = 1,
                    accountPublicId = "acc_self",
                    accountName = "我",
                    role = "member",
                    createdAt = "2026-05-01T00:00:00Z",
                    disabledAt = null,
                    isSelf = true,
                ),
                newOwner = LedgerMemberDto(
                    memberId = 2,
                    accountPublicId = "acc_new",
                    accountName = "家人",
                    role = "owner",
                    createdAt = "2026-05-02T00:00:00Z",
                    disabledAt = null,
                    isSelf = false,
                ),
            ),
            listLedgersResult = LedgerListResponseDto(
                ledgers = listOf(ledgerDto("L_family", "家庭账本", role = "member")),
            ),
        )
        val store = LedgerFakeSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "L_family",
                ledgerName = "家庭账本",
                deviceName = "Pixel",
                role = "owner",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
        val repo = LedgerRepository(
            apiClient = LedgerStubApiFactory(api),
            settingsStore = store,
            tokenStore = LedgerFakeTokenStore().apply { saveToken("t") },
            expenseDao = LedgerFakeDao(),
        )

        val result = repo.transferOwner(2).getOrThrow()

        assertEquals("member", result.previousOwner.role)
        assertEquals("owner", result.newOwner.role)
        assertEquals("member", store.role())
        assertEquals(listOf("L_family" to 2L), api.transferTargets)
        assertEquals("member", repo.cachedLedgers().single().role)
    }

    private fun makeRepo(): LedgerRepository {
        val store = LedgerFakeSettingsStore().apply { saveServerUrl("https://api.example.com") }
        val tokenStore = LedgerFakeTokenStore().apply { saveToken("t") }
        return LedgerRepository(
            apiClient = LedgerStubApiFactory(StubApi()),
            settingsStore = store,
            tokenStore = tokenStore,
            expenseDao = LedgerFakeDao(),
        )
    }

    private fun ledgerDto(
        id: String,
        name: String,
        role: String = "owner",
        isDefault: Boolean = false,
    ) = LedgerDto(
        ledgerId = id,
        name = name,
        role = role,
        isDefault = isDefault,
        createdAt = "2026-01-01T00:00:00Z",
        archivedAt = null,
    )
}

private class LedgerStubApiFactory(private val service: ApiService) : ApiServiceFactory {
    val tokenProviders: MutableList<() -> String?> = mutableListOf()

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        tokenProviders += tokenProvider
        return service
    }
}

private class StubApi(
    var listLedgersResult: LedgerListResponseDto? = null,
    var listLedgersError: Throwable? = null,
    var createResult: LedgerDto? = null,
    var switchResult: LedgerSwitchResponseDto? = null,
    var switchHandler: (suspend (String) -> LedgerSwitchResponseDto)? = null,
    var switchError: Throwable? = null,
    var membersResult: LedgerMemberListResponseDto? = null,
    var auditResult: LedgerAuditListResponseDto? = null,
    var roleUpdateResult: LedgerMemberDto? = null,
    var disableResult: LedgerMemberDto? = null,
    var transferResult: OwnerTransferResponseDto? = null,
    var previewResult: InvitationPreviewResponseDto? = null,
    var previewError: Throwable? = null,
    var acceptResult: InvitationAcceptResponseDto? = null,
    var acceptError: Throwable? = null,
    val switchRequests: MutableList<String> = mutableListOf(),
    val memberLedgerRequests: MutableList<String> = mutableListOf(),
    val auditRequests: MutableList<Pair<String, Int>> = mutableListOf(),
    val roleUpdateTargets: MutableList<Pair<String, Long>> = mutableListOf(),
    val roleUpdateRequests: MutableList<LedgerMemberRoleUpdateRequestDto> = mutableListOf(),
    val disableTargets: MutableList<Pair<String, Long>> = mutableListOf(),
    val transferTargets: MutableList<Pair<String, Long>> = mutableListOf(),
    val previewRequests: MutableList<InvitationPreviewRequestDto> = mutableListOf(),
    val acceptRequests: MutableList<InvitationAcceptRequestDto> = mutableListOf(),
) : ApiService {
    var onLedgerMembers: (() -> Unit)? = null

    override suspend fun listLedgers(): LedgerListResponseDto {
        listLedgersError?.let { throw it }
        return listLedgersResult ?: LedgerListResponseDto(ledgers = emptyList())
    }

    override suspend fun createLedger(request: LedgerCreateRequestDto): LedgerDto {
        return createResult ?: LedgerDto(
            ledgerId = "L_new",
            name = request.name,
            role = "owner",
            isDefault = false,
            createdAt = "2026-01-01T00:00:00Z",
            archivedAt = null,
        )
    }

    override suspend fun switchLedger(ledgerId: String): LedgerSwitchResponseDto {
        switchRequests += ledgerId
        switchError?.let { throw it }
        switchHandler?.let { return it(ledgerId) }
        return switchResult ?: error("Unexpected switch call")
    }

    override suspend fun ledgerMembers(ledgerId: String): LedgerMemberListResponseDto {
        memberLedgerRequests += ledgerId
        onLedgerMembers?.invoke()
        return membersResult ?: error("Unexpected members call")
    }

    override suspend fun ledgerAudit(ledgerId: String, limit: Int): LedgerAuditListResponseDto {
        auditRequests += ledgerId to limit
        return auditResult ?: error("Unexpected audit call")
    }

    override suspend fun updateLedgerMemberRole(
        ledgerId: String,
        memberId: Long,
        request: LedgerMemberRoleUpdateRequestDto,
    ): LedgerMemberDto {
        roleUpdateTargets += ledgerId to memberId
        roleUpdateRequests += request
        return roleUpdateResult ?: error("Unexpected role update call")
    }

    override suspend fun disableLedgerMember(ledgerId: String, memberId: Long): LedgerMemberDto {
        disableTargets += ledgerId to memberId
        return disableResult ?: error("Unexpected disable call")
    }

    override suspend fun transferLedgerOwner(
        ledgerId: String,
        memberId: Long,
    ): OwnerTransferResponseDto {
        transferTargets += ledgerId to memberId
        return transferResult ?: error("Unexpected transfer call")
    }

    override suspend fun previewInvitation(
        request: InvitationPreviewRequestDto,
    ): InvitationPreviewResponseDto {
        previewRequests += request
        previewError?.let { throw it }
        return previewResult ?: error("Unexpected preview call")
    }

    override suspend fun acceptInvitation(request: InvitationAcceptRequestDto): InvitationAcceptResponseDto {
        acceptRequests += request
        acceptError?.let { throw it }
        return acceptResult ?: error("Unexpected accept call")
    }

    override suspend fun pairDevice(request: PairRequestDto): PairResponseDto = unsupported()
    override suspend fun checkAuth(): AuthCheckDto = unsupported()
    override suspend fun pendingExpenses(): List<ExpenseDto> = unsupported()
    override suspend fun confirmedExpenses(
        page: Int,
        pageSize: Int,
        month: String?,
        category: String?,
        tag: String?,
        timezone: String?,
    ): PaginatedExpensesDto = unsupported()
    override suspend fun categories(): CategoriesDto = unsupported()
    override suspend fun tags(): TagsDto = unsupported()
    override suspend fun months(timezone: String?): MonthsDto = unsupported()
    override suspend fun exportCsv(month: String?, category: String?, tag: String?, timezone: String?): Response<ResponseBody> = unsupported()
    override suspend fun createManualExpense(request: ExpenseUpdateRequest): ExpenseDto = unsupported()
    override suspend fun createNotificationDraft(
        request: com.ticketbox.data.remote.dto.NotificationDraftRequestDto,
    ): ExpenseDto = unsupported()
    override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?): UploadResponseDto = unsupported()
    override suspend fun expense(id: Long): ExpenseDto = unsupported()
    override suspend fun updateExpense(id: Long, request: ExpenseUpdateRequest): ExpenseDto = unsupported()
    override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto = unsupported()
    override suspend fun replaceExpenseItems(
        id: Long,
        request: ExpenseItemReplaceRequestDto,
    ): ExpenseItemsResponseDto = unsupported()
    override suspend fun expenseSplits(id: Long): ExpenseSplitsResponseDto = unsupported()
    override suspend fun replaceExpenseSplits(
        id: Long,
        request: ExpenseSplitReplaceRequestDto,
    ): ExpenseSplitsResponseDto = unsupported()
    override suspend fun confirmExpense(id: Long): ExpenseDto = unsupported()
    override suspend fun rejectExpense(id: Long): ExpenseDto = unsupported()
    override suspend fun retryOcr(id: Long): ExpenseDto = unsupported()
    override suspend fun markNotDuplicate(id: Long): ExpenseDto = unsupported()
    override suspend fun expenseImage(id: Long): Response<ResponseBody> = unsupported()
    override suspend fun expenseThumbnail(id: Long): Response<ResponseBody> = unsupported()
    override suspend fun duplicates(): List<ExpenseDto> = unsupported()
    override suspend fun categoryRules(): List<CategoryRuleDto> = unsupported()
    override suspend fun createCategoryRule(request: CategoryRuleRequest): CategoryRuleDto = unsupported()
    override suspend fun updateCategoryRule(id: Long, request: CategoryRuleRequest): CategoryRuleDto = unsupported()
    override suspend fun deleteCategoryRule(id: Long): StatusDto = unsupported()
    override suspend fun merchantAliases(): MerchantAliasListDto = unsupported()
    override suspend fun createMerchantAlias(request: MerchantAliasRequest): MerchantAliasDto = unsupported()
    override suspend fun updateMerchantAlias(
        publicId: String,
        request: MerchantAliasRequest,
    ): MerchantAliasDto = unsupported()
    override suspend fun deleteMerchantAlias(publicId: String): StatusDto = unsupported()
    override suspend fun ruleApplications(limit: Int): RuleApplicationListDto = unsupported()
    override suspend fun rollbackRuleApplication(publicId: String): RuleApplicationRollbackDto = unsupported()
    override suspend fun applyConfirmedRules(
        request: RuleApplyConfirmedRequestDto,
        limit: Int,
        maxScan: Int,
    ): RuleApplyConfirmedResponseDto = unsupported()
    override suspend fun serverSettings(): ServerSettingsDto = unsupported()
    override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?): MonthlyStatsDto = unsupported()
    override suspend fun lifestyleStats(month: String?, timezone: String?): LifestyleStatsDto = unsupported()
    override suspend fun reportsOverview(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): ReportsOverviewDto = unsupported()
    override suspend fun reportsOverviewCsv(
        month: String?,
        granularity: String,
        topN: Int,
        merchantCategory: String?,
        rankingMetric: String,
        timezone: String?,
    ): Response<ResponseBody> = unsupported()
    override suspend fun goals(
        month: String?,
        includeArchived: Boolean,
        timezone: String?,
    ): GoalListResponseDto = unsupported()
    override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?): GoalDto = unsupported()
    override suspend fun goal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun updateGoal(
        publicId: String,
        request: GoalUpdateRequestDto,
        timezone: String?,
    ): GoalDto = unsupported()
    override suspend fun archiveGoal(publicId: String, timezone: String?): GoalDto = unsupported()
    override suspend fun dashboardCards(surface: String): DashboardCardsResponseDto = unsupported()
    override suspend fun updateDashboardCards(
        request: DashboardCardsUpdateRequestDto,
        surface: String,
    ): DashboardCardsResponseDto = unsupported()
    override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto = unsupported()
    override suspend fun updateMonthlyBudget(
        month: String,
        request: BudgetMonthlyUpdateRequestDto,
        timezone: String?,
    ): BudgetMonthlyDto = unsupported()
    override suspend fun recurringCandidates(timezone: String?): com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto = unsupported()
    override suspend fun recurringItems(
        status: String?,
        includeArchived: Boolean,
        month: String?,
        timezone: String?,
    ): RecurringItemListResponseDto = unsupported()
    override suspend fun confirmRecurringCandidate(
        request: RecurringCandidateConfirmRequestDto,
        timezone: String?,
    ): RecurringItemDto = unsupported()
    override suspend fun recurringItem(publicId: String, month: String?, timezone: String?): RecurringItemDto = unsupported()
    override suspend fun pauseRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun resumeRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun archiveRecurringItem(publicId: String): RecurringItemDto = unsupported()
    override suspend fun dataQualitySummary(): com.ticketbox.data.remote.dto.DataQualitySummaryDto = unsupported()
    override suspend fun getUiPreferences(): Response<UserUiPreferencesDto> = unsupported()
    override suspend fun putUiPreferences(
        request: UserUiPreferencesUpdateRequestDto,
    ): Response<UserUiPreferencesDto> = unsupported()
}

private class LedgerFakeSettingsStore : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null
    private var ledgerName: String? = null
    private var ledgersJson: String? = null
    private val ledgerIdFlow = MutableStateFlow<String?>(null)
    var capturedAccountName: String? = null
    var capturedDeviceName: String? = null
    var capturedRole: String? = null
    var capturedBoundAt: String? = null
    override fun serverUrl(): String? = serverUrl
    override fun appSkinKey(): String? = null
    override fun monthlyBudgetCents(): Long? = null
    override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit
    override fun lastConfirmedSyncAt(): String? = null
    override fun accountName(): String? = capturedAccountName
    override fun ledgerName(): String? = ledgerName
    override fun activeLedgerId(): String? = ledgerIdFlow.value
    override fun activeLedgerName(): String? = ledgerName
    override fun availableLedgersJson(): String? = ledgersJson
    override fun observeActiveLedgerId(): Flow<String?> = ledgerIdFlow
    override fun saveActiveLedger(ledgerId: String, ledgerName: String) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
    }
    override fun saveAvailableLedgersJson(json: String?) { ledgersJson = json }
    override fun deviceName(): String? = capturedDeviceName
    override fun role(): String? = capturedRole
    override fun boundAt(): String? = capturedBoundAt
    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        ledgerIdFlow.value = ledgerId
        this.ledgerName = ledgerName
        capturedAccountName = accountName
        capturedDeviceName = deviceName
        capturedRole = role
        capturedBoundAt = boundAt
    }
    override fun saveLastConfirmedSyncAt(value: String) = Unit
    override fun clearLastConfirmedSyncAt() = Unit
    override fun lastUploadAt(): String? = null
    override fun saveLastUploadAt(value: String) = Unit
    override fun saveAppSkinKey(skinKey: String) = Unit
    override fun currencyCodeKey(): String? = null
    override fun saveCurrencyCodeKey(currencyKey: String) = Unit
    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)
    override fun saveServerUrl(serverUrl: String) {
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }
    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()
    override fun markUnlocked() = Unit
    override fun markBackgrounded() = Unit
    override fun requiresUnlock(): Boolean = false
    override fun clear() {
        serverUrl = null; ledgerIdFlow.value = null; ledgerName = null; ledgersJson = null
    }
}

private class LedgerFakeTokenStore : SessionTokenStore {
    private var token: String? = null
    override fun saveToken(token: String) { this.token = token }
    override fun getToken(): String? = token
    override fun clear() { token = null }
}

private class LedgerFakeDao : ExpenseDao {
    private val map = linkedMapOf<Long, ExpenseEntity>()
    private val flows = mutableMapOf<String, MutableStateFlow<List<ExpenseEntity>>>()
    fun insertEntity(entity: ExpenseEntity) { map[entity.id] = entity }
    fun find(id: Long): ExpenseEntity? = map[id]
    override fun observeConfirmed(ledgerId: String): Flow<List<ExpenseEntity>> = flowFor(ledgerId)
    override suspend fun getConfirmed(ledgerId: String): List<ExpenseEntity> = map.values.filter { it.ledgerId == ledgerId }
    override suspend fun findByServerId(ledgerId: String, serverId: Long): ExpenseEntity? =
        map.values.firstOrNull { it.ledgerId == ledgerId && it.serverId == serverId }
    override suspend fun findByServerIds(ledgerId: String, serverIds: List<Long>): List<ExpenseEntity> =
        map.values.filter { it.ledgerId == ledgerId && it.serverId in serverIds.toSet() }
    override suspend fun confirmedServerIdsForLedger(ledgerId: String): List<Long> =
        map.values.filter { it.ledgerId == ledgerId && it.status == "confirmed" }.map { it.serverId }
    override suspend fun insert(expense: ExpenseEntity): Long {
        map[expense.id] = expense
        return expense.id
    }
    override suspend fun insertAll(expenses: List<ExpenseEntity>): List<Long> = expenses.map { insert(it) }
    override suspend fun update(expense: ExpenseEntity) { map[expense.id] = expense }
    override suspend fun updateAll(expenses: List<ExpenseEntity>) { expenses.forEach { update(it) } }
    override suspend fun clear() { map.clear() }
    override suspend fun clearForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun deleteConfirmedForLedger(ledgerId: String) {
        val ids = map.values.filter { it.ledgerId == ledgerId && it.status == "confirmed" }.map { it.id }
        ids.forEach { map.remove(it) }
    }
    override suspend fun deleteConfirmedByServerIds(ledgerId: String, serverIds: List<Long>) {
        val remove = serverIds.toSet()
        val ids = map.values
            .filter { it.ledgerId == ledgerId && it.status == "confirmed" && it.serverId in remove }
            .map { it.id }
        ids.forEach { map.remove(it) }
    }
    private fun flowFor(ledgerId: String): MutableStateFlow<List<ExpenseEntity>> =
        flows.getOrPut(ledgerId) { MutableStateFlow(emptyList()) }
}

private fun unsupported(): Nothing = error("Unexpected API call")

private fun ledgerEntity(id: Long, ledgerId: String, serverId: Long): ExpenseEntity = ExpenseEntity(
    id = id,
    ledgerId = ledgerId,
    serverId = serverId,
    publicId = "p-$id",
    amountCents = 100,
    merchant = "m",
    category = "其他",
    note = null,
    source = "manual",
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = null,
    createdAt = "2026-01-01T00:00:00Z",
    confirmedAt = null,
    updatedAt = null,
)
