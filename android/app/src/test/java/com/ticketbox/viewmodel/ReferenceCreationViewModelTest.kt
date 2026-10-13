package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.remote.dto.ReferenceCreatedDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ReferenceCreationActions
import com.ticketbox.data.repository.ReferenceKind
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class ReferenceCreationViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val original = LogicalSessionBinding("https://example.test", "ledger", "original-owner", "session", "binding")
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun close() { Dispatchers.resetMain() }

    @Test fun lostReceiptAndProcessRestorationReplayOnlyTheOriginalNameAndKey() = runTest(dispatcher) {
        for (kind in ReferenceKind.entries) {
            val remote = Remote(kind)
            val handle = SavedStateHandle()
            val first = ReferenceCreationViewModel(remote, handle)
            advanceUntilIdle()
            first.open(); first.updateName("  暑期旅行  "); first.submit()
            advanceUntilIdle()
            val key = requireNotNull(first.state.value.draft).key
            assertEquals("unconfirmed", first.state.value.draft?.phase)
            first.updateName("不能改写未知结果")
            val restored = ReferenceCreationViewModel(remote, SavedStateHandle(handle.keys().associateWith { handle.get<Any>(it) }))
            advanceUntilIdle()
            assertEquals("  暑期旅行  ", restored.state.value.draft?.name)
            restored.submit(); advanceUntilIdle()
            assertEquals(listOf(key, key), remote.calls.map { it.third })
            assertEquals(listOf("  暑期旅行  ", "  暑期旅行  "), remote.calls.map { it.second })
            assertEquals(1, remote.accepted.size)
            assertEquals("accepted", restored.state.value.draft?.phase)
            restored.submit(); advanceUntilIdle()
            assertEquals(2, remote.calls.size)
            restored.consumeReceipt(key)
            assertNull(restored.state.value.draft)
        }
    }

    @Test fun roleWithdrawalKeepsRawInputAndCannotPublishUntilWriterReturns() = runTest(dispatcher) {
        val remote = Remote()
        val vm = ReferenceCreationViewModel(remote)
        advanceUntilIdle(); vm.open(); vm.updateName("  原草稿  ")
        val key = vm.state.value.draft?.key
        remote.access.value = LedgerAccessContext(original, false)
        advanceUntilIdle(); vm.updateName("覆盖"); vm.submit(); advanceUntilIdle()
        assertFalse(vm.state.value.canModify)
        assertEquals("  原草稿  ", vm.state.value.draft?.name)
        assertTrue(remote.calls.isEmpty())
        remote.access.value = LedgerAccessContext(original, true)
        advanceUntilIdle(); vm.submit(); advanceUntilIdle()
        assertEquals(key, remote.calls.single().third)
    }

    @Test fun reauthenticationNeedsExplicitReviewAndRetainsOriginalUncertainCommand() = runTest(dispatcher) {
        val remote = Remote()
        val vm = ReferenceCreationViewModel(remote)
        advanceUntilIdle(); vm.open(); vm.updateName("旅行"); vm.submit(); advanceUntilIdle()
        val originalCall = remote.calls.single()
        val renewed = original.copy(sessionGeneration = "renewed", bindingRevision = "reviewed")
        remote.access.value = LedgerAccessContext(renewed, true)
        advanceUntilIdle(); vm.submit(); advanceUntilIdle()
        assertTrue(vm.state.value.bindingChanged)
        assertEquals(1, remote.calls.size)
        vm.reviewIdentity(); vm.submit(); advanceUntilIdle()
        assertEquals(renewed, remote.calls.last().first)
        assertEquals(originalCall.second, remote.calls.last().second)
        assertEquals(originalCall.third, remote.calls.last().third)
        assertEquals(1, remote.accepted.size)
    }

    @Test fun otherAccountLedgerOrServerCannotReadOrAdoptTheOriginalDraft() = runTest(dispatcher) {
        val remote = Remote()
        val vm = ReferenceCreationViewModel(remote)
        advanceUntilIdle(); vm.open(); vm.updateName("个人原稿")
        val key = vm.state.value.draft?.key
        for (other in listOf(original.copy(ownerKey = "another-owner"), original.copy(ledgerId = "another-ledger"),
            original.copy(serverUrl = "https://another.test"))) {
            remote.access.value = LedgerAccessContext(other, true)
            advanceUntilIdle(); vm.reviewIdentity(); vm.submit(); advanceUntilIdle()
            assertNull(vm.state.value.draft)
            assertTrue(remote.calls.isEmpty())
        }
        remote.access.value = LedgerAccessContext(original, true)
        advanceUntilIdle()
        assertEquals(key, vm.state.value.draft?.key)
        assertEquals("个人原稿", vm.state.value.draft?.name)
    }

    @Test fun definiteDuplicateRefusalRequiresExplicitNewIntentBeforeEditing() = runTest(dispatcher) {
        val remote = Remote().apply { refuse = true }
        val vm = ReferenceCreationViewModel(remote)
        advanceUntilIdle(); vm.open(); vm.updateName("已有名称"); vm.submit(); advanceUntilIdle()
        val key = vm.state.value.draft?.key
        assertEquals("rejected", vm.state.value.draft?.phase)
        vm.updateName("悄悄换名"); vm.submit(); advanceUntilIdle()
        assertEquals("已有名称", vm.state.value.draft?.name)
        assertEquals(1, remote.calls.size)
        vm.reviewRejected()
        assertNotEquals(key, vm.state.value.draft?.key)
        assertEquals("已有名称", vm.state.value.draft?.name)
        vm.updateName("另一个名称"); remote.refuse = false; vm.submit(); advanceUntilIdle()
        assertEquals("另一个名称", remote.calls.last().second)
    }

    private inner class Remote(override val kind: ReferenceKind = ReferenceKind.Tag) : ReferenceCreationActions {
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(original, true))
        val calls = mutableListOf<Triple<LogicalSessionBinding, String, String>>()
        val accepted = mutableMapOf<String, ReferenceCreatedDto>()
        var refuse = false
        override fun observeAccess() = access
        override suspend fun create(binding: LogicalSessionBinding, name: String, key: String): Result<ReferenceCreatedDto> {
            calls += Triple(binding, name, key)
            if (refuse) return Result.failure(RepositoryException("已有同名对象", errorCode = "reference_name_conflict"))
            accepted[key]?.let { return Result.success(it) }
            accepted[key] = ReferenceCreatedDto(kind.wire, "00000000-0000-0000-0000-000000000001", name.trim(), 1)
            return Result.failure(RepositoryException("回执暂时不可达"))
        }
    }
}
