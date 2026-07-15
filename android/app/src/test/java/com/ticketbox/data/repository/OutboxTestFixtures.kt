package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import kotlinx.coroutines.flow.Flow
import java.time.Clock

internal fun testOutboxBinding(
    serverUrl: String = "https://api.example.com",
    ledgerId: String = "owner",
    owner: OutboxOwnerIdentity = requireNotNull(
        OutboxOwnerIdentity.fromOrNull(
            serverId = TEST_SERVER_ID,
            dataGeneration = TEST_DATA_GENERATION,
            accountPublicId = TEST_ACCOUNT_PUBLIC_ID,
            devicePublicId = TEST_DEVICE_PUBLIC_ID,
        ),
    ),
): OutboxBinding = OutboxBinding(
    serverUrl = serverUrl,
    ledgerId = ledgerId,
    owner = owner,
)

internal fun testOutboxRepository(
    dao: PendingMutationDao,
    clock: Clock = Clock.systemUTC(),
    onEnqueued: () -> Unit = {},
    onClearAll: () -> Unit = {},
): OutboxRepository = OutboxRepository(
    dao = dao,
    clock = clock,
    bindingProvider = ::testOutboxBinding,
    onEnqueued = onEnqueued,
    onClearAll = onClearAll,
)

internal fun testOutboxRepository(
    dao: PendingMutationDao,
    bindingProvider: () -> OutboxBinding,
    clock: Clock = Clock.systemUTC(),
    bindingChanges: Flow<OutboxBinding>? = null,
    onClearAll: () -> Unit = {},
): OutboxRepository = OutboxRepository(
    dao = dao,
    clock = clock,
    bindingProvider = bindingProvider,
    bindingChanges = bindingChanges,
    onClearAll = onClearAll,
)
