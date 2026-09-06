package com.ticketbox.data.repository

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import android.provider.MediaStore
import androidx.annotation.RequiresApi
import androidx.room.Room
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.RepositoryGraph
import com.ticketbox.RepositoryGraphDependencies
import com.ticketbox.RepositoryGraphOutbox
import com.ticketbox.data.local.AppDatabase
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiClient
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.CategoriesDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.LocalSessionRecord
import com.ticketbox.security.LocalSessionStore
import com.ticketbox.security.SessionCredentialAdapter
import com.ticketbox.security.StoredSessionToken
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.IOException
import java.lang.reflect.Proxy
import java.time.Clock
import java.util.UUID
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.flow.MutableStateFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import retrofit2.HttpException

/** Disk Room and real repositories. Only HTTP, session storage and the last-upload timestamp are synthetic. */
@RequiresApi(29)
internal class UploadIntentConnectedFixture(private val context: Context) : Closeable {
    private val testId = UUID.randomUUID().toString()
    private val databaseName = "upload-intent-$testId.db"
    private var database: AppDatabase? = null
    private val session = MutableStateFlow(uploadSession())
    val network = UploadIntentConnectedNetwork()
    val sourceUris = linkedMapOf<String, Uri>()
    val sourceBytes = linkedMapOf<String, ByteArray>()
    val savedUploadLedgers = CopyOnWriteArrayList<String>()

    fun createSources(): List<String> {
        listOf("a.png", "b.png", "c.png").forEachIndexed { index, name ->
            val bitmap = Bitmap.createBitmap(2, 2, Bitmap.Config.ARGB_8888)
            bitmap.eraseColor(0xff112233.toInt() + index)
            val bytes = ByteArrayOutputStream().use { output ->
                check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output))
                output.toByteArray()
            }
            bitmap.recycle()
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, name)
                put(MediaStore.Images.Media.MIME_TYPE, "image/png")
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/TicketboxUploadIntent-$testId")
            }
            val uri = requireNotNull(context.contentResolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values))
            sourceUris[name] = uri
            sourceBytes[name] = bytes
            requireNotNull(context.contentResolver.openOutputStream(uri)).use { it.write(bytes) }
        }
        return sourceUris.values.map(Uri::toString)
    }

    fun revokeSources() {
        val remaining = sourceUris.values.iterator()
        while (remaining.hasNext()) {
            val uri = remaining.next()
            check(context.contentResolver.delete(uri, null, null) == 1)
            remaining.remove()
            check(runCatching { context.contentResolver.openInputStream(uri)?.use { it.read() } }.getOrNull() == null)
        }
    }

    fun reopen(): RepositoryGraph {
        database?.close()
        val db = Room.databaseBuilder(context, AppDatabase::class.java, databaseName).build().also { database = it }
        val sessions = uploadProxy<LocalSessionStore> { method, _ -> when (method) {
            "currentSession" -> session.value
            "observeSession" -> session
            "hasPersistedSessionState" -> true
            else -> error("Unexpected session method: $method")
        } }
        val settings = uploadProxy<TicketboxSettingsStore> { method, args -> when (method) {
            "saveLastUploadAtForLedger" -> { savedUploadLedgers += args[0] as String; Unit }
            else -> error("Unexpected upload settings method: $method")
        } }
        val credentials = SessionCredentialAdapter(sessions)
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
                check(baseUrl == session.value.serverUrl)
                check(tokenProvider() == session.value.credential.token)
                return network.service
            }
        }
        val outbox = OutboxRepository(db.pendingMutationDao(), Clock.systemUTC(),
            bindingProvider = { session.value.toOutboxBinding() })
        return RepositoryGraph(RepositoryGraphDependencies(db, ApiClient(), settings, sessions, credentials,
            ApiServiceProvider(factory, sessions, credentials), RepositoryGraphOutbox(outbox, OutboxAdapterGraph())))
    }

    fun hasDiskDatabase(): Boolean = context.getDatabasePath(databaseName).isFile

    override fun close() {
        database?.close()
        context.deleteDatabase(databaseName)
        sourceUris.values.forEach { context.contentResolver.delete(it, null, null) }
    }
}

