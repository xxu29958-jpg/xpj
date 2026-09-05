package com.ticketbox.data.repository

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.RepositoryGraph
import com.ticketbox.RepositoryGraphDependencies
import com.ticketbox.RepositoryGraphOutbox
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import java.io.IOException
import java.lang.reflect.Proxy
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real production composition and on-disk Room; only session and network IO are synthetic. */
@RunWith(AndroidJUnit4::class)
class DebtCreationRoomContinuityTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val databaseName = "debt-create-continuity.db"
    private var database: AppDatabase? = null
    private var networkCreates = 0

    @After
    fun closeFixture() {
        database?.close()
        context.deleteDatabase(databaseName)
    }

    @Test
    fun saveKeepsOriginalIntentAcrossRoomCloseAndReopenBeforeAnyNetworkCreate() = runBlocking {
        val session = sessionRecord("owner")
        val firstDatabase = reopenDatabase()
        val graph = repositoryGraph(firstDatabase, session)

        val result = graph.debtRepository.createDebt(draft())

        val stored = storedRows(firstDatabase)
        assertEquals("Save must publish one durable intent", 1, stored.size)
        assertTrue("Local acceptance does not depend on network availability", result.isSuccess)
        assertEquals("The durable queue, not Save, sends the request", 0, networkCreates)
        val original = stored.single()
        assertEquals("create_debt", original.getValue("type"))
        assertEquals(session.identity.ledgerId, original.getValue("ledgerId"))
        assertEquals(session.toOutboxBinding().ownerStorageKey, original.getValue("ownerKey"))
        assertTrue(requireNotNull(original["idempotencyKey"]).isNotBlank())

        val restartedDatabase = reopenDatabase()
        assertEquals(stored, storedRows(restartedDatabase))
        val restartedOutbox = outbox(restartedDatabase, session)
        val resumed = restartedOutbox.dequeueNextRunnable().single()
        assertEquals(original.getValue("idempotencyKey"), resumed.idempotencyKey)
        assertEquals(original.getValue("payload"), resumed.payloadJson)
        assertEquals(original.getValue("ownerKey"), resumed.ownerKey)
        assertEquals(0, networkCreates)
    }

    @Test
    fun viewerCannotPublishAnIntentOrSendTheCreate() = runBlocking {
        val currentDatabase = reopenDatabase()
        val graph = repositoryGraph(currentDatabase, sessionRecord("viewer"))

        val result = graph.debtRepository.createDebt(draft())

        assertTrue(result.isFailure)
        assertTrue(storedRows(currentDatabase).isEmpty())
        assertEquals(0, networkCreates)
    }

    private fun reopenDatabase(): AppDatabase {
        database?.close()
        return Room.databaseBuilder(context, AppDatabase::class.java, databaseName)
            .build()
            .also { database = it }
    }

    private fun outbox(database: AppDatabase, session: LocalSessionRecord) = OutboxRepository(
        dao = database.pendingMutationDao(),
        bindingProvider = { session.toOutboxBinding() },
    )

    private fun repositoryGraph(database: AppDatabase, session: LocalSessionRecord): RepositoryGraph {
        val sessions = fixtureProxy<LocalSessionStore> { method ->
            when (method) {
                "currentSession" -> session
                "observeSession" -> flowOf(session)
                "hasPersistedSessionState" -> true
                else -> error("Unexpected session call: $method")
            }
        }
        val service = fixtureProxy<ApiService> { method ->
            check(method == "createDebt") { "Unexpected network call: $method" }
            networkCreates += 1
            throw IOException("Synthetic interrupted create")
        }
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
        }
        val credentials = SessionCredentialAdapter(sessions)
        return RepositoryGraph(
            RepositoryGraphDependencies(
                database = database,
                apiClient = ApiClient(),
                settingsStore = fixtureProxy<TicketboxSettingsStore> { error("Unexpected settings call: $it") },
                sessionStore = sessions,
                credentials = credentials,
                apiServiceProvider = ApiServiceProvider(factory, sessions, credentials),
                outbox = RepositoryGraphOutbox(outbox(database, session), OutboxAdapterGraph()),
            ),
        )
    }

    private fun storedRows(database: AppDatabase): List<Map<String, String?>> =
        database.openHelper.readableDatabase.query("SELECT * FROM pending_mutations ORDER BY id").use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(cursor.columnNames.mapIndexed { index, name -> name to cursor.getString(index) }.toMap())
                }
            }
        }

    private fun draft() = DebtDraft(
        direction = DebtDirections.OWED_TO_ME,
        counterpartyLabel = "小王",
        principalAmountCents = 12_345L,
        note = "出差垫付车费",
    )

    private fun sessionRecord(role: String) = LocalSessionRecord(
        sessionGeneration = "debt-create-session",
        bindingRevision = "debt-create-binding",
        serverId = "30000000-0000-4000-8000-000000000001",
        dataGeneration = "30000000-0000-4000-8000-000000000002",
        serverUrl = "https://debt.example.test",
        credential = StoredSessionToken(token = "synthetic-debt-session"),
        identity = LocalSessionIdentity(
            accountPublicId = "30000000-0000-4000-8000-000000000003",
            devicePublicId = "30000000-0000-4000-8000-000000000004",
            accountName = "测试成员",
            ledgerId = "debt-ledger",
            ledgerName = "测试账本",
            deviceName = "测试设备",
            role = role,
            boundAt = "2026-09-06T00:00:00Z",
        ),
    )
}

private inline fun <reified T> fixtureProxy(crossinline answer: (String) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, _ ->
        answer(method.name)
    } as T
