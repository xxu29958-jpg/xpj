package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import java.net.ConnectException
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

internal class RecurringSharedConsumerReadTest : ExpensePendingRepositoryOutboxTestBase() {
    @Test fun planOverviewAndDefinitionPageCanReadTogetherWithoutFailingEachOther() = runTest {
        for (overviewReturnsLast in listOf(false, true)) {
            val started = List(2) { CompletableDeferred<Unit>() }
            val release = List(2) { CompletableDeferred<Unit>() }
            val calls = AtomicInteger()
            var offline = false
            val fixture = GoalReadFixture(decorate = { delegate -> object : ApiService by delegate {
                override suspend fun recurringItems(status: String?, includeArchived: Boolean,
                    month: String?, timezone: String?): RecurringItemListResponseDto {
                    if (offline) throw ConnectException("offline after both consumers read")
                    val call = calls.getAndIncrement()
                    started[call].complete(Unit)
                    release[call].await()
                    return RecurringItemListResponseDto(listOf(recurringReadItem().copy(
                        rowVersion = 9L + call, baselineAmountCents = 2400L + call * 100)))
                }
            } })
            val reader = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            val overview = async { reader.items(fixture.binding, null, true, null) }
            started[0].await()
            val definitions = async { reader.items(fixture.binding, null, true, null) }
            started[1].await()
            val first = if (overviewReturnsLast) 1 else 0
            release[first].complete(Unit)
            if (overviewReturnsLast) definitions.await() else overview.await()
            release[1 - first].complete(Unit)
            val overviewRead = overview.await().getOrThrow()
            val definitionsRead = definitions.await().getOrThrow()
            assertEquals(9L, overviewRead.value.single().rowVersion)
            assertEquals(10L, definitionsRead.value.single().rowVersion)
            offline = true
            val reopened = RecurringQueryReader(fixture.provider, fixture.dao, fixture.coordinator)
            assertEquals(definitionsRead.copy(fromCache = true),
                reopened.items(fixture.binding, null, true, null).getOrThrow(),
                "A late overview response must not replace the definition page's newer saved read")
        }
    }
}