internal data class UploadAttempt(val name: String, val bytes: ByteArray, val timezone: String?)

/** The remote model owns accepted receipts only; it never saves or reconstructs local B/C upload intents. */
internal class UploadIntentConnectedNetwork {
    val attempts = CopyOnWriteArrayList<UploadAttempt>()
    private val accepted = CopyOnWriteArrayList<ExpenseDto>()
    val service = object : ApiService by uploadProxy<ApiService>({ method, _ -> throw IOException("Unexpected API: $method") }) {
        override suspend fun pendingExpenses(): List<ExpenseDto> = accepted.toList()
        override suspend fun categories() = CategoriesDto(listOf("未分类", "餐饮"))
        override suspend fun getBackgroundTask(publicId: String) = BackgroundTaskDto(
            publicId = publicId, taskType = "expense_enrichment", status = "completed",
            resultSummary = mapOf("outcome" to "no_result"), createdAt = "2026-09-07T00:00:00Z",
        )
        override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?): UploadResponseDto {
            val disposition = requireNotNull(file.headers?.get("Content-Disposition"))
            val name = requireNotNull(Regex("filename=\"([^\"]+)\"").find(disposition)).groupValues[1]
            val bytes = Buffer().also { file.body.writeTo(it) }.readByteArray()
            attempts += UploadAttempt(name, bytes, timezone)
            if (name == "b.png" && attempts.count { it.name == name } == 1) {
                throw HttpException(retrofit2.Response.error<UploadResponseDto>(503,
                    """{"error":"enrichment_capacity_full","message":"识别队列暂时已满"}"""
                        .toResponseBody("application/json".toMediaType())))
            }
            val expense = uploadedExpense((accepted.size + 1).toLong(), name)
            accepted += expense
            return UploadResponseDto(expense.id, requireNotNull(expense.publicId), "upload-task-${expense.id}",
                "pending", "已保存待确认账单", bytes.size.toLong())
        }
    }
}

private fun uploadedExpense(id: Long, name: String) = ExpenseDto(id = id, publicId = "uploaded-$id",
    amountCents = null, homeCurrency = "CNY", merchant = name, category = "未分类", note = null,
    source = "Android截图", imagePath = null, thumbnailPath = null, imageHash = null, rawText = null,
    confidence = null, duplicateStatus = "none", duplicateOfId = null, duplicateReason = null, tags = null,
    valueScore = null, regretScore = null, status = "pending", expenseTime = null,
    createdAt = "2026-09-07T00:00:00Z", updatedAt = "2026-09-07T00:00:00Z", rowVersion = 1,
    confirmedAt = null, rejectedAt = null)

private fun uploadSession() = LocalSessionRecord(sessionGeneration = "upload-session", bindingRevision = "upload-binding",
    serverId = "70000000-0000-4000-8000-000000000001", dataGeneration = "70000000-0000-4000-8000-000000000002",
    serverUrl = "https://upload.example.test", credential = StoredSessionToken(token = "synthetic-upload-session"),
    identity = LocalSessionIdentity(accountPublicId = "70000000-0000-4000-8000-000000000003",
        devicePublicId = "70000000-0000-4000-8000-000000000004", accountName = "家庭成员", ledgerId = "upload-ledger",
        ledgerName = "家庭账本", deviceName = "测试手机", role = "member", boundAt = "2026-09-07T00:00:00Z"))

private inline fun <reified T> uploadProxy(crossinline answer: (String, Array<out Any?>) -> Any?): T =
    Proxy.newProxyInstance(T::class.java.classLoader, arrayOf(T::class.java)) { _, method, args ->
        answer(method.name, args.orEmpty())
    } as T
