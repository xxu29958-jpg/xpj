package com.ticketbox.data.repository

import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.AccountProfileDto
import com.ticketbox.data.remote.dto.AccountProfileRenameDto
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.viewmodel.AccountProfileViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class AccountProfileRepositoryTest {
    @Test
    fun viewerRenamePreservesIdentityCredentialsCacheAndBindingRevision() = runTest {
        val h = Harness()
        val before = requireNotNull(h.session.sessionStore.currentSession())
        val binding = requireNotNull(h.repository.currentBinding())
        val saved = h.repository.rename(binding, " 家里的我 ", "我").getOrThrow()
        val after = requireNotNull(h.session.sessionStore.currentSession())
        assertEquals("家里的我", saved.displayName)
        assertEquals(before.copy(identity = before.identity.copy(accountName = "家里的我")), after)
        assertEquals(binding, h.repository.currentBinding())
        assertNotNull(h.dao.find(1))
        assertEquals(AccountProfileRenameDto("家里的我", "我"), h.sent.single())
    }

    @Test
    fun nameReplyPreservesARoleProjectionThatChangedWhileTheRequestWasPending() = runTest {
        val h = Harness()
        h.beforeReply = {
            val current = requireNotNull(h.session.sessionStore.currentSession())
            h.session.sessionStore.replaceForFixture(current.copy(identity = current.identity.copy(role = "member")))
        }
        h.repository.rename(requireNotNull(h.repository.currentBinding()), "新名称", "我").getOrThrow()
        val current = requireNotNull(h.session.sessionStore.currentSession())
        assertEquals("member", current.identity.role)
        assertEquals("新名称", current.identity.accountName)
    }

    @Test
    fun offlineFailureKeepsDraftAndOnlyAnAcknowledgedRetryShowsSaved() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val h = Harness()
            val vm = AccountProfileViewModel(h.repository)
            vm.refresh()
            vm.uiState.first { !it.busy && it.fresh }
            vm.changeName("没有丢掉的输入")
            h.offline = true
            vm.save()
            val failed = vm.uiState.first { !it.busy && it.message != null }
            assertEquals("没有丢掉的输入", failed.name)
            assertEquals(MessageTone.Danger, failed.tone)
            assertEquals("我", h.session.sessionStore.currentSession()?.identity?.accountName)
            h.offline = false
            vm.save()
            val saved = vm.uiState.first { !it.busy && it.tone == MessageTone.Success }
            assertEquals(UiText.res(R.string.account_profile_saved), saved.message)
            assertEquals("没有丢掉的输入", h.name)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun conflictingNameIsShownWithoutErasingOrResubmittingTheDraft() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val h = Harness()
            val vm = AccountProfileViewModel(h.repository)
            vm.refresh()
            vm.uiState.first { !it.busy && it.fresh }
            vm.changeName("手机中输入的名称")
            h.name = "Web 已经保存"
            vm.save()
            val conflicted = vm.uiState.first { !it.busy && it.message != null }
            assertEquals("手机中输入的名称", conflicted.name)
            assertEquals("Web 已经保存", conflicted.profile?.displayName)
            assertEquals(MessageTone.Danger, conflicted.tone)
            assertEquals(1, h.sent.size)
            vm.save()
            vm.uiState.first { !it.busy && it.tone == MessageTone.Success }
            assertEquals("Web 已经保存", h.sent.last().expectedName)
            assertEquals("手机中输入的名称", h.name)
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun sessionChangeRetiresTheOldReplyAndPreventsDraftSubmissionToNewAccount() = runTest {
        val h = Harness()
        val binding = requireNotNull(h.repository.currentBinding())
        h.beforeReply = {
            h.session.rebindAsDifferentAccountForFixture("另一人", "other", "另一个账本", "另一设备", "other-token")
        }
        assertTrue(h.repository.rename(binding, "旧页面名称", "我").isFailure)
        val current = requireNotNull(h.session.sessionStore.currentSession())
        assertEquals("另一人", current.identity.accountName)
        assertEquals("other-token", current.credential.token)
        val requests = h.sent.size
        assertTrue(h.repository.rename(binding, "再次提交", "我").isFailure)
        assertEquals(requests, h.sent.size)
    }

    @Test
    fun conflictWithFailedReloadRequiresAnExplicitRefreshBeforeSavingAgain() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val h = Harness()
            val vm = AccountProfileViewModel(h.repository)
            vm.refresh()
            vm.uiState.first { !it.busy && it.fresh }
            vm.changeName("保留输入")
            h.name = "别处修改"
            h.failConflictReload = true
            vm.save()
            val failed = vm.uiState.first { !it.busy && it.message != null }
            assertFalse(failed.fresh)
            assertEquals("保留输入", failed.name)
            vm.save()
            assertEquals(1, h.sent.size)
            h.offline = false
            vm.refresh()
            val refreshed = vm.uiState.first { !it.busy && it.fresh }
            assertEquals("保留输入", refreshed.name)
            assertEquals("别处修改", refreshed.profile?.displayName)
        } finally {
            Dispatchers.resetMain()
        }
    }

    private class Harness {
        val session = ledgerSessionFixture("owner", "家庭账本", role = "viewer")
        val dao = LedgerFakeDao().apply { insertEntity(ledgerEntity(1, "owner", 10)) }
        val sent = mutableListOf<AccountProfileRenameDto>()
        var name = "我"
        var offline = false
        var failConflictReload = false
        var beforeReply: () -> Unit = {}
        private val api = object : ApiService by StubApi() {
            override suspend fun accountProfile(): AccountProfileDto {
                if (offline) throw IOException("Offline")
                return AccountProfileDto(TEST_ACCOUNT_PUBLIC_ID, name)
            }

            override suspend fun renameAccountProfile(request: AccountProfileRenameDto): AccountProfileDto {
                if (offline) throw IOException("Offline")
                sent += request
                if (name != request.expectedName && name != request.displayName) {
                    if (failConflictReload) offline = true
                    throw HttpException(Response.error<AccountProfileDto>(409,
                        """{"error":"conflict","message":"账号名称已在另一处修改"}""".toResponseBody("application/json".toMediaType())))
                }
                name = request.displayName
                beforeReply()
                return AccountProfileDto(TEST_ACCOUNT_PUBLIC_ID, name)
            }
        }
        val repository = AccountProfileRepository(testApiServiceProvider(LedgerStubApiFactory(api), session),
            LocalLedgerSessionCoordinator(LedgerFakeSettingsStore(), session.sessionStore, dao))
    }
}
