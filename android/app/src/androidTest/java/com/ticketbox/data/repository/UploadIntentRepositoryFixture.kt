package com.ticketbox.data.repository

import android.content.Context
import android.content.ContextWrapper
import androidx.room.Room
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import com.ticketbox.upload.PreparedUploadImage
import java.io.Closeable
import java.io.File
import java.io.IOException
import java.lang.reflect.Proxy
import java.nio.file.Files
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map

/** Real private files and disk Room; the only write fault is thrown after the real Room commit. */
internal class UploadIntentRepositoryFixture : Closeable {
    private val base = InstrumentationRegistry.getInstrumentation().targetContext
    private val directory = Files.createTempDirectory(base.cacheDir.toPath(), "upload-repository-test-").toFile()
    private val databaseName = "upload-repository-${UUID.randomUUID()}.db"
    private val context = object : ContextWrapper(base) {
        override fun getApplicationContext(): Context = this
        override fun getFilesDir(): File = directory
    }
    private var database = openDatabase()
    val session = MutableStateFlow(repositoryUploadSession())
    val adapters = OutboxAdapterGraph()
    var availableBytes: Long? = null
    var fileStore = UploadIntentFileStore(context) { availableBytes ?: it.usableSpace }
        private set
    val savedTimestamps = mutableListOf<Pair<String, String>>()
    private val timestamps = mutableMapOf<String, String>()
    var loseNextInsertAcknowledgement = false
    var failNextTimestampWrite = false
    var scheduled = 0
    var apiCalls = 0
    val dao: PendingMutationDao get() = database.pendingMutationDao()
    lateinit var outbox: OutboxRepository
        private set
    var repository: UploadIntentRepository = newRepository()
        private set

    private fun openDatabase(): AppDatabase = Room.databaseBuilder(context, AppDatabase::class.java, databaseName).build()

    private fun newRepository(): UploadIntentRepository {
        val actualDao = dao
        val interceptedDao = object : PendingMutationDao by actualDao {
            override suspend fun insertBatch(rows: List<PendingMutationEntity>): List<Long> {
                val ids = actualDao.insertBatch(rows)
                if (loseNextInsertAcknowledgement) {
                    loseNextInsertAcknowledgement = false
                    throw IOException("Synthetic acknowledgement lost after Room commit")
                }
                return ids
            }
        }
        val sessions = repositoryUploadProxy<LocalSessionStore> { method, _ -> when (method) {
            "currentSession" -> session.value
            "observeSession" -> session
            else -> error("Unexpected session method: $method")
        } }
        val settings = repositoryUploadProxy<TicketboxSettingsStore> { method, args -> when (method) {
            "lastUploadAtForLedger" -> timestamps[args[0] as String]
            "saveLastUploadAtForLedger" -> {
                if (failNextTimestampWrite) {
                    failNextTimestampWrite = false
                    error("Synthetic derived setting write failed")
                }
                val pair = (args[0] as String) to (args[1] as String)
                timestamps[pair.first] = pair.second
                savedTimestamps += pair
                Unit
            }
            else -> error("Unexpected settings method: $method")
        } }
        val transport = repositoryUploadProxy<ApiService> { _, _ ->
            apiCalls++
            error("The upload repository must never send HTTP")
        }
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = transport
        }
        val provider = ApiServiceProvider(factory, sessions, SessionCredentialAdapter(sessions))
        outbox = OutboxRepository(interceptedDao, Clock.fixed(Instant.parse(NOW), ZoneOffset.UTC),
            bindingProvider = { session.value.toOutboxBinding() },
            bindingChanges = session.map { it.toOutboxBinding() }, onEnqueued = { scheduled++ },
            onRowsDeleted = { repository.collectOrphans() })
        return UploadIntentRepository(provider, outbox, fileStore,
            adapters.uploadPayloadAdapter, adapters.uploadReceiptAdapter, settings)
    }

    fun reopen(): UploadIntentRepository {
        database.close()
        database = openDatabase()
        fileStore = UploadIntentFileStore(context) { availableBytes ?: it.usableSpace }
        repository = newRepository()
        return repository
    }

    fun request(names: List<String> = listOf("a.png", "b.png", "c.png")): UploadBatchRequest = UploadBatchRequest(
        id = UUID.randomUUID().toString(), imageRefs = names,
        expectedBinding = requireNotNull(repository.currentUploadBinding()), prepare = { image(it) },
    )

    fun image(name: String): PreparedUploadImage = PreparedUploadImage(
        fileName = name, contentType = "image/png", bytes = name.toByteArray(),
        sourceSizeBytes = name.length.toLong(), preparationDurationMs = 17L,
    )

    fun original(key: String): File = File(directory, "upload-intents/$key.upload")

    override fun close() {
        database.close()
        check(base.deleteDatabase(databaseName))
        check(directory.parentFile.canonicalFile == base.cacheDir.canonicalFile)
        check(directory.name.startsWith("upload-repository-test-"))
        check(directory.deleteRecursively())
    }

    companion object {
        const val NOW = "2026-09-07T00:00:00.000Z"
        val RECEIPT = UploadResponseDto(42L, "original-expense", "original-task", "pending", "queued",
            "a".repeat(64), null, "none", null, 5L, 7L, mapOf("save" to 3L))
    }
}

private fun repositoryUploadSession() = LocalSessionRecord(
    sessionGeneration = "upload-session", bindingRevision = "upload-binding",
    serverId = "71000000-0000-4000-8000-000000000001", dataGeneration = "71000000-0000-4000-8000-000000000002",
    serverUrl = "https://upload.example.test", credential = StoredSessionToken(token = "synthetic-session"),
    identity = LocalSessionIdentity(accountPublicId = "71000000-0000-4000-8000-000000000003",
        devicePublicId = "71000000-0000-4000-8000-000000000004", accountName = "家庭成员", ledgerId = "family",
        ledgerName = "家庭账本", deviceName = "测试手机", role = "member", boundAt = UploadIntentRepositoryFixture.NOW),
)

private inline fun <reified T> repositoryUploadProxy(crossinline answer: (String, Array<out Any?>) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, args ->
        answer(method.name, args.orEmpty())
    } as T
