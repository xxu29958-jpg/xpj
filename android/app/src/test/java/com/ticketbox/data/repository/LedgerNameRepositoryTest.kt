package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerRenameRequestDto
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.viewmodel.LedgerSwitcherViewModel
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
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class LedgerNameRepositoryTest {
    @Test
    fun renameChangesOnlyCurrentLabelAndPreservesCachedFactsAndBinding() = runTest {
        val h = Harness()
        val target = h.repository.refreshLedgers().getOrThrow().first()
        val before = requireNotNull(h.session.sessionStore.currentSession())
        val binding = requireNotNull(h.repository.currentBinding())
        val saved = h.repository.renameLedger(binding, target, "  我们的家  ").getOrThrow()
        val after = requireNotNull(h.session.sessionStore.currentSession())
        assertEquals(before.copy(identity = before.identity.copy(ledgerName = "我们的家")), after)
        assertEquals("我们的家", saved.name)
        assertEquals(binding, h.repository.currentBinding())
        assertEquals("我们的家", h.repository.cachedLedgers().first().name)
        assertNotNull(h.dao.find(1))
        assertEquals("owner" to LedgerRenameRequestDto("我们的家", "家庭"), h.calls.single())
    }

    @Test
    fun anotherOwnedLedgerCanBeRenamedWithoutSwitchingOrRestoringOldRole() = runTest {
        val h = Harness()
        val rows = h.repository.refreshLedgers().getOrThrow()
        val binding = requireNotNull(h.repository.currentBinding())
        val before = requireNotNull(h.session.sessionStore.currentSession())
        h.repository.renameLedger(binding, rows.last(), "新的旅行账本").getOrThrow()
        assertEquals(before, h.session.sessionStore.currentSession())
        h.beforeReply = {
            val current = requireNotNull(h.session.sessionStore.currentSession())
            h.session.sessionStore.replaceForFixture(current.copy(identity = current.identity.copy(role = "viewer")))
        }
        h.repository.renameLedger(binding, rows.first(), "新的家庭名称").getOrThrow()
        assertEquals("viewer", h.session.sessionStore.currentSession()?.identity?.role)
        assertEquals("新的家庭名称", h.session.sessionStore.currentSession()?.identity?.ledgerName)
    }

    @Test
    fun refreshingRemoteNamesUpdatesTheCurrentProjectionWithoutClearingFacts() = runTest {
        val h = Harness()
        h.rows = h.rows.map { it.copy(name = "远端新名称") }
        val binding = h.repository.currentBinding()
        h.repository.refreshLedgers().getOrThrow()
        assertEquals("远端新名称", h.repository.currentLedgerName())
        assertEquals(binding, h.repository.currentBinding())
        assertNotNull(h.dao.find(1))
    }

    @Test
    fun offlineDraftIsKeptUntilAnExplicitSuccessfulRetry() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val h = Harness()
            val vm = h.loadedViewModel()
            vm.beginRename(vm.uiState.value.ledgers.first())
            vm.changeRenameName("断网也保留")
            h.offline = true
            var saved = 0
            vm.saveRename { saved++ }
            val failed = vm.uiState.first { !it.loading && it.messageTone == MessageTone.Danger }
            assertEquals("断网也保留", failed.rename?.name)
            assertEquals("家庭", h.repository.currentLedgerName())
            assertEquals(0, saved)
            h.offline = false
            vm.saveRename { saved++ }
            val accepted = vm.uiState.first { !it.loading && it.messageTone == MessageTone.Success }
            assertNull(accepted.rename)
            assertEquals("断网也保留", accepted.ledgers.first().name)
            assertEquals(1, saved)
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun conflictShowsTheNewNameBesideTheDraftAndDoesNotResubmitAutomatically() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val h = Harness()
            val vm = h.loadedViewModel()
            vm.beginRename(vm.uiState.value.ledgers.first())
            vm.changeRenameName("手机输入")
            h.rows = h.rows.map { it.copy(name = "电脑已经改名") }
            vm.saveRename {}
            val conflict = vm.uiState.first { !it.loading && it.messageTone == MessageTone.Danger }
            assertEquals("手机输入", conflict.rename?.name)
            assertEquals("电脑已经改名", conflict.rename?.ledger?.name)
            assertEquals(1, h.calls.size)
            vm.saveRename {}
            vm.uiState.first { !it.loading && it.messageTone == MessageTone.Success }
            assertEquals("电脑已经改名", h.calls.last().second.expectedName)
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun failedConflictReloadBlocksSavingAndPermissionLossKeepsTheDraftReadOnly() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try {
            val h = Harness()
            val vm = h.loadedViewModel()
            vm.beginRename(vm.uiState.value.ledgers.first())
            vm.changeRenameName("保留输入")
            h.rows = h.rows.map { it.copy(name = "别处更新", role = "viewer") }
            h.failConflictReload = true
            vm.saveRename {}
            val failed = vm.uiState.first { !it.loading && it.messageTone == MessageTone.Danger }
            assertFalse(requireNotNull(failed.rename).fresh)
            vm.saveRename {}
            assertEquals(1, h.calls.size)
            h.offline = false
            vm.refresh()
            val refreshed = vm.uiState.first { !it.loading }
            assertFalse(requireNotNull(refreshed.rename).fresh)
            assertEquals("保留输入", refreshed.rename?.name)
            vm.saveRename {}
            assertEquals(1, h.calls.size)
        } finally { Dispatchers.resetMain() }
    }

    @Test
    fun aNewSessionDoesNotReceiveTheOldResponseOrTheOldFormSubmission() = runTest {
        val h = Harness()
        val target = h.repository.refreshLedgers().getOrThrow().first()
        val binding = requireNotNull(h.repository.currentBinding())
        h.beforeReply = { h.session.rebindAsDifferentAccountForFixture("另一人", "other", "另一账本", "新手机", "new-token") }
        assertTrue(h.repository.renameLedger(binding, target, "旧页面").isFailure)
        assertEquals("另一账本", h.repository.currentLedgerName())
        val count = h.calls.size
        assertTrue(h.repository.renameLedger(binding, target, "旧页面再试").isFailure)
        assertEquals(count, h.calls.size)
    }

    private class Harness {
        val session = ledgerSessionFixture("owner", "家庭", role = "owner")
        val settings = LedgerFakeSettingsStore()
        val dao = LedgerFakeDao().apply { insertEntity(ledgerEntity(1, "owner", 10)) }
        var rows = listOf(LedgerDto("owner", "家庭", "owner", true, null, null),
            LedgerDto("travel", "旅行", "owner", false, null, null))
        val calls = mutableListOf<Pair<String, LedgerRenameRequestDto>>()
        var offline = false
        var failConflictReload = false
        var beforeReply: () -> Unit = {}
        private val api = object : ApiService by StubApi() {
            override suspend fun listLedgers(): LedgerListResponseDto {
                if (offline) throw IOException("Offline")
                return LedgerListResponseDto(rows)
            }
            override suspend fun renameLedger(ledgerId: String, request: LedgerRenameRequestDto): LedgerDto {
                if (offline) throw IOException("Offline")
                calls += ledgerId to request
                val current = rows.first { it.ledgerId == ledgerId }
                if (current.name != request.expectedName && current.name != request.name) {
                    if (failConflictReload) offline = true
                    throw HttpException(Response.error<LedgerDto>(409,
                        """{"error":"ledger_name_conflict","message":"名称已更新，请核对后重新保存。"}""".toResponseBody("application/json".toMediaType())))
                }
                val saved = current.copy(name = request.name)
                rows = rows.map { if (it.ledgerId == ledgerId) saved else it }
                beforeReply()
                return saved
            }
        }
        val repository = testLedgerRepository(LedgerStubApiFactory(api), settings, session, dao)
        suspend fun loadedViewModel(): LedgerSwitcherViewModel {
            val vm = LedgerSwitcherViewModel(repository)
            vm.refresh()
            vm.uiState.first { !it.loading && it.ledgers.isNotEmpty() }
            return vm
        }
    }
}
