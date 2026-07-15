package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.InvitationAcceptResponseDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class LedgerRepositoryInvitationOutboxTest {
    @Test
    fun boundInvitationPreservesSessionPrincipalAndOldLedgerIntent() = runTest {
        val api = StubApi(
            LedgerStubApiState(
                acceptResult = acceptedFamilyLedger(),
                listLedgersResult = LedgerListResponseDto(emptyList()),
            ),
        )
        val settings = LedgerFakeSettingsStore()
        val session = existingOwnerSessionFixture(
            ledgerId = "personal",
            ledgerName = "个人账本",
            accountName = "我",
            deviceName = "Pixel",
            token = "stable-token",
        )
        val beforeSession = requireNotNull(session.sessionStore.currentSession())
        val apiFactory = LedgerStubApiFactory(api)
        val apiProvider = testApiServiceProvider(apiFactory, session)
        val mutationDao = FakePendingMutationDao()
        val outbox = testOutboxRepository(
            dao = mutationDao,
            bindingProvider = {
                apiProvider.currentSession().toOutboxBinding()
            },
        )
        val expenseDao = LedgerFakeDao()
        val coordinator = LocalLedgerSessionCoordinator(
            settingsStore = settings,
            sessionStore = session.sessionStore,
            expenseDao = expenseDao,
            outbox = outbox,
        )
        val repository = LedgerRepository(
            settingsStore = settings,
            expenseDao = expenseDao,
            sessionStore = session.sessionStore,
            apiProvider = apiProvider,
            sessionCoordinator = coordinator,
        )
        val rowId = outbox.enqueue(
            PendingMutationType.CreateExpense,
            "expense:local:before-join",
            "{}",
            0L,
        )
        val ownerBefore = mutationDao.rows.getValue(rowId).ownerKey

        repository.acceptInvitation("inv_family", "ignored", "ignored").getOrThrow()

        val afterSession = requireNotNull(session.sessionStore.currentSession())
        val preserved = mutationDao.rows[rowId]
        assertNotNull(preserved)
        assertEquals(beforeSession.sessionGeneration, afterSession.sessionGeneration)
        assertEquals(beforeSession.identity.accountPublicId, afterSession.identity.accountPublicId)
        assertEquals(beforeSession.identity.devicePublicId, afterSession.identity.devicePublicId)
        assertEquals(ownerBefore, preserved.ownerKey)
        assertEquals("personal", preserved.ledgerId)
        assertTrue(outbox.dequeueNextRunnable().isEmpty())
    }

    private fun acceptedFamilyLedger() = InvitationAcceptResponseDto(
        sessionToken = "stable-token",
        serverId = TEST_SERVER_ID,
        dataGeneration = TEST_DATA_GENERATION,
        accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
        devicePublicId = TEST_DEVICE_PUBLIC_ID,
        accountName = "我",
        ledgerId = "family",
        ledgerName = "家庭账本",
        deviceName = "Pixel",
        role = "member",
    )
}
